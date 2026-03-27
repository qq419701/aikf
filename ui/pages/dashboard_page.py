# -*- coding: utf-8 -*-
"""
首页 - 数据总览
"""

import time
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem
)
from qfluentwidgets import CardWidget, TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel

from core.process_watcher import ProcessWatcher
from core.db import Database


class StatCard(CardWidget):
    """统计卡片"""

    def __init__(self, title: str, value: str = '0', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)

        self._value_label = TitleLabel(value)
        self._value_label.setStyleSheet('font-size: 28px; font-weight: bold; color: #0078d4;')
        self._title_label = CaptionLabel(title)
        self._title_label.setStyleSheet('color: #666;')

        layout.addWidget(self._value_label)
        layout.addWidget(self._title_label)

    def set_value(self, value: str):
        """更新数值"""
        self._value_label.setText(value)


class DashboardPage(QWidget):
    """首页"""

    def __init__(self, watcher: ProcessWatcher = None, db: Database = None, parent=None):
        super().__init__(parent)
        self._watcher = watcher
        self._db = db
        self._setup_ui()
        self._connect_signals()
        self.setObjectName('dashboardPage')

    def _setup_ui(self):
        """构建UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 标题
        title = TitleLabel('首页总览')
        layout.addWidget(title)

        # 4个统计卡片
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self._card_procs = StatCard('监控进程数', '0')
        self._card_msgs = StatCard('今日消息数', '0')
        self._card_ai = StatCard('AI回复数', '0')
        self._card_mem = StatCard('进程总内存', '0 MB')

        for card in [self._card_procs, self._card_msgs, self._card_ai, self._card_mem]:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        # 进程状态表
        proc_title = SubtitleLabel('进程状态')
        layout.addWidget(proc_title)

        self._proc_table = QTableWidget()
        self._proc_table.setColumnCount(7)
        self._proc_table.setHorizontalHeaderLabels(
            ['平台', '进程名', 'PID', '状态', 'CPU%', '内存(MB)', '运行时长']
        )
        self._proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._proc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._proc_table.horizontalHeader().setStretchLastSection(True)
        self._proc_table.setMaximumHeight(200)
        layout.addWidget(self._proc_table)

        # 最近消息
        msg_title = SubtitleLabel('最近消息')
        layout.addWidget(msg_title)

        self._msg_list = QListWidget()
        self._msg_list.setMaximumHeight(180)
        layout.addWidget(self._msg_list)

        layout.addStretch()

    def _connect_signals(self):
        """连接信号"""
        if self._watcher:
            self._watcher.scan_completed.connect(self._on_scan_completed)

    def _on_scan_completed(self, processes: list):
        """扫描完成，刷新数据"""
        # 更新进程数
        self._card_procs.set_value(str(len(processes)))

        # 更新总内存
        total_mem = sum(p.memory_mb for p in processes)
        self._card_mem.set_value(f'{total_mem:.1f} MB')

        # 更新今日消息数
        if self._db:
            try:
                count = self._db.count_messages_today()
                self._card_msgs.set_value(str(count))
            except Exception:
                pass

        # 刷新进程表
        self._proc_table.setRowCount(0)
        for i, sp in enumerate(processes):
            self._proc_table.insertRow(i)
            elapsed = int(time.time() - sp.create_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            items = [
                sp.platform_name,
                sp.name,
                str(sp.pid),
                sp.status,
                f'{sp.cpu_percent:.1f}',
                f'{sp.memory_mb:.1f}',
                f'{h:02d}:{m:02d}:{s:02d}',
            ]
            for j, text in enumerate(items):
                self._proc_table.setItem(i, j, QTableWidgetItem(text))

        # 刷新最近消息
        if self._db:
            try:
                msgs = self._db.get_messages(limit=10)
                self._msg_list.clear()
                for msg in msgs:
                    direction = '→' if msg.get('direction') == 'out' else '←'
                    content = msg.get('content', '')[:50]
                    self._msg_list.addItem(f"{direction} {content}")
            except Exception:
                pass
