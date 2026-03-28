# -*- coding: utf-8 -*-
"""
主窗口
基于 FluentWindow，包含侧边栏导航和系统托盘
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition, InfoBar, InfoBarPosition

from core.process_watcher import ProcessWatcher
from core.updater import Updater
from core.notify import Notifier
from core.db import Database
from ui.pages.dashboard_page import DashboardPage
from ui.pages.monitor_page import MonitorPage
from ui.pages.detect_page import DetectPage
from ui.pages.ai_page import AiPage
from ui.pages.knowledge_page import KnowledgePage
from ui.pages.rules_page import RulesPage
from ui.pages.uhaozu_page import UhaozuPage
from ui.pages.stats_page import StatsPage
from ui.pages.settings_page import SettingsPage


class MainWindow(FluentWindow):
    """主窗口"""

    def __init__(self, db: Database = None, parent=None):
        super().__init__(parent)
        self.db = db
        self._setup_window()
        self._setup_tray()
        self._setup_watcher()
        self._setup_pages()
        self._setup_updater()

    def _setup_window(self):
        """配置窗口基本属性"""
        self.setWindowTitle('AIKF 客服助手')
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def _setup_tray(self):
        """初始化系统托盘"""
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip('AIKF 客服助手')

        # 托盘右键菜单
        tray_menu = QMenu()
        show_action = tray_menu.addAction('显示主窗口')
        show_action.triggered.connect(self._show_main)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction('退出')
        quit_action.triggered.connect(QApplication.quit)
        self._tray.setContextMenu(tray_menu)

        # 双击显示主窗口
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # 通知器
        self._notifier = Notifier(self._tray)

    def _setup_watcher(self):
        """初始化进程监控"""
        self._watcher = ProcessWatcher(scan_interval=3.0)
        self._watcher.process_found.connect(self._on_process_found)
        self._watcher.start()

    def _setup_pages(self):
        """添加导航页面"""
        # 首页
        self._dashboard = DashboardPage(watcher=self._watcher, db=self.db)
        self.addSubInterface(self._dashboard, FluentIcon.HOME, '首页')

        # 进程监控（默认选中）
        self._monitor = MonitorPage(watcher=self._watcher)
        self.addSubInterface(self._monitor, FluentIcon.SEARCH, '进程监控')

        # 数据检测（进程监控之后）
        self._detect = DetectPage(watcher=self._watcher)
        self.addSubInterface(self._detect, FluentIcon.SEARCH_MIRROR, '数据检测')

        # AI 设置
        self._ai = AiPage()
        self.addSubInterface(self._ai, FluentIcon.ROBOT, 'AI 设置')

        # 快捷话术
        self._knowledge = KnowledgePage()
        self.addSubInterface(self._knowledge, FluentIcon.BOOK_SHELF, '快捷话术')

        # 自动化规则
        self._rules = RulesPage()
        self.addSubInterface(self._rules, FluentIcon.SETTING, '自动化规则')

        # U号租
        self._uhaozu = UhaozuPage()
        self.addSubInterface(self._uhaozu, FluentIcon.GAME, 'U号租')

        # 数据统计
        self._stats = StatsPage()
        self.addSubInterface(self._stats, FluentIcon.PIE_SINGLE, '数据统计')

        # 系统设置（底部）
        self._settings = SettingsPage(db=self.db)
        self.addSubInterface(
            self._settings, FluentIcon.SETTING, '系统设置',
            position=NavigationItemPosition.BOTTOM
        )

        # 默认选中进程监控
        self.switchTo(self._monitor)

    def _setup_updater(self):
        """初始化自动更新检查，延迟2秒启动"""
        self._updater = Updater(self)
        self._updater.update_found.connect(self._on_update_found)
        QTimer.singleShot(2000, self._updater.check)

    def _on_process_found(self, sp):
        """检测到新进程时发送托盘通知"""
        self._notifier.notify(
            '检测到客服软件',
            f'已检测到 {sp.platform_name} 进程: {sp.name} (PID: {sp.pid})',
            level='info'
        )

    def _on_update_found(self, info: dict):
        """发现新版本时显示顶部提示"""
        InfoBar.info(
            title='发现新版本',
            content=f'新版本 {info["version"]} 已发布，请前往 GitHub 下载更新',
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            duration=8000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def _on_tray_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_main()

    def _show_main(self):
        """显示主窗口"""
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        """关闭主窗口时最小化到托盘"""
        event.ignore()
        self.hide()
        self._notifier.notify('AIKF 客服助手', '已最小化到托盘，右键托盘图标可退出', level='info')
