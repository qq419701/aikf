# -*- coding: utf-8 -*-
"""
进程监控页面（核心页面）
左右分栏：左侧进程列表，右侧详情面板
"""

import time
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QClipboard
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QScrollArea, QLabel, QFrame, QPlainTextEdit,
    QApplication
)
from qfluentwidgets import (
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, CardWidget, InfoBar, InfoBarPosition
)

from core.process_watcher import ProcessWatcher, ShopProcess


class ProcessCard(QFrame):
    """进程卡片"""
    NORMAL_STYLE = """
        QFrame {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 8px;
        }
        QFrame:hover { border-color: #0078d4; }
    """
    SELECTED_STYLE = """
        QFrame {
            background: #e8f0fe;
            border: 2px solid #0078d4;
            border-radius: 8px;
            padding: 8px;
        }
    """

    def __init__(self, sp: ShopProcess, parent=None):
        super().__init__(parent)
        self.sp = sp
        self.selected = False
        self._click_callback = None
        self.setStyleSheet(self.NORMAL_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()

    def _build_ui(self):
        """构建卡片UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        # 第一行：状态灯 + 平台名 + 进程名
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        status_icon = '🟢' if self.sp.status == 'running' else '🟡'
        status_label = QLabel(status_icon)
        status_label.setFixedWidth(20)
        row1.addWidget(status_label)

        name_label = QLabel(f'{self.sp.platform_name} · {self.sp.name}')
        name_label.setStyleSheet('font-weight: bold; font-size: 13px;')
        row1.addWidget(name_label)
        row1.addStretch()
        layout.addLayout(row1)

        # 第二行：PID + 内存
        pid_label = QLabel(f'PID: {self.sp.pid}  内存: {self.sp.memory_mb:.1f} MB')
        pid_label.setStyleSheet('font-size: 11px; color: #888;')
        layout.addWidget(pid_label)

        # 第三行：店铺名（有的话）
        if self.sp.shop_name:
            shop_label = QLabel(f'🏪 {self.sp.shop_name}')
            shop_label.setStyleSheet('font-size: 11px; color: #0078d4;')
            layout.addWidget(shop_label)

    def set_selected(self, selected: bool):
        """设置选中状态"""
        self.selected = selected
        self.setStyleSheet(self.SELECTED_STYLE if selected else self.NORMAL_STYLE)

    def set_click_callback(self, callback):
        """设置点击回调"""
        self._click_callback = callback

    def mousePressEvent(self, event):
        """点击卡片"""
        if event.button() == Qt.MouseButton.LeftButton and self._click_callback:
            self._click_callback(self.sp.pid)


class MonitorPage(QWidget):
    """进程监控页面"""

    def __init__(self, watcher: ProcessWatcher = None, parent=None):
        super().__init__(parent)
        self._watcher = watcher
        self._cards: dict = {}       # pid -> ProcessCard
        self._selected_pid: int = -1
        self.setObjectName('monitorPage')
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """构建UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ── 左侧面板 ──
        left_widget = QWidget()
        left_widget.setMinimumWidth(260)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(16, 16, 8, 16)
        left_layout.setSpacing(8)

        # 标题行
        title_row = QHBoxLayout()
        left_title = SubtitleLabel('检测到的进程')
        self._scan_btn = PushButton('🔄 立即扫描')
        self._scan_btn.setFixedHeight(32)
        self._scan_btn.clicked.connect(self._on_force_scan)
        title_row.addWidget(left_title)
        title_row.addStretch()
        title_row.addWidget(self._scan_btn)
        left_layout.addLayout(title_row)

        # 扫描状态
        self._status_label = CaptionLabel('等待扫描...')
        self._status_label.setStyleSheet('color: #888;')
        left_layout.addWidget(self._status_label)

        # 进程卡片滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 空状态提示
        self._empty_label = QLabel('🔍 未检测到客服软件\n请打开拼多多/京东商家客服软件')
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet('color: #aaa; font-size: 13px; padding: 24px;')
        self._cards_layout.addWidget(self._empty_label)

        scroll.setWidget(self._cards_container)
        left_layout.addWidget(scroll)

        # ── 右侧面板 ──
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 16, 16, 16)
        right_layout.setSpacing(8)

        # 右侧滚动区
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._detail_container = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(8)
        self._detail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._no_select_label = QLabel('← 点击左侧进程查看详情')
        self._no_select_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_select_label.setStyleSheet('color: #aaa; font-size: 14px; padding: 60px;')
        self._detail_layout.addWidget(self._no_select_label)

        right_scroll.setWidget(self._detail_container)
        right_layout.addWidget(right_scroll)

        # 底部按钮
        btn_row = QHBoxLayout()
        self._copy_btn = PushButton('📋 复制全部信息')
        self._copy_btn.setFixedHeight(34)
        self._copy_btn.clicked.connect(self._on_copy_info)
        self._deep_scan_btn = PrimaryPushButton('🔍 深度扫描')
        self._deep_scan_btn.setFixedHeight(34)
        self._deep_scan_btn.clicked.connect(self._on_deep_scan)
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._deep_scan_btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 700])

        main_layout.addWidget(splitter)

    def _connect_signals(self):
        """连接 watcher 信号"""
        if not self._watcher:
            return
        self._watcher.process_found.connect(self._on_process_found)
        self._watcher.process_lost.connect(self._on_process_lost)
        self._watcher.process_updated.connect(self._on_process_updated)
        self._watcher.scan_completed.connect(self._on_scan_completed)

    def _on_process_found(self, sp: ShopProcess):
        """添加新进程卡片"""
        card = ProcessCard(sp)
        card.set_click_callback(self._on_card_clicked)
        self._cards[sp.pid] = card
        self._cards_layout.addWidget(card)
        self._empty_label.hide()

    def _on_process_lost(self, pid: int):
        """移除进程卡片"""
        if pid in self._cards:
            card = self._cards.pop(pid)
            self._cards_layout.removeWidget(card)
            card.deleteLater()
            # 如果是当前选中的进程，清空右侧详情
            if self._selected_pid == pid:
                self._selected_pid = -1
                self._clear_detail()
        # 没有进程时显示空状态
        if not self._cards:
            self._empty_label.show()

    def _on_process_updated(self, sp: ShopProcess):
        """进程信息更新"""
        # 刷新卡片
        if sp.pid in self._cards:
            old_card = self._cards[sp.pid]
            idx = self._cards_layout.indexOf(old_card)
            new_card = ProcessCard(sp)
            new_card.set_click_callback(self._on_card_clicked)
            if self._selected_pid == sp.pid:
                new_card.set_selected(True)
            self._cards_layout.insertWidget(idx, new_card)
            self._cards_layout.removeWidget(old_card)
            old_card.deleteLater()
            self._cards[sp.pid] = new_card
            # 刷新右侧详情
            if self._selected_pid == sp.pid:
                self._show_detail(sp)

    def _on_scan_completed(self, processes: list):
        """扫描完成，更新时间戳"""
        now = datetime.now().strftime('%H:%M:%S')
        self._status_label.setText(f'自动扫描中... 上次: {now}')

    def _on_card_clicked(self, pid: int):
        """点击卡片，显示右侧详情"""
        # 取消旧选中
        if self._selected_pid in self._cards:
            self._cards[self._selected_pid].set_selected(False)
        self._selected_pid = pid
        if pid in self._cards:
            self._cards[pid].set_selected(True)
        # 找到进程信息
        for sp in self._watcher.get_all() if self._watcher else []:
            if sp.pid == pid:
                self._show_detail(sp)
                return

    def _on_force_scan(self):
        """立即扫描"""
        if self._watcher:
            self._watcher.force_scan()
        self._status_label.setText('正在扫描...')

    def _clear_detail(self):
        """清空右侧详情"""
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._no_select_label = QLabel('← 点击左侧进程查看详情')
        self._no_select_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_select_label.setStyleSheet('color: #aaa; font-size: 14px; padding: 60px;')
        self._detail_layout.addWidget(self._no_select_label)

    def _show_detail(self, sp: ShopProcess):
        """在右侧显示进程详情"""
        # 清空旧内容
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        elapsed = int(time.time() - sp.create_time) if sp.create_time else 0
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60

        def section(title: str) -> QLabel:
            lbl = QLabel(title)
            lbl.setStyleSheet(
                'font-size: 12px; font-weight: bold; color: #555; '
                'border-bottom: 1px solid #eee; padding-bottom: 2px; margin-top: 8px;'
            )
            return lbl

        def row(label: str, value: str, color: str = '#333') -> QHBoxLayout:
            lo = QHBoxLayout()
            lo.setSpacing(8)
            k = QLabel(f'{label}:')
            k.setStyleSheet('color: #888; font-size: 12px; min-width: 90px;')
            v = QLabel(value)
            v.setStyleSheet(f'color: {color}; font-size: 12px;')
            v.setWordWrap(True)
            lo.addWidget(k)
            lo.addWidget(v)
            lo.addStretch()
            return lo

        # ── 基础信息 ──
        self._detail_layout.addWidget(section('基础信息'))
        name_lbl = QLabel(sp.name)
        name_lbl.setStyleSheet('font-size: 18px; font-weight: bold; color: #222;')
        self._detail_layout.addWidget(name_lbl)
        self._detail_layout.addLayout(row('运行状态', sp.status, '#2e7d32'))
        self._detail_layout.addLayout(row('PID', str(sp.pid)))
        self._detail_layout.addLayout(row('平台', sp.platform_name))
        self._detail_layout.addLayout(row('路径', sp.exe_path or '未知'))
        self._detail_layout.addLayout(row('启动时间', sp.create_time_str or '未知'))
        self._detail_layout.addLayout(row('CPU', f'{sp.cpu_percent:.1f}%'))
        self._detail_layout.addLayout(row('内存', f'{sp.memory_mb:.1f} MB'))

        # ── 网络连接 ──
        self._detail_layout.addWidget(section('网络连接'))
        self._detail_layout.addLayout(row('TCP连接总数', str(sp.tcp_count)))
        ws_count = len(sp.ws_connections)
        self._detail_layout.addLayout(row('疑似WS连接数', str(ws_count), '#0078d4' if ws_count else '#333'))
        for conn in sp.ws_connections:
            ws_lbl = QLabel(f'⭐ {conn.remote_ip}:{conn.remote_port}  [{conn.status}]')
            ws_lbl.setStyleSheet('font-size: 12px; color: #0078d4; padding-left: 100px;')
            self._detail_layout.addWidget(ws_lbl)

        # ── 本地数据目录 ──
        self._detail_layout.addWidget(section('本地数据目录'))
        if sp.local_data_dirs:
            for d in sp.local_data_dirs:
                self._detail_layout.addLayout(row('目录', d))
            cookies = sp.data_files.get('cookies_files', [])
            local_storage = sp.data_files.get('local_storage_dirs', [])
            indexeddb = sp.data_files.get('indexeddb_dirs', [])
            json_configs = sp.data_files.get('json_configs', [])
            self._detail_layout.addLayout(
                row('Cookies', '✅ 存在' if cookies else '❌ 未找到',
                    '#2e7d32' if cookies else '#e53935')
            )
            self._detail_layout.addLayout(
                row('Local Storage', '✅ 存在' if local_storage else '❌ 未找到',
                    '#2e7d32' if local_storage else '#e53935')
            )
            self._detail_layout.addLayout(
                row('IndexedDB', '✅ 存在' if indexeddb else '❌ 未找到',
                    '#2e7d32' if indexeddb else '#e53935')
            )
            self._detail_layout.addLayout(row('配置文件数量', str(len(json_configs))))
        else:
            self._detail_layout.addWidget(QLabel('  未找到本地数据目录'))

        # ── 调试信息 ──
        self._detail_layout.addWidget(section('调试信息'))
        if sp.debug_port:
            self._detail_layout.addLayout(
                row('CDP调试端口', f'✅ {sp.debug_port}', '#2e7d32')
            )
        else:
            self._detail_layout.addLayout(row('CDP调试端口', '❌ 未开启', '#e53935'))
        for title in sp.window_titles:
            self._detail_layout.addLayout(row('窗口标题', title))
        if sp.shop_name:
            self._detail_layout.addLayout(row('疑似店铺名', sp.shop_name, '#0078d4'))
        self._detail_layout.addLayout(row('疑似Token数量', str(len(sp.suspected_tokens))))

        # ── 命令行参数 ──
        if sp.cmdline_str:
            self._detail_layout.addWidget(section('命令行参数'))
            cmd_box = QPlainTextEdit()
            cmd_box.setReadOnly(True)
            cmd_box.setPlainText(sp.cmdline_str)
            cmd_box.setMaximumHeight(80)
            font = QFont('Consolas', 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            cmd_box.setFont(font)
            self._detail_layout.addWidget(cmd_box)

        # ── 相关文件 ──
        if sp.open_files:
            self._detail_layout.addWidget(section('相关文件（最多10个）'))
            for fpath in sp.open_files[:10]:
                lbl = QLabel(fpath)
                font = QFont('Consolas', 10)
                font.setStyleHint(QFont.StyleHint.Monospace)
                lbl.setFont(font)
                lbl.setStyleSheet('font-size: 11px; color: #555;')
                lbl.setWordWrap(True)
                self._detail_layout.addWidget(lbl)

        # ── 子进程 ──
        if sp.children:
            self._detail_layout.addWidget(section('子进程（最多5个）'))
            for child in sp.children[:5]:
                self._detail_layout.addLayout(
                    row(str(child.get('pid')), child.get('name', ''))
                )

        self._detail_layout.addStretch()

    def _on_copy_info(self):
        """复制全部进程信息到剪贴板"""
        if self._selected_pid < 0 or not self._watcher:
            return
        sp = None
        for p in self._watcher.get_all():
            if p.pid == self._selected_pid:
                sp = p
                break
        if not sp:
            return

        lines = [
            f'进程名: {sp.name}',
            f'PID: {sp.pid}',
            f'平台: {sp.platform_name}',
            f'路径: {sp.exe_path}',
            f'状态: {sp.status}',
            f'CPU: {sp.cpu_percent:.1f}%',
            f'内存: {sp.memory_mb:.1f} MB',
            f'启动时间: {sp.create_time_str}',
            f'命令行: {sp.cmdline_str}',
            f'TCP连接数: {sp.tcp_count}',
            f'WS连接数: {len(sp.ws_connections)}',
            f'调试端口: {sp.debug_port or "无"}',
            f'窗口标题: {"; ".join(sp.window_titles)}',
            f'店铺名: {sp.shop_name or "未知"}',
            f'疑似Token数: {len(sp.suspected_tokens)}',
            f'数据目录: {"; ".join(sp.local_data_dirs)}',
        ]
        text = '\n'.join(lines)
        QApplication.clipboard().setText(text)
        InfoBar.success(
            title='已复制',
            content='进程信息已复制到剪贴板',
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def _on_deep_scan(self):
        """深度扫描当前选中进程"""
        if self._selected_pid < 0 or not self._watcher:
            return
        detail = self._watcher.get_process_detail(self._selected_pid)
        if 'error' in detail:
            InfoBar.error(
                title='深度扫描失败',
                content=detail['error'],
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )
        else:
            InfoBar.success(
                title='深度扫描完成',
                content=f'IndexedDB文件: {detail.get("data_files", {}).get("indexeddb_files", 0)} 个',
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )
