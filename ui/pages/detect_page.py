# -*- coding: utf-8 -*-
"""
CDP 数据检测页面
通过 Chrome DevTools Protocol 实时采集 Electron 客服软件中的页面数据：
聊天消息、Cookies、LocalStorage、页面文本、网络请求
"""

import json
import subprocess
import threading
from datetime import datetime

import psutil
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPlainTextEdit,
    QApplication, QSplitter, QListWidget, QListWidgetItem,
    QTabWidget, QLineEdit, QFrame, QMessageBox,
)
from qfluentwidgets import (
    SubtitleLabel, CaptionLabel,
    PushButton, PrimaryPushButton,
    InfoBar, InfoBarPosition,
    ComboBox,
)

from core.process_watcher import ProcessWatcher
from core import cdp_reader



# ─────────────────────── 后台 CDP 扫描线程 ─────────────────────────────────
class _CdpScanWorker(QThread):
    """后台 CDP 扫描线程：一次性扫描所有页面，不阻塞 UI"""
    finished = pyqtSignal(dict)   # 扫描成功，传回汇总数据 dict
    error = pyqtSignal(str)       # 扫描失败，传回错误信息

    def __init__(self, debug_port: int):
        super().__init__()
        self._debug_port = debug_port

    def run(self):
        """在后台线程中执行 CDP 全页面扫描"""
        try:
            result = cdp_reader.scan_all_pages(self._debug_port)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────── 后台网络监听线程 ─────────────────────────────────
class _NetworkWorker(QThread):
    """后台网络请求实时监听线程：持续监听直到调用 stop()"""
    network_event = pyqtSignal(dict)   # 每次收到网络事件时触发

    def __init__(self, debug_port: int, ws_url: str):
        super().__init__()
        self._debug_port = debug_port
        self._ws_url = ws_url
        self._client = None
        self._stop_event = threading.Event()  # 用于干净地停止线程

    def run(self):
        """建立 WebSocket 连接并持续监听网络事件"""
        try:
            self._client = cdp_reader.CdpClient(self._debug_port, self._ws_url)
            if not self._client.connect(timeout=5):
                return
            # 启动网络拦截，将事件发射给 UI
            cdp_reader.start_network_intercept(self._client, self._on_event)
            # 等待停止信号，避免忙等待
            self._stop_event.wait()
        except Exception:
            pass
        finally:
            if self._client:
                self._client.disconnect()

    def _on_event(self, event: dict):
        """收到网络事件时，发射信号到 UI 线程"""
        try:
            self.network_event.emit(event)
        except Exception:
            pass

    def stop(self):
        """停止监听"""
        self._stop_event.set()
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass


# ─────────────────────── 后台进程重启线程 ─────────────────────────────────
class _RestartWorker(QThread):
    """
    后台进程重启线程：
    终止旧进程，添加 --remote-debugging-port 参数后重新启动，不阻塞 UI。
    """
    # 重启完成信号：(成功与否, 提示消息)
    finished = pyqtSignal(bool, str)

    def __init__(self, pid: int, port: int = 9222):
        super().__init__()
        self._pid = pid      # 需要重启的进程 PID
        self._port = port    # 要附加的调试端口号（默认 9222）

    def run(self):
        """在后台线程中执行：终止旧进程 → 附加调试参数 → 重新启动"""
        try:
            proc = psutil.Process(self._pid)
            cmdline = proc.cmdline()  # 获取原始命令行参数列表

            debug_flag = f'--remote-debugging-port={self._port}'
            # 如果命令行中还没有调试端口参数，则追加（精确前缀匹配，避免误判其他端口号）
            if not any(arg.startswith('--remote-debugging-port=') for arg in cmdline):
                cmdline.append(debug_flag)

            # 终止旧进程（先 terminate，超时后 kill）
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()

            # 用修改后的命令行重新启动进程
            subprocess.Popen(cmdline)  # noqa: S603 — 命令来自用户已运行进程的原始 cmdline
            self.finished.emit(
                True,
                f'进程已重启，调试端口: {self._port}。'
                '请等待软件完全启动后，再点击「一键检测并扫描」。'
            )
        except Exception as exc:
            self.finished.emit(False, f'重启失败: {exc}')


