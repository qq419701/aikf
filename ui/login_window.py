# -*- coding: utf-8 -*-
"""
登录/激活窗口
无边框圆角窗口，支持激活码验证和7天免费试用
"""

import re

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QSizePolicy
)
from qfluentwidgets import (
    LineEdit, PrimaryPushButton, PushButton,
    BodyLabel, CaptionLabel, TitleLabel
)

import config
from version import APP_VERSION, APP_BUILD


class LoginWindow(QWidget):
    """激活登录窗口"""
    activated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = QPoint()
        self._setup_ui()
        self._setup_window()

    def _setup_window(self):
        """配置窗口属性"""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(460, 580)
        # 居中显示
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def _setup_ui(self):
        """构建UI布局"""
        # 主容器（圆角白色背景）
        self._container = QFrame(self)
        self._container.setObjectName('loginContainer')
        self._container.setStyleSheet("""
            #loginContainer {
                background-color: white;
                border-radius: 12px;
                border: 1px solid #e0e0e0;
            }
        """)
        self._container.setGeometry(0, 0, 460, 580)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(12)

        # 右上角关闭按钮
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        close_btn = QLabel('✕')
        close_btn.setStyleSheet("""
            color: #999;
            font-size: 16px;
            padding: 4px 8px;
            border-radius: 4px;
        """)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self.close()
        top_bar.addWidget(close_btn)
        layout.addLayout(top_bar)

        # Logo 区域
        logo_layout = QVBoxLayout()
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.setSpacing(4)

        emoji_label = QLabel('🤖')
        emoji_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_label.setStyleSheet('font-size: 48px;')
        logo_layout.addWidget(emoji_label)

        aikf_label = QLabel('AIKF')
        aikf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        aikf_label.setStyleSheet('color: #0078d4; font-size: 28px; font-weight: bold;')
        logo_layout.addWidget(aikf_label)

        sub_label = QLabel('客服助手')
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setStyleSheet('color: #888; font-size: 14px;')
        logo_layout.addWidget(sub_label)

        layout.addLayout(logo_layout)
        layout.addSpacing(8)

        # 欢迎文字
        welcome_label = QLabel('欢迎使用 AIKF 客服助手')
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label.setStyleSheet('font-size: 16px; font-weight: bold; color: #333;')
        layout.addWidget(welcome_label)

        hint_label = QLabel('请输入授权激活码以开始使用')
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setStyleSheet('font-size: 12px; color: #888;')
        layout.addWidget(hint_label)

        layout.addSpacing(8)

        # 激活码输入框
        self._key_input = LineEdit()
        self._key_input.setPlaceholderText('AIKF-XXXX-XXXX-XXXX')
        self._key_input.setFixedHeight(42)
        self._key_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._key_input)

        # 错误提示
        self._error_label = QLabel('')
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setStyleSheet('color: #e53935; font-size: 12px;')
        self._error_label.hide()
        layout.addWidget(self._error_label)

        # 立即激活按钮
        self._activate_btn = PrimaryPushButton('立即激活')
        self._activate_btn.setFixedHeight(42)
        self._activate_btn.clicked.connect(self._on_activate)
        layout.addWidget(self._activate_btn)

        # 分割线
        sep_layout = QHBoxLayout()
        line_left = QFrame()
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_left.setStyleSheet('color: #e0e0e0;')
        or_label = QLabel('  或  ')
        or_label.setStyleSheet('color: #999; font-size: 12px;')
        line_right = QFrame()
        line_right.setFrameShape(QFrame.Shape.HLine)
        line_right.setStyleSheet('color: #e0e0e0;')
        sep_layout.addWidget(line_left)
        sep_layout.addWidget(or_label)
        sep_layout.addWidget(line_right)
        layout.addLayout(sep_layout)

        # 免费试用按钮
        self._trial_btn = PushButton('免费试用 7 天')
        self._trial_btn.setFixedHeight(42)
        self._trial_btn.clicked.connect(self._on_trial)
        layout.addWidget(self._trial_btn)

        layout.addStretch()

        # 版本号
        version_label = QLabel(f'v{APP_VERSION}  Build {APP_BUILD}')
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet('color: #bbb; font-size: 11px;')
        layout.addWidget(version_label)

    def _on_activate(self):
        """激活码验证逻辑"""
        key = self._key_input.text().strip().upper()
        pattern = re.compile(r'^AIKF-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$')
        if pattern.match(key):
            config.save_license(key)
            self._error_label.hide()
            self.activated.emit()
        else:
            self._error_label.setText('激活码格式不正确，请检查后重新输入')
            self._error_label.show()

    def _on_trial(self):
        """开始免费试用"""
        config.save_trial(7)
        self.activated.emit()

    def mousePressEvent(self, event):
        """记录拖动起始位置"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        """窗口拖动"""
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def paintEvent(self, event):
        """绘制圆角阴影背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        painter.fillPath(path, QColor(255, 255, 255, 0))
