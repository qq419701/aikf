# -*- coding: utf-8 -*-
"""
自动化规则页面（即将上线）
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from qfluentwidgets import SubtitleLabel, CaptionLabel


class RulesPage(QWidget):
    """自动化规则页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('rulesPage')
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel('⚡')
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet('font-size: 64px;')
        layout.addWidget(icon_label)

        title = SubtitleLabel('自动化规则')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = CaptionLabel('功能即将上线')
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet('color: #aaa; font-size: 14px;')
        layout.addWidget(sub)

        layout.addSpacing(16)

        features = [
            '✦ 关键词自动触发回复',
            '✦ 订单状态联动动作',
            '✦ 超时自动提醒',
            '✦ 自动转人工条件',
            '✦ 规则优先级管理',
        ]
        for feat in features:
            lbl = QLabel(feat)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet('color: #aaa; font-size: 13px;')
            layout.addWidget(lbl)

        layout.addSpacing(24)

        tip = QLabel('目前请先使用进程监控功能，确认监控效果后此功能将陆续开放')
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet('color: #bbb; font-size: 12px;')
        layout.addWidget(tip)