# ─────────────────────── 工具函数 ──────────────────────────────────────────
def _make_table(columns: list) -> QTableWidget:
    """创建统一风格的只读表格：交替行颜色、禁止编辑、列宽自适应"""
    tbl = QTableWidget(0, len(columns))
    tbl.setHorizontalHeaderLabels(columns)
    tbl.setAlternatingRowColors(True)
    tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = tbl.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    tbl.verticalHeader().setDefaultSectionSize(24)
    return tbl


def _item(text: str, color: str = None) -> QTableWidgetItem:
    """创建只读的表格单元格"""
    it = QTableWidgetItem(str(text))
    it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if color:
        it.setForeground(QColor(color))
    return it

# 弹出无调试端口提示对话框的延迟（毫秒）
# 延迟是为了避免在 currentIndexChanged 信号处理函数中直接弹出对话框，
# 防止 Qt 在信号栈仍在运行时处理模态窗口事件循环导致的异常。
_DIALOG_DELAY_MS = 300


# ─────────────────────── CDP 检测页面主体 ──────────────────────────────────
class DetectPage(QWidget):
    """
    CDP 数据检测页面。
    左侧：进程/端口选择 + 页面列表。
    右侧：聊天消息、Cookies、LocalStorage、页面文本、网络请求 五个 Tab。
    """

    def __init__(self, watcher=None, parent=None):
        super().__init__(parent)
        self._watcher: ProcessWatcher = watcher
        self._scan_worker: _CdpScanWorker = None   # CDP 扫描线程
        self._net_worker: _NetworkWorker = None     # 网络监听线程
        self._restart_worker: _RestartWorker = None # 进程重启线程
        self._last_data: dict = {}                  # 上次扫描结果缓存
        self._pages: list = []                      # 当前端口的页面列表
        self._net_monitoring: bool = False          # 是否正在监听网络
        self._pending_no_debug_sp = None            # 待处理的无调试端口进程
        self.setObjectName('detectPage')
        self._setup_ui()
        self._connect_watcher_signals()

    # ─────────────────────── UI 构建 ───────────────────────────────────────
    def _setup_ui(self):
        """构建整体布局：左右分栏"""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 顶部标题栏
        title_bar = QHBoxLayout()
        title_lbl = SubtitleLabel('📡 数据实时检测')
        title_bar.addWidget(title_lbl)
        title_bar.addStretch()
        # 状态标签：提示用户当前操作状态
        self._status_lbl = CaptionLabel('请选择软件进程后点击「一键检测并扫描」')
        self._status_lbl.setStyleSheet('color: #888;')
        title_bar.addWidget(self._status_lbl)
        root.addLayout(title_bar)

        # 主体左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 左侧面板 ──
        left = QWidget()
        left.setMinimumWidth(220)
        left.setMaximumWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(8)

        # 进程选择下拉框：列出当前检测到的客服软件进程
        proc_lbl = QLabel('第一步：选择客服软件进程')
        proc_lbl.setStyleSheet('font-size: 12px; color: #555; font-weight: bold;')
        left_layout.addWidget(proc_lbl)
        self._proc_combo = ComboBox()
        self._proc_combo.setMinimumWidth(200)
        self._proc_combo.setPlaceholderText('未检测到进程...')
        self._proc_combo.currentIndexChanged.connect(self._on_proc_changed)
        left_layout.addWidget(self._proc_combo)

        # 一键检测按钮：核心操作，自动判断是否需要开启调试模式
        self._one_click_btn = PrimaryPushButton('🚀 一键检测并扫描')
        self._one_click_btn.setFixedHeight(38)
        self._one_click_btn.setToolTip(
            '自动检测进程是否开启调试模式，未开启时提示重启，开启后自动连接采集数据'
        )
        self._one_click_btn.clicked.connect(self._on_one_click_detect)
        left_layout.addWidget(self._one_click_btn)

        # 分隔线：区分常用操作与高级选项
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #ddd; margin: 4px 0;')
        left_layout.addWidget(sep)

        # 高级选项：手动输入调试端口（适合已知端口的高级用户）
        port_lbl = QLabel('高级：手动输入调试端口')
        port_lbl.setStyleSheet('font-size: 11px; color: #999;')
        left_layout.addWidget(port_lbl)
        self._port_input = QLineEdit()
        self._port_input.setPlaceholderText('例如: 9222')
        self._port_input.setMaximumHeight(32)
        left_layout.addWidget(self._port_input)

        # 手动连接按钮：使用输入框中的端口直接连接（高级用户用）
        self._connect_btn = PushButton('🔗 手动连接')
        self._connect_btn.setFixedHeight(30)
        self._connect_btn.setToolTip('使用上方输入框中的端口直接连接扫描（高级选项）')
        self._connect_btn.clicked.connect(self._on_connect)
        left_layout.addWidget(self._connect_btn)

        # 页面列表：显示目标进程中已打开的页面
        page_list_lbl = QLabel('页面列表:')
        page_list_lbl.setStyleSheet('font-size: 12px; color: #555; margin-top: 8px;')
        left_layout.addWidget(page_list_lbl)
        self._page_list = QListWidget()
        self._page_list.setAlternatingRowColors(True)
        self._page_list.currentRowChanged.connect(self._on_page_selected)
        left_layout.addWidget(self._page_list, 1)

        self._copy_btn = PushButton('📋 复制全部数据')
        self._copy_btn.setFixedHeight(30)
        self._copy_btn.clicked.connect(self._on_copy_all)
        left_layout.addWidget(self._copy_btn)

        splitter.addWidget(left)

        # ── 右侧面板：Tab 区域 ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(4)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._tab_chat = QWidget()
        self._setup_tab_chat()
        self._tabs.addTab(self._tab_chat, '💬 聊天消息')

        self._tab_cookies = QWidget()
        self._setup_tab_cookies()
        self._tabs.addTab(self._tab_cookies, '🍪 Cookies')

        self._tab_ls = QWidget()
        self._setup_tab_ls()
        self._tabs.addTab(self._tab_ls, '📦 LocalStorage')

        self._tab_text = QWidget()
        self._setup_tab_text()
        self._tabs.addTab(self._tab_text, '📄 页面文本')

        self._tab_net = QWidget()
        self._setup_tab_net()
        self._tabs.addTab(self._tab_net, '🌐 网络请求')

        right_layout.addWidget(self._tabs, 1)
        splitter.addWidget(right)

        splitter.setSizes([260, 900])
        root.addWidget(splitter, 1)

        # ── 底部日志面板 ──
        log_header = QHBoxLayout()
        log_title = QLabel('📋 运行日志')
        log_title.setStyleSheet('font-size: 11px; font-weight: bold; color: #555;')
        log_header.addWidget(log_title)
        log_header.addStretch()
        clear_log_btn = PushButton('清空日志')
        clear_log_btn.setFixedHeight(22)
        clear_log_btn.setStyleSheet('font-size: 11px;')
        clear_log_btn.clicked.connect(self._on_clear_log)
        log_header.addWidget(clear_log_btn)
        root.addLayout(log_header)
        self._log_box = QPlainTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setMaximumHeight(120)
        self._log_box.setPlaceholderText('操作日志将在这里显示，方便排查问题…')
        log_font = QFont('Consolas', 9)
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self._log_box.setFont(log_font)
        self._log_box.setStyleSheet(
            'background: #1e1e1e; color: #d4d4d4; border: 1px solid #444; border-radius: 4px;'
        )
        root.addWidget(self._log_box)

    # ──────────── Tab 构建 ─────────────────────────────────────────────────
    def _setup_tab_chat(self):
        """构建聊天消息 Tab"""
        layout = QVBoxLayout(self._tab_chat)
        hint = QLabel('来源：CDP Runtime.evaluate（实时页面 DOM）')
        hint.setStyleSheet('color: #888; font-size: 11px; padding: 2px 0;')
        layout.addWidget(hint)
        self._tbl_chat = _make_table(['序号', '内容（前500字）', 'HTML（前200字）'])
        layout.addWidget(self._tbl_chat)
        self._chat_hint = QLabel('点击左侧「一键检测并扫描」获取聊天消息')
        self._chat_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._chat_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._chat_hint)

    def _setup_tab_cookies(self):
        """构建 Cookies Tab"""
        layout = QVBoxLayout(self._tab_cookies)
        top_row = QHBoxLayout()
        hint = QLabel('来源：CDP Network.getAllCookies（明文，无需解密）')
        hint.setStyleSheet('color: #888; font-size: 11px;')
        top_row.addWidget(hint)
        top_row.addStretch()
        self._cookies_count_lbl = QLabel('共 0 条')
        self._cookies_count_lbl.setStyleSheet('color: #555; font-size: 12px;')
        top_row.addWidget(self._cookies_count_lbl)
        layout.addLayout(top_row)
        self._tbl_cookies = _make_table(['序号', 'Domain', 'Name', 'Value（前80字）', 'Path', 'HttpOnly', 'Secure'])
        layout.addWidget(self._tbl_cookies)

    def _setup_tab_ls(self):
        """构建 LocalStorage Tab"""
        layout = QVBoxLayout(self._tab_ls)
        hint = QLabel('来源：CDP Runtime.evaluate（localStorage + sessionStorage）')
        hint.setStyleSheet('color: #888; font-size: 11px; padding: 2px 0;')
        layout.addWidget(hint)
        self._tbl_ls = _make_table(['序号', '存储类型', 'Key', 'Value（前100字）'])
        layout.addWidget(self._tbl_ls)

    def _setup_tab_text(self):
        """构建页面文本 Tab"""
        layout = QVBoxLayout(self._tab_text)
        hint = QLabel('来源：CDP Runtime.evaluate（document.body.innerText，前8000字）')
        hint.setStyleSheet('color: #888; font-size: 11px; padding: 2px 0;')
        layout.addWidget(hint)
        self._page_text_edit = QPlainTextEdit()
        self._page_text_edit.setReadOnly(True)
        font = QFont('Consolas', 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._page_text_edit.setFont(font)
        layout.addWidget(self._page_text_edit)

    def _setup_tab_net(self):
        """构建网络请求 Tab"""
        layout = QVBoxLayout(self._tab_net)
        top_row = QHBoxLayout()
        self._net_count_lbl = QLabel('已捕获: 0 条')
        self._net_count_lbl.setStyleSheet('font-size: 12px; color: #555;')
        top_row.addWidget(self._net_count_lbl)
        top_row.addStretch()
        self._net_toggle_btn = PushButton('▶ 开始实时监听')
        self._net_toggle_btn.setFixedHeight(28)
        self._net_toggle_btn.clicked.connect(self._on_net_toggle)
        top_row.addWidget(self._net_toggle_btn)
        clear_btn = PushButton('🗑 清空')
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._on_net_clear)
        top_row.addWidget(clear_btn)
        layout.addLayout(top_row)
        self._tbl_net = _make_table(['序号', '时间', '事件类型', '请求ID', '内容（前200字）'])
        layout.addWidget(self._tbl_net)

    # ──────────── 信号连接 ─────────────────────────────────────────────────
    def _connect_watcher_signals(self):
        """连接进程监控信号，自动更新进程下拉框"""
        if not self._watcher:
            return
        try:
            self._watcher.process_found.connect(self._on_process_found)
            self._watcher.process_lost.connect(self._on_process_lost)
        except Exception:
            pass

    # ──────────── 日志面板 ─────────────────────────────────────────────────
    def _log(self, msg: str, level: str = 'info'):
        """向底部日志面板追加一行日志（level: info / warn / error / ok）"""
        try:
            ts = datetime.now().strftime('%H:%M:%S')
            icons = {'info': 'ℹ', 'warn': '⚠', 'error': '✗', 'ok': '✔'}
            icon = icons.get(level, 'ℹ')
            self._log_box.appendPlainText(f'[{ts}] {icon} {msg}')
            self._log_box.verticalScrollBar().setValue(
                self._log_box.verticalScrollBar().maximum()
            )
        except Exception:
            pass

    def _on_clear_log(self):
        """清空日志面板"""
        try:
            self._log_box.clear()
        except Exception:
            pass

    # ──────────── 进程下拉框管理 ───────────────────────────────────────────
    def _make_combo_text(self, sp) -> str:
        """生成下拉框显示文本"""
        port_str = f' [CDP:{sp.debug_port}]' if getattr(sp, 'debug_port', 0) else ''
        return f'{sp.platform_name} | {sp.name} (PID:{sp.pid}){port_str}'

    def _on_process_found(self, sp):
        """检测到新进程时更新下拉框"""
        try:
            text = self._make_combo_text(sp)
            for i in range(self._proc_combo.count()):
                if self._proc_combo.itemData(i) == sp.pid:
                    return
            self._proc_combo.addItem(text, userData=sp.pid)
            if getattr(sp, 'debug_port', 0):
                self._port_input.setText(str(sp.debug_port))
                self._log(f'检测到进程 {sp.name} (PID:{sp.pid})，调试端口: {sp.debug_port}', 'ok')
            else:
                self._log(
                    f'检测到进程 {sp.name} (PID:{sp.pid})，暂无调试端口'
                    '（点击「一键检测并扫描」可自动处理）', 'info'
                )
        except Exception:
            pass

    def _on_process_lost(self, pid: int):
        """进程消失时从下拉框移除"""
        try:
            for i in range(self._proc_combo.count()):
                if self._proc_combo.itemData(i) == pid:
                    self._proc_combo.removeItem(i)
                    break
        except Exception:
            pass

    def _on_proc_changed(self, index: int):
        """
        切换进程时的处理：
        - 如果进程有调试端口，自动填入端口号并记录日志
        - 如果进程没有调试端口（debug_port == 0），延迟弹出提示对话框
        """
        try:
            if not self._watcher or index < 0:
                return
            pid = self._proc_combo.itemData(index)
            if not pid:
                return
            procs = self._watcher.get_all()
            for sp in procs:
                if sp.pid == pid:
                    if getattr(sp, 'debug_port', 0):
                        # 有调试端口：自动填入，可直接点击扫描
                        self._port_input.setText(str(sp.debug_port))
                        self._log(
                            f'已选择 {sp.name}，调试端口 {sp.debug_port} 已自动填入，'
                            '可直接点击「一键检测并扫描」', 'ok'
                        )
                    else:
                        # 无调试端口：保存进程信息，延迟弹出提示（避免在信号中直接弹窗）
                        self._pending_no_debug_sp = sp
                        self._log(
                            f'已选择 {sp.name} (PID:{sp.pid})，该进程尚未开启调试模式，'
                            '点击「一键检测并扫描」将提示自动重启', 'warn'
                        )
                        QTimer.singleShot(_DIALOG_DELAY_MS, self._show_no_debug_port_dialog)
                    break
        except Exception:
            pass

    def update_processes(self, processes: list):
        """外部调用：刷新进程下拉框（传入 ShopProcess 列表）"""
        try:
            self._proc_combo.clear()
            for sp in processes:
                text = self._make_combo_text(sp)
                self._proc_combo.addItem(text, userData=sp.pid)
                if getattr(sp, 'debug_port', 0):
                    self._port_input.setText(str(sp.debug_port))
        except Exception:
            pass

    # ──────────── 连接并扫描 ───────────────────────────────────────────────
    def _get_debug_port(self) -> int:
        """从手动输入框或进程下拉框获取调试端口，失败返回 0"""
        txt = self._port_input.text().strip()
        if txt.isdigit():
            return int(txt)
        try:
            if self._watcher:
                idx = self._proc_combo.currentIndex()
                pid = self._proc_combo.itemData(idx)
                if pid:
                    for sp in self._watcher.get_all():
                        if sp.pid == pid and getattr(sp, 'debug_port', 0):
                            return sp.debug_port
        except Exception:
            pass
        return 0

    def _on_connect(self):
        """点击「手动连接」：使用输入框中的端口直接启动 CDP 扫描（高级选项）"""
        port = self._get_debug_port()
        if not port:
            InfoBar.warning(
                title='未指定调试端口',
                content='请先在输入框中手动填写调试端口号（如 9222），或使用「一键检测并扫描」',
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._log(f'[手动连接] 准备连接端口 {port}…')
        self._do_connect_scan(port)


    # ──────────── 一键检测并扫描 ──────────────────────────────────────────
    def _on_one_click_detect(self):
        """
        一键检测并扫描的完整流程：
        1. 检查当前选中进程是否已开启调试端口
        2. 若未开启：弹出对话框询问是否重启并启用调试模式
        3. 若已开启（或端口已手动填写）：直接连接 CDP 采集数据
        """
        try:
            idx = self._proc_combo.currentIndex()
            if self._watcher and idx >= 0:
                pid = self._proc_combo.itemData(idx)
                if pid:
                    for sp in self._watcher.get_all():
                        if sp.pid == pid:
                            if getattr(sp, 'debug_port', 0):
                                # 进程已有调试端口，自动填入并开始扫描
                                self._port_input.setText(str(sp.debug_port))
                                self._do_connect_scan(sp.debug_port)
                            else:
                                # 进程未开启调试端口，弹出提示让用户决策
                                self._pending_no_debug_sp = sp
                                self._show_no_debug_port_dialog()
                            return
        except Exception:
            pass
        # 没有匹配进程时，尝试使用输入框中的端口
        port = self._get_debug_port()
        if port:
            self._do_connect_scan(port)
        else:
            InfoBar.warning(
                title='未选择进程',
                content='请先从上方下拉框选择一个客服软件进程，再点击「一键检测并扫描」',
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _do_connect_scan(self, port: int):
        """实际执行 CDP 连接和扫描的内部方法（先验证端口可用性）"""
        self._connect_btn.setEnabled(False)
        self._one_click_btn.setEnabled(False)
        self._log(f'正在检测调试端口 {port} 可用性…')
        self._status_lbl.setText(f'正在验证端口 {port}…')

        # 先做一次快速端口检测，给用户即时反馈
        check = cdp_reader.check_debug_port(port)
        if not check['ok']:
            self._connect_btn.setEnabled(True)
            self._one_click_btn.setEnabled(True)
            self._status_lbl.setText('端口不可用，请查看日志')
            self._log(f'端口 {port} 检测失败: {check["error"]}', 'error')
            if check.get('suggestion'):
                self._log(f'建议: {check["suggestion"]}', 'warn')
            InfoBar.error(
                title='无法连接',
                content=check['error'],
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        self._log(
            f'端口 {port} 可用，发现 {len(check["pages"])} 个页面，开始扫描…', 'ok'
        )
        self._status_lbl.setText(f'正在连接端口 {port}，扫描所有页面…')
        self._refresh_page_list(port)
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.quit()
        self._scan_worker = _CdpScanWorker(port)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    # ──────────── 调试端口提示与重启 ──────────────────────────────────────
    def _show_no_debug_port_dialog(self):
        """
        当选中的进程未开启调试模式时弹出提示对话框。
        提供「重启并启用调试」和「取消」两个选项，尽量简单直观。
        """
        sp = self._pending_no_debug_sp
        self._pending_no_debug_sp = None
        if not sp:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle('未开启调试模式')
        msg.setText(
            f'所选进程「{sp.name}」未处于调试模式，无法直接采集数据。\n\n'
            '是否重启该进程并启用调试模式？'
        )
        msg.setInformativeText(
            '系统将自动添加参数 --remote-debugging-port=9222 并重新启动该进程。\n'
            '重启后请等待软件完全加载，再点击「一键检测并扫描」。'
        )
        msg.setIcon(QMessageBox.Icon.Information)
        # 创建具有明确说明的按钮
        restart_btn = msg.addButton('重启并启用调试', QMessageBox.ButtonRole.AcceptRole)
        msg.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        if msg.clickedButton() == restart_btn:
            self._do_restart_with_debug_port(sp)

    def _do_restart_with_debug_port(self, sp):
        """
        启动后台线程重启进程并附加调试端口参数（默认端口 9222）。
        重启过程不阻塞 UI。
        """
        if self._restart_worker and self._restart_worker.isRunning():
            return  # 已在重启中，防止重复触发

        self._connect_btn.setEnabled(False)
        self._one_click_btn.setEnabled(False)
        self._status_lbl.setText(f'正在重启进程 {sp.name}，请稍候...')

        self._restart_debug_port = 9222
        self._restart_worker = _RestartWorker(sp.pid, port=self._restart_debug_port)
        self._restart_worker.finished.connect(self._on_restart_finished)
        self._restart_worker.start()

    def _on_restart_finished(self, success: bool, msg: str):
        """进程重启完成后的回调：更新 UI 状态并提示用户"""
        debug_port = getattr(self, '_restart_debug_port', 9222)
        self._connect_btn.setEnabled(True)
        self._one_click_btn.setEnabled(True)
        if success:
            # 重启成功：预填调试端口，提示用户稍等后再扫描
            self._port_input.setText(str(debug_port))
            self._status_lbl.setText(msg)
            self._log(msg, 'ok')
            self._log('请等待软件完全加载后，再点击「一键检测并扫描」', 'info')
            InfoBar.success(
                title='重启成功',
                content=msg,
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            self._status_lbl.setText('重启失败，请查看日志')
            self._log(f'重启失败: {msg}', 'error')
            self._log(
                f'建议：请手动关闭软件，然后以管理员身份在命令行添加'
                f' --remote-debugging-port={debug_port} 参数重新启动', 'warn'
            )
            InfoBar.error(
                title='重启失败',
                content=msg,
                duration=5000,
                position=InfoBarPosition.TOP,
                parent=self,
            )


    def _refresh_page_list(self, port: int):
        """刷新左侧页面列表"""
        self._page_list.clear()
        try:
            self._pages = cdp_reader.get_pages(port)
            for p in self._pages:
                title = p.get('title') or p.get('url', '（无标题）')
                item = QListWidgetItem(f'📄 {title[:60]}')
                item.setToolTip(p.get('url', ''))
                self._page_list.addItem(item)
        except Exception:
            self._pages = []

    def _on_page_selected(self, row: int):
        """左侧选中某个页面时，显示该页面对应的数据"""
        try:
            if row < 0 or not self._last_data.get('pages'):
                return
            pages = self._last_data['pages']
            if row < len(pages):
                self._populate_tabs(pages[row].get('data', {}))
        except Exception:
            pass

    # ──────────── 扫描结果回调 ─────────────────────────────────────────────
    def _on_scan_finished(self, data: dict):
        """CDP 扫描完成：填充所有 Tab，并重新启用按钮"""
        self._connect_btn.setEnabled(True)
        self._one_click_btn.setEnabled(True)
        self._last_data = data
        if data.get('error'):
            err_msg = data['error']
            suggestion = data.get('suggestion', '')
            self._status_lbl.setText(f'扫描失败: {err_msg}')
            self._log(f'扫描失败: {err_msg}', 'error')
            if suggestion:
                self._log(f'建议: {suggestion}', 'warn')
            InfoBar.error(
                title='扫描失败',
                content=err_msg,
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        pages = data.get('pages', [])
        total_ck = data.get('total_cookies', 0)
        scan_time = data.get('scan_time', '')
        self._status_lbl.setText(
            f'扫描完成 | 页面: {len(pages)} | 总Cookie: {total_ck} | {scan_time}'
        )
        self._log(
            f'扫描完成：共 {len(pages)} 个页面，{total_ck} 条 Cookie，耗时见右上角时间', 'ok'
        )
        for i, pg in enumerate(pages):
            title = pg.get('title', '') or pg.get('url', '')
            pg_data = pg.get('data', {})
            chat_cnt = len(pg_data.get('chat_messages', []))
            ck_cnt = len(pg_data.get('cookies', []))
            self._log(
                f'  页面[{i+1}] {title[:50]} — 聊天:{chat_cnt} 条, Cookie:{ck_cnt} 条'
            )
        if pages:
            self._page_list.setCurrentRow(0)
            self._populate_tabs(pages[0].get('data', {}))
        InfoBar.success(
            title='扫描完成',
            content=f'共扫描 {len(pages)} 个页面，获取 {total_ck} 条 Cookie',
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_scan_error(self, msg: str):
        """扫描出错：重新启用按钮并显示错误提示"""
        self._connect_btn.setEnabled(True)
        self._one_click_btn.setEnabled(True)
        self._status_lbl.setText(f'错误: {msg}')
        self._log(f'扫描线程异常: {msg}', 'error')
        InfoBar.error(
            title='扫描出错',
            content=msg,
            duration=5000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _populate_tabs(self, page_data: dict):
        """用指定页面的数据填充所有 Tab"""
        try:
            self._fill_chat_tab(page_data.get('chat_messages', []))
            self._fill_cookies_tab(page_data.get('cookies', []))
            self._fill_ls_tab(page_data.get('local_storage', {}))
            self._fill_text_tab(page_data.get('page_text', ''))
        except Exception:
            pass

    # ──────────── Tab 填充 ─────────────────────────────────────────────────
    def _fill_chat_tab(self, messages: list):
        """填充聊天消息 Tab"""
        tbl = self._tbl_chat
        tbl.setRowCount(0)
        if not messages:
            self._chat_hint.setVisible(True)
            return
        self._chat_hint.setVisible(False)
        for msg in messages:
            row = tbl.rowCount()
            tbl.insertRow(row)
            tbl.setItem(row, 0, _item(str(msg.get('index', row))))
            tbl.setItem(row, 1, _item(str(msg.get('content', ''))[:500]))
            tbl.setItem(row, 2, _item(str(msg.get('raw_html', ''))[:200]))

    def _fill_cookies_tab(self, cookies: list):
        """填充 Cookies Tab"""
        tbl = self._tbl_cookies
        tbl.setRowCount(0)
        self._cookies_count_lbl.setText(f'共 {len(cookies)} 条')
        for ck in cookies:
            row = tbl.rowCount()
            tbl.insertRow(row)
            tbl.setItem(row, 0, _item(str(row + 1)))
            tbl.setItem(row, 1, _item(ck.get('domain', '')))
            tbl.setItem(row, 2, _item(ck.get('name', '')))
            tbl.setItem(row, 3, _item(str(ck.get('value', ''))[:80]))
            tbl.setItem(row, 4, _item(ck.get('path', '/')))
            tbl.setItem(row, 5, _item('✓' if ck.get('httpOnly') else '', color='#0078d4' if ck.get('httpOnly') else None))
            tbl.setItem(row, 6, _item('✓' if ck.get('secure') else '', color='#00a550' if ck.get('secure') else None))

    def _fill_ls_tab(self, storage: dict):
        """填充 LocalStorage Tab"""
        tbl = self._tbl_ls
        tbl.setRowCount(0)
        row_idx = 0
        for store_type, items in storage.items():
            if not isinstance(items, dict):
                continue
            for k, v in items.items():
                tbl.insertRow(row_idx)
                tbl.setItem(row_idx, 0, _item(str(row_idx + 1)))
                tbl.setItem(row_idx, 1, _item(store_type, color='#0078d4'))
                tbl.setItem(row_idx, 2, _item(str(k)))
                tbl.setItem(row_idx, 3, _item(str(v)[:100]))
                row_idx += 1

    def _fill_text_tab(self, text: str):
        """填充页面文本 Tab"""
        self._page_text_edit.setPlainText(text or '')

    # ──────────── 网络监听 ─────────────────────────────────────────────────
    def _on_net_toggle(self):
        """切换网络实时监听的开启/停止状态"""
        if self._net_monitoring:
            self._stop_net_monitor()
        else:
            self._start_net_monitor()

    def _start_net_monitor(self):
        """启动网络实时监听"""
        port = self._get_debug_port()
        if not port:
            InfoBar.warning(
                title='未指定调试端口',
                content='请先连接一个 CDP 调试端口',
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        ws_url = ''
        try:
            pages = cdp_reader.get_pages(port)
            if pages:
                ws_url = pages[0].get('webSocketDebuggerUrl', '')
        except Exception:
            pass
        if not ws_url:
            InfoBar.error(
                title='无可用页面',
                content=f'端口 {port} 上未找到可连接的页面',
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._net_monitoring = True
        self._net_toggle_btn.setText('⏹ 停止监听')
        if self._net_worker and self._net_worker.isRunning():
            self._net_worker.stop()
        self._net_worker = _NetworkWorker(port, ws_url)
        self._net_worker.network_event.connect(self._on_network_event)
        self._net_worker.start()
        InfoBar.info(
            title='网络监听已启动',
            content='正在实时捕获网络请求，请在客服软件中操作',
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _stop_net_monitor(self):
        """停止网络实时监听"""
        self._net_monitoring = False
        self._net_toggle_btn.setText('▶ 开始实时监听')
        if self._net_worker:
            self._net_worker.stop()
            self._net_worker = None

    def _on_network_event(self, event: dict):
        """收到网络事件：追加到网络请求表格"""
        try:
            tbl = self._tbl_net
            row = tbl.rowCount()
            tbl.insertRow(row)
            now = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            method = event.get('method', '')
            params = event.get('params', {})
            req_id = params.get('requestId', params.get('frameId', ''))
            content = ''
            for key in ('url', 'response', 'message', 'errorText'):
                val = params.get(key)
                if val:
                    content = str(val)[:200]
                    break
            tbl.setItem(row, 0, _item(str(row + 1)))
            tbl.setItem(row, 1, _item(now))
            tbl.setItem(row, 2, _item(method, color='#0078d4'))
            tbl.setItem(row, 3, _item(str(req_id)))
            tbl.setItem(row, 4, _item(content))
            self._net_count_lbl.setText(f'已捕获: {row + 1} 条')
            tbl.scrollToBottom()
        except Exception:
            pass

    def _on_net_clear(self):
        """清空网络请求表格"""
        self._tbl_net.setRowCount(0)
        self._net_count_lbl.setText('已捕获: 0 条')

    # ──────────── 复制全部数据 ─────────────────────────────────────────────
    def _on_copy_all(self):
        """将上次扫描的全部数据复制为 JSON 到剪贴板"""
        try:
            text = json.dumps(self._last_data, ensure_ascii=False, indent=2)
            QApplication.clipboard().setText(text)
            InfoBar.success(
                title='已复制',
                content='全部 CDP 扫描数据已复制到剪贴板（JSON 格式）',
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                title='复制失败',
                content=str(e),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
