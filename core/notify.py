# -*- coding: utf-8 -*-
"""
通知模块
使用系统托盘气泡通知
"""

from PyQt6.QtWidgets import QSystemTrayIcon
from PyQt6.QtCore import QObject


class Notifier(QObject):
    """系统通知管理器"""

    def __init__(self, tray: QSystemTrayIcon = None, parent=None):
        super().__init__(parent)
        self._tray = tray

    def set_tray(self, tray: QSystemTrayIcon):
        """设置系统托盘图标"""
        self._tray = tray

    def notify(self, title: str, message: str, duration: int = 3000, level: str = 'info'):
        """
        发送系统托盘气泡通知
        :param title: 通知标题
        :param message: 通知内容
        :param duration: 持续时间（毫秒）
        :param level: 通知级别 info/warning/critical
        """
        if not self._tray:
            return
        icon_map = {
            'info': QSystemTrayIcon.MessageIcon.Information,
            'warning': QSystemTrayIcon.MessageIcon.Warning,
            'critical': QSystemTrayIcon.MessageIcon.Critical,
        }
        icon = icon_map.get(level, QSystemTrayIcon.MessageIcon.Information)
        self._tray.showMessage(title, message, icon, duration)
