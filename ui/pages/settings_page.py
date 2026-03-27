# -*- coding: utf-8 -*-
"""
系统设置页面
"""

import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFrame, QLabel, QSlider
)
from qfluentwidgets import (
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, LineEdit, SwitchButton,
    InfoBar, InfoBarPosition
)

import config
from version import APP_VERSION, APP_BUILD, GITHUB_REPO
from core.updater import Updater
from core.db import Database


class SettingsPage(QWidget):
    """系统设置页面"""

    def __init__(self, db: Database = None, parent=None):
        super().__init__(parent)
        self._db = db
        self.setObjectName('settingsPage')
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        """构建UI"""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        scroll.setWidget(container)

        # 标题
        layout.addWidget(TitleLabel('系统设置'))

        # ── 数据库 ──
        layout.addWidget(self._section('数据库'))
        db_row = QHBoxLayout()
        self._db_path_label = LineEdit()
        self._db_path_label.setText(config.get_db_path())
        self._db_path_label.setReadOnly(True)
        open_dir_btn = PushButton('打开目录')
        open_dir_btn.clicked.connect(self._open_db_dir)
        db_row.addWidget(QLabel('SQLite路径:'))
        db_row.addWidget(self._db_path_label)
        db_row.addWidget(open_dir_btn)
        layout.addLayout(db_row)

        # MySQL 开关（展开输入）
        mysql_row = QHBoxLayout()
        mysql_row.addWidget(QLabel('启用 MySQL:'))
        self._mysql_switch = SwitchButton()
        self._mysql_switch.checkedChanged.connect(self._on_mysql_toggle)
        mysql_row.addWidget(self._mysql_switch)
        mysql_row.addStretch()
        layout.addLayout(mysql_row)

        self._mysql_panel = QWidget()
        mysql_panel_layout = QVBoxLayout(self._mysql_panel)
        mysql_panel_layout.setContentsMargins(0, 0, 0, 0)
        mysql_panel_layout.setSpacing(8)

        self._mysql_host = LineEdit()
        self._mysql_host.setPlaceholderText('主机地址 (localhost)')
        self._mysql_port = LineEdit()
        self._mysql_port.setPlaceholderText('端口 (3306)')
        self._mysql_db = LineEdit()
        self._mysql_db.setPlaceholderText('数据库名 (aikf)')
        self._mysql_user = LineEdit()
        self._mysql_user.setPlaceholderText('用户名 (root)')
        self._mysql_pass = LineEdit()
        self._mysql_pass.setPlaceholderText('密码')
        self._mysql_pass.setEchoMode(LineEdit.EchoMode.Password)

        for w in [self._mysql_host, self._mysql_port, self._mysql_db,
                  self._mysql_user, self._mysql_pass]:
            mysql_panel_layout.addWidget(w)

        self._mysql_panel.hide()
        layout.addWidget(self._mysql_panel)

        # ── 扫描设置 ──
        layout.addWidget(self._section('扫描设置'))
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel('扫描间隔:'))
        self._interval_slider = QSlider(Qt.Orientation.Horizontal)
        self._interval_slider.setRange(1, 10)
        self._interval_slider.setValue(3)
        self._interval_slider.setFixedWidth(200)
        self._interval_value_label = QLabel('3 秒')
        self._interval_slider.valueChanged.connect(
            lambda v: self._interval_value_label.setText(f'{v} 秒')
        )
        slider_row.addWidget(self._interval_slider)
        slider_row.addWidget(self._interval_value_label)
        slider_row.addStretch()
        layout.addLayout(slider_row)

        # ── 通知 ──
        layout.addWidget(self._section('通知'))

        auto_start_row = QHBoxLayout()
        auto_start_row.addWidget(QLabel('开机自启:'))
        self._auto_start_switch = SwitchButton()
        auto_start_row.addWidget(self._auto_start_switch)
        auto_start_row.addStretch()
        layout.addLayout(auto_start_row)

        tray_row = QHBoxLayout()
        tray_row.addWidget(QLabel('最小化到托盘:'))
        self._tray_switch = SwitchButton()
        tray_row.addWidget(self._tray_switch)
        tray_row.addStretch()
        layout.addLayout(tray_row)

        notify_row = QHBoxLayout()
        notify_row.addWidget(QLabel('桌面通知:'))
        self._notify_switch = SwitchButton()
        notify_row.addWidget(self._notify_switch)
        notify_row.addStretch()
        layout.addLayout(notify_row)

        # 保存按钮
        save_btn = PrimaryPushButton('保存设置')
        save_btn.setFixedWidth(120)
        save_btn.clicked.connect(self._save_settings)
        layout.addWidget(save_btn)

        # ── 维护 ──
        layout.addWidget(self._section('维护'))
        maint_row = QHBoxLayout()

        clear_btn = PushButton('清除消息记录')
        clear_btn.clicked.connect(self._clear_messages)

        update_btn = PushButton('检查更新')
        update_btn.clicked.connect(self._check_update)

        log_btn = PushButton('查看日志文件')
        log_btn.clicked.connect(self._open_log_dir)

        maint_row.addWidget(clear_btn)
        maint_row.addWidget(update_btn)
        maint_row.addWidget(log_btn)
        maint_row.addStretch()
        layout.addLayout(maint_row)

        # ── 关于 ──
        layout.addWidget(self._section('关于'))
        about_layout = QVBoxLayout()
        about_layout.addWidget(QLabel(f'AIKF v{APP_VERSION}'))
        about_layout.addWidget(QLabel(f'Build {APP_BUILD}'))
        about_layout.addWidget(QLabel(f'GitHub: {GITHUB_REPO}'))
        layout.addLayout(about_layout)

        layout.addStretch()

    def _section(self, title: str) -> QLabel:
        """创建分节标题"""
        lbl = QLabel(title)
        lbl.setStyleSheet(
            'font-size: 14px; font-weight: bold; color: #0078d4; '
            'border-bottom: 2px solid #0078d4; padding-bottom: 4px;'
        )
        return lbl

    def _load_config(self):
        """从配置文件加载设置"""
        cfg = config.get_app_config()
        self._interval_slider.setValue(cfg.get('scan_interval', 3))
        self._interval_value_label.setText(f'{cfg.get("scan_interval", 3)} 秒')
        self._tray_switch.setChecked(cfg.get('minimize_to_tray', True))
        self._notify_switch.setChecked(cfg.get('desktop_notify', True))
        self._auto_start_switch.setChecked(cfg.get('auto_start', False))

        use_mysql = cfg.get('db_type', 'sqlite') == 'mysql'
        self._mysql_switch.setChecked(use_mysql)
        if use_mysql:
            self._mysql_panel.show()
        self._mysql_host.setText(cfg.get('mysql_host', 'localhost'))
        self._mysql_port.setText(str(cfg.get('mysql_port', 3306)))
        self._mysql_db.setText(cfg.get('mysql_db', 'aikf'))
        self._mysql_user.setText(cfg.get('mysql_user', 'root'))

    def _save_settings(self):
        """保存设置"""
        cfg = config.get_app_config()
        cfg['scan_interval'] = self._interval_slider.value()
        cfg['minimize_to_tray'] = self._tray_switch.isChecked()
        cfg['desktop_notify'] = self._notify_switch.isChecked()
        cfg['auto_start'] = self._auto_start_switch.isChecked()
        cfg['db_type'] = 'mysql' if self._mysql_switch.isChecked() else 'sqlite'
        cfg['mysql_host'] = self._mysql_host.text()
        try:
            cfg['mysql_port'] = int(self._mysql_port.text())
        except ValueError:
            cfg['mysql_port'] = 3306
        cfg['mysql_db'] = self._mysql_db.text()
        cfg['mysql_user'] = self._mysql_user.text()
        # 密码加密保存
        if self._mysql_pass.text():
            cfg['mysql_pass_enc'] = config._encrypt(self._mysql_pass.text())
        config.save_app_config(cfg)
        InfoBar.success(
            title='已保存',
            content='设置已保存',
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def _on_mysql_toggle(self, checked: bool):
        """MySQL 开关切换"""
        if checked:
            self._mysql_panel.show()
        else:
            self._mysql_panel.hide()

    def _open_db_dir(self):
        """打开数据库目录"""
        db_dir = config.get_config_dir()
        self._open_directory(db_dir)

    def _open_log_dir(self):
        """打开日志目录"""
        log_dir = config.get_log_dir()
        self._open_directory(log_dir)

    def _open_directory(self, path: str):
        """用系统文件管理器打开目录"""
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            InfoBar.error(
                title='打开失败',
                content=str(e),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )

    def _clear_messages(self):
        """清除所有消息记录"""
        if self._db:
            try:
                self._db.execute('DELETE FROM messages')
                InfoBar.success(
                    title='已清除',
                    content='消息记录已清除',
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self
                )
            except Exception as e:
                InfoBar.error(
                    title='清除失败',
                    content=str(e),
                    duration=3000,
                    position=InfoBarPosition.TOP,
                    parent=self
                )

    def _check_update(self):
        """检查更新"""
        self._updater = Updater(self)

        def on_found(info):
            InfoBar.info(
                title='发现新版本',
                content=f'新版本 {info["version"]} 已发布',
                duration=5000,
                position=InfoBarPosition.TOP,
                parent=self
            )

        def on_no():
            InfoBar.success(
                title='已是最新版本',
                content=f'当前版本 v{APP_VERSION} 已是最新',
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )

        def on_error(err):
            InfoBar.error(
                title='检查失败',
                content=err,
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )

        self._updater.update_found.connect(on_found)
        self._updater.no_update.connect(on_no)
        self._updater.check_error.connect(on_error)
        self._updater.check()
