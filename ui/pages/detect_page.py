# -*- coding: utf-8 -*-
"""
数据检测页面（全新可视化页面）
对检测到的客服软件进程进行全面数据扫描，分区展示：
聊天消息、订单/商品、Cookies、IndexedDB、本地存储、网络连接、数据目录&文件
"""

import json
import csv
import io
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QDialogButtonBox,
    QPlainTextEdit, QListWidget, QListWidgetItem,
    QApplication, QSplitter, QFrame, QScrollArea,
    QTabWidget, QFileDialog
)
from qfluentwidgets import (
    SubtitleLabel, CaptionLabel,
    PushButton, PrimaryPushButton,
    InfoBar, InfoBarPosition,
    ComboBox,
)

from core.process_watcher import ProcessWatcher


# ─────────────────────── 后台检测线程 ──────────────────────────────────────
class _DetectWorker(QThread):
    """后台数据检测线程，不阻塞 UI 主线程"""
    finished = pyqtSignal(dict)   # 检测成功，传回结果 dict
    error = pyqtSignal(str)       # 检测失败，传回错误信息

    def __init__(self, watcher: ProcessWatcher, pid: int):
        super().__init__()
        self._watcher = watcher
        self._pid = pid

    def run(self):
        """在后台线程中执行深度扫描"""
        try:
            result = self._watcher.get_process_detail(self._pid)
            if isinstance(result, dict) and 'error' in result:
                self.error.emit(result['error'])
            else:
                self.finished.emit(result if isinstance(result, dict) else {})
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────── 内容详情弹窗 ──────────────────────────────────────
class _ContentDialog(QDialog):
    """点击表格行时弹出的内容详情对话框，展示格式化 JSON"""

    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        # 格式化 JSON 内容显示
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        font = QFont('Consolas', 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        txt.setFont(font)
        txt.setPlainText(content)
        layout.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


# ─────────────────────── 工具函数 ──────────────────────────────────────────
def _make_table(columns: list) -> QTableWidget:
    """
    创建统一风格的只读表格。
    交替行颜色、禁止编辑、列宽自适应，最后一列拉伸。

    参数:
        columns (list): 列标题列表
    返回:
        QTableWidget
    """
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
    """
    创建一个只读的表格单元格。

    参数:
        text (str): 单元格文本
        color (str): 可选，前景色（如 '#e74c3c'）
    返回:
        QTableWidgetItem
    """
    it = QTableWidgetItem(str(text))
    it.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if color:
        it.setForeground(QColor(color))
    return it


def _section_label(text: str) -> QLabel:
    """创建分区标题标签"""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        'font-size: 12px; font-weight: bold; color: #555; '
        'border-bottom: 1px solid #eee; padding-bottom: 2px; margin-top: 6px;'
    )
    return lbl


# ─────────────────────── 检测页面主体 ──────────────────────────────────────
class DetectPage(QWidget):
    """
    全面数据检测页面。
    分区展示：基本信息 / 聊天消息 / 订单商品 / Cookies / IndexedDB / 本地存储
             / 网络连接 / 数据目录&文件
    """

    def __init__(self, watcher: ProcessWatcher = None, parent=None):
        super().__init__(parent)
        self._watcher = watcher
        self._worker: _DetectWorker = None
        self._last_result: dict = {}       # 上次检测结果缓存
        self.setObjectName('detectPage')
        self._setup_ui()
        self._connect_signals()

    # ──────────────────────── UI 构建 ──────────────────────────────────────
    def _setup_ui(self):
        """构建页面整体布局"""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── 顶部工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        title_lbl = SubtitleLabel('🔎 全面数据检测')
        toolbar.addWidget(title_lbl)
        toolbar.addStretch()

        # 进程选择下拉框
        proc_lbl = QLabel('选择进程:')
        proc_lbl.setStyleSheet('font-size: 13px; color: #555;')
        toolbar.addWidget(proc_lbl)
        self._proc_combo = ComboBox()
        self._proc_combo.setMinimumWidth(260)
        self._proc_combo.setPlaceholderText('未检测到进程...')
        toolbar.addWidget(self._proc_combo)

        # 开始检测按钮
        self._start_btn = PrimaryPushButton('▶ 开始检测')
        self._start_btn.setFixedHeight(34)
        self._start_btn.clicked.connect(self._on_start_detect)
        toolbar.addWidget(self._start_btn)

        # 状态标签
        self._status_lbl = CaptionLabel('请选择进程后点击「开始检测」')
        self._status_lbl.setStyleSheet('color: #888;')
        toolbar.addWidget(self._status_lbl)

        root.addLayout(toolbar)

        # ── 主体 Tab 区域 ──
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Tab1: 基本信息
        self._tab_basic = QWidget()
        self._setup_tab_basic()
        self._tabs.addTab(self._tab_basic, '📋 基本信息')

        # Tab2: 聊天消息
        self._tab_chat = QWidget()
        self._setup_tab_chat()
        self._tabs.addTab(self._tab_chat, '💬 聊天消息')

        # Tab3: 订单/商品
        self._tab_order = QWidget()
        self._setup_tab_order()
        self._tabs.addTab(self._tab_order, '📦 订单/商品')

        # Tab4: Cookies
        self._tab_cookies = QWidget()
        self._setup_tab_cookies()
        self._tabs.addTab(self._tab_cookies, '🍪 Cookies')

        # Tab5: IndexedDB
        self._tab_idb = QWidget()
        self._setup_tab_idb()
        self._tabs.addTab(self._tab_idb, '🗄️ IndexedDB')

        # Tab6: 本地存储
        self._tab_ls = QWidget()
        self._setup_tab_ls()
        self._tabs.addTab(self._tab_ls, '📁 本地存储')

        # Tab7: 网络连接
        self._tab_net = QWidget()
        self._setup_tab_net()
        self._tabs.addTab(self._tab_net, '🌐 网络连接')

        # Tab8: 数据目录&文件
        self._tab_dirs = QWidget()
        self._setup_tab_dirs()
        self._tabs.addTab(self._tab_dirs, '📂 数据目录&文件')

        root.addWidget(self._tabs, 1)

    # ──────────────── Tab1 基本信息 ────────────────────────────────────────
    def _setup_tab_basic(self):
        """构建基本信息 Tab"""
        layout = QVBoxLayout(self._tab_basic)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self._basic_layout = QVBoxLayout(inner)
        self._basic_layout.setContentsMargins(0, 0, 0, 0)
        self._basic_layout.setSpacing(4)
        self._basic_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # 初始占位
        self._basic_hint = QLabel('请先点击「开始检测」')
        self._basic_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 30px;')
        self._basic_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._basic_layout.addWidget(self._basic_hint)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

    # ──────────────── Tab2 聊天消息 ────────────────────────────────────────
    def _setup_tab_chat(self):
        """构建聊天消息 Tab"""
        layout = QVBoxLayout(self._tab_chat)
        src_lbl = QLabel('来源: Msg.db / chat.db（本地缓存数据）')
        src_lbl.setStyleSheet('color: #888; font-size: 11px; padding: 2px 0;')
        layout.addWidget(src_lbl)
        self._tbl_chat = _make_table(['序号', '数据库文件', '表名', '原始内容 (JSON)'])
        self._tbl_chat.cellDoubleClicked.connect(self._on_chat_row_dblclick)
        layout.addWidget(self._tbl_chat)
        self._chat_hint = QLabel('暂未检测到聊天数据，请先点击「开始检测」')
        self._chat_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._chat_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._chat_hint)

    # ──────────────── Tab3 订单/商品 ───────────────────────────────────────
    def _setup_tab_order(self):
        """构建订单/商品 Tab"""
        layout = QVBoxLayout(self._tab_order)
        src_lbl = QLabel('来源: Info2.db / search.db（本地缓存数据）')
        src_lbl.setStyleSheet('color: #888; font-size: 11px; padding: 2px 0;')
        layout.addWidget(src_lbl)
        self._tbl_order = _make_table(['序号', '数据库文件', '表名', '原始内容 (JSON)'])
        self._tbl_order.cellDoubleClicked.connect(self._on_order_row_dblclick)
        layout.addWidget(self._tbl_order)
        self._order_hint = QLabel('暂未检测到订单/商品数据，请先点击「开始检测」')
        self._order_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._order_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._order_hint)

    # ──────────────── Tab4 Cookies ─────────────────────────────────────────
    def _setup_tab_cookies(self):
        """构建 Cookies Tab"""
        layout = QVBoxLayout(self._tab_cookies)
        # 顶部栏：说明 + 统计 + 导出按钮
        top_row = QHBoxLayout()
        src_lbl = QLabel('来源: Cookies 文件（Chromium SQLite 格式）')
        src_lbl.setStyleSheet('color: #888; font-size: 11px;')
        top_row.addWidget(src_lbl)
        top_row.addStretch()
        self._cookies_count_lbl = QLabel('共 0 条 Cookies')
        self._cookies_count_lbl.setStyleSheet('color: #555; font-size: 12px;')
        top_row.addWidget(self._cookies_count_lbl)
        self._export_cookies_btn = PushButton('📤 导出 CSV')
        self._export_cookies_btn.setFixedHeight(28)
        self._export_cookies_btn.clicked.connect(self._on_export_cookies)
        top_row.addWidget(self._export_cookies_btn)
        layout.addLayout(top_row)
        self._tbl_cookies = _make_table(['序号', 'Host', 'Name', 'Value (前50字)', 'Path', '过期时间'])
        layout.addWidget(self._tbl_cookies)
        self._cookies_hint = QLabel('暂未检测到 Cookies，请先点击「开始检测」')
        self._cookies_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._cookies_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._cookies_hint)

    # ──────────────── Tab5 IndexedDB ───────────────────────────────────────
    def _setup_tab_idb(self):
        """构建 IndexedDB Tab"""
        layout = QVBoxLayout(self._tab_idb)
        # 统计卡片行
        stat_row = QHBoxLayout()
        self._idb_file_count_lbl = QLabel('总文件数: 0')
        self._idb_file_count_lbl.setStyleSheet(
            'font-size: 14px; font-weight: bold; color: #0078d4; '
            'background: #e8f0fe; border-radius: 6px; padding: 8px 16px;'
        )
        self._idb_size_lbl = QLabel('总大小: 0 KB')
        self._idb_size_lbl.setStyleSheet(
            'font-size: 14px; font-weight: bold; color: #00a550; '
            'background: #e6f9ee; border-radius: 6px; padding: 8px 16px;'
        )
        stat_row.addWidget(self._idb_file_count_lbl)
        stat_row.addWidget(self._idb_size_lbl)
        stat_row.addStretch()
        layout.addLayout(stat_row)
        self._tbl_idb = _make_table(['序号', '文件路径', '大小 (KB)'])
        layout.addWidget(self._tbl_idb)
        self._idb_hint = QLabel('暂未检测到 IndexedDB 文件，请先点击「开始检测」')
        self._idb_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._idb_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._idb_hint)

    # ──────────────── Tab6 本地存储 ────────────────────────────────────────
    def _setup_tab_ls(self):
        """构建本地存储 Tab"""
        layout = QVBoxLayout(self._tab_ls)
        src_lbl = QLabel('来源: Local Storage 目录（.localstorage 文件）')
        src_lbl.setStyleSheet('color: #888; font-size: 11px; padding: 2px 0;')
        layout.addWidget(src_lbl)
        self._tbl_ls = _make_table(['序号', 'Origin', 'Key', 'Value (前80字)'])
        layout.addWidget(self._tbl_ls)
        self._ls_hint = QLabel('暂未检测到本地存储数据，请先点击「开始检测」')
        self._ls_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._ls_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._ls_hint)

    # ──────────────── Tab7 网络连接 ────────────────────────────────────────
    def _setup_tab_net(self):
        """构建网络连接 Tab"""
        layout = QVBoxLayout(self._tab_net)
        # 统计行
        self._net_stat_lbl = QLabel('TCP 连接数: 0   WS候选: 0')
        self._net_stat_lbl.setStyleSheet('font-size: 12px; color: #555; padding: 2px 0;')
        layout.addWidget(self._net_stat_lbl)
        self._tbl_net = _make_table(['序号', '本地地址:端口', '远程地址:端口', '状态', '类型'])
        layout.addWidget(self._tbl_net)
        self._net_hint = QLabel('暂未检测到网络连接，请先点击「开始检测」')
        self._net_hint.setStyleSheet('color: #aaa; font-size: 13px; padding: 20px;')
        self._net_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._net_hint)

    # ──────────────── Tab8 数据目录&文件 ───────────────────────────────────
    def _setup_tab_dirs(self):
        """构建数据目录&文件 Tab"""
        layout = QVBoxLayout(self._tab_dirs)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 上半：数据目录列表
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(_section_label('数据目录'))
        self._dirs_list = QListWidget()
        self._dirs_list.setAlternatingRowColors(True)
        top_layout.addWidget(self._dirs_list)
        splitter.addWidget(top_widget)

        # 下半：检测到的相关文件
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(0, 0, 0, 0)
        bot_layout.addWidget(_section_label('相关文件（按类型着色）'))
        self._files_list = QListWidget()
        self._files_list.setAlternatingRowColors(True)
        bot_layout.addWidget(self._files_list)
        splitter.addWidget(bot_widget)

        splitter.setSizes([200, 300])
        layout.addWidget(splitter)

    # ──────────────── 信号连接 ─────────────────────────────────────────────
    def _connect_signals(self):
        """连接 watcher 信号以自动更新进程下拉框"""
        if not self._watcher:
            return
        try:
            self._watcher.process_found.connect(self._on_process_found)
            self._watcher.process_lost.connect(self._on_process_lost)
        except Exception:
            pass

    # ──────────────── 进程下拉框管理 ───────────────────────────────────────
    def _make_combo_text(self, sp) -> str:
        """生成下拉框选项文字"""
        platform_name = getattr(sp, 'platform_name', '未知')
        name = getattr(sp, 'name', '')
        pid = getattr(sp, 'pid', 0)
        return f'{platform_name} · {name} (PID:{pid})'

    def _on_process_found(self, sp):
        """新进程检测到，添加到下拉框"""
        try:
            text = self._make_combo_text(sp)
            # 检查是否已存在（防止重复）
            for i in range(self._proc_combo.count()):
                if self._proc_combo.itemText(i) == text:
                    return
            self._proc_combo.addItem(text, userData=getattr(sp, 'pid', 0))
        except Exception:
            pass

    def _on_process_lost(self, pid: int):
        """进程消失，从下拉框移除"""
        try:
            for i in range(self._proc_combo.count()):
                if self._proc_combo.itemData(i) == pid:
                    self._proc_combo.removeItem(i)
                    break
        except Exception:
            pass

    def _get_selected_pid(self) -> int:
        """获取当前选中进程的 PID，未选中返回 -1"""
        try:
            idx = self._proc_combo.currentIndex()
            if idx < 0:
                return -1
            pid = self._proc_combo.itemData(idx)
            return pid if pid is not None else -1
        except Exception:
            return -1

    # ──────────────── 开始检测 ─────────────────────────────────────────────
    def _on_start_detect(self):
        """点击「开始检测」按钮"""
        pid = self._get_selected_pid()
        if pid < 0 or not self._watcher:
            InfoBar.warning(
                title='未选择进程',
                content='请先在下拉框中选择要检测的进程',
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            self._status_lbl.setText('❌ 未选择进程')
            return

        # 防止重复启动
        if self._worker and self._worker.isRunning():
            InfoBar.warning(
                title='检测中',
                content='检测正在进行，请稍候...',
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        # 断开旧信号
        if self._worker is not None:
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except RuntimeError:
                pass
            self._worker = None

        # 禁用按钮，显示检测中状态
        self._start_btn.setEnabled(False)
        self._start_btn.setText('⏳ 检测中...')
        self._status_lbl.setText('🔄 正在深度检测，请稍候...')

        # 启动后台线程
        self._worker = _DetectWorker(self._watcher, pid)
        self._worker.finished.connect(self._on_detect_finished)
        self._worker.error.connect(self._on_detect_error)
        self._worker.start()

    def _on_detect_finished(self, result: dict):
        """检测完成，更新所有 Tab 内容"""
        self._start_btn.setEnabled(True)
        self._start_btn.setText('▶ 开始检测')
        now = datetime.now().strftime('%H:%M:%S')
        self._status_lbl.setText(f'✅ 检测完成 ({now})')
        self._last_result = result

        # 逐 Tab 更新数据
        try:
            self._update_tab_basic(result)
        except Exception:
            pass
        try:
            self._update_tab_chat(result)
        except Exception:
            pass
        try:
            self._update_tab_order(result)
        except Exception:
            pass
        try:
            self._update_tab_cookies(result)
        except Exception:
            pass
        try:
            self._update_tab_idb(result)
        except Exception:
            pass
        try:
            self._update_tab_ls(result)
        except Exception:
            pass
        try:
            self._update_tab_net(result)
        except Exception:
            pass
        try:
            self._update_tab_dirs(result)
        except Exception:
            pass

        InfoBar.success(
            title='检测完成',
            content='全部数据已更新，请查看各 Tab 页面',
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_detect_error(self, msg: str):
        """检测失败"""
        self._start_btn.setEnabled(True)
        self._start_btn.setText('▶ 开始检测')
        self._status_lbl.setText(f'❌ 检测失败: {msg}')
        InfoBar.error(
            title='检测失败',
            content=msg,
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    # ──────────────── Tab 数据更新方法 ─────────────────────────────────────
    def _update_tab_basic(self, result: dict):
        """更新基本信息 Tab"""
        # 清空旧内容
        while self._basic_layout.count():
            item = self._basic_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        create_time_str = result.get('create_time_str', '')
        status = result.get('status', '')
        debug_port = result.get('debug_port', 0)
        tokens_count = result.get('suspected_tokens_count', 0)
        env_keys = result.get('env_relevant_keys', []) or []
        window_titles = result.get('window_titles', []) or []
        children = result.get('children', []) or []

        def kv_row(key: str, val: str, val_color: str = '#333'):
            """创建 key-value 行布局"""
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 2, 0, 2)
            k_lbl = QLabel(key)
            k_lbl.setStyleSheet('font-size: 12px; color: #888; min-width: 120px;')
            k_lbl.setFixedWidth(130)
            v_lbl = QLabel(str(val))
            v_lbl.setStyleSheet(f'font-size: 12px; color: {val_color};')
            v_lbl.setWordWrap(True)
            row_l.addWidget(k_lbl)
            row_l.addWidget(v_lbl, 1)
            return row_w

        # 基本信息
        self._basic_layout.addWidget(_section_label('基本信息'))
        self._basic_layout.addWidget(kv_row('进程名', result.get('name', '')))
        self._basic_layout.addWidget(kv_row('PID', str(result.get('pid', ''))))
        self._basic_layout.addWidget(kv_row('平台', result.get('platform_name', ''), '#0078d4'))
        self._basic_layout.addWidget(kv_row('状态', status,
                                            '#00a550' if status == 'running' else '#e67e22'))
        self._basic_layout.addWidget(kv_row('路径', result.get('exe_path', '') or '未知'))
        self._basic_layout.addWidget(kv_row('内存', f"{result.get('memory_mb', 0.0):.1f} MB"))
        self._basic_layout.addWidget(kv_row('CPU', f"{result.get('cpu_percent', 0.0):.1f}%"))
        self._basic_layout.addWidget(kv_row('启动时间', create_time_str))

        # 店铺信息
        shop_name = result.get('shop_name', '')
        if shop_name or window_titles:
            self._basic_layout.addWidget(_section_label('店铺信息'))
            if shop_name:
                self._basic_layout.addWidget(kv_row('店铺名', shop_name, '#0078d4'))
            for t in window_titles:
                self._basic_layout.addWidget(kv_row('窗口标题', str(t)))

        # 命令行
        cmdline = result.get('cmdline_str', '')
        if cmdline:
            self._basic_layout.addWidget(_section_label('命令行'))
            cmd_box = QPlainTextEdit(cmdline)
            cmd_box.setReadOnly(True)
            cmd_box.setMaximumHeight(72)
            font = QFont('Consolas', 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            cmd_box.setFont(font)
            self._basic_layout.addWidget(cmd_box)

        # 调试端口
        if debug_port:
            self._basic_layout.addWidget(_section_label('调试端口'))
            dp_lbl = QLabel(f'⚠️ 检测到调试端口: {debug_port}')
            dp_lbl.setStyleSheet('color: #e74c3c; font-size: 13px; font-weight: bold; padding: 4px 0;')
            self._basic_layout.addWidget(dp_lbl)

        # 疑似 Token
        if tokens_count > 0:
            self._basic_layout.addWidget(_section_label('疑似 Token'))
            tk_lbl = QLabel(f'⚠️ 发现 {tokens_count} 个疑似 Token（来自命令行）')
            tk_lbl.setStyleSheet('color: #e67e22; font-size: 12px; padding: 4px 0;')
            self._basic_layout.addWidget(tk_lbl)

        # 子进程
        if children:
            self._basic_layout.addWidget(_section_label('子进程'))
            child_tbl = _make_table(['PID', '进程名'])
            for child in children:
                if isinstance(child, dict):
                    c_pid = str(child.get('pid', ''))
                    c_name = child.get('name', '')
                else:
                    c_pid = str(getattr(child, 'pid', ''))
                    c_name = getattr(child, 'name', '')
                r = child_tbl.rowCount()
                child_tbl.insertRow(r)
                child_tbl.setItem(r, 0, _item(c_pid))
                child_tbl.setItem(r, 1, _item(c_name))
            child_tbl.setMaximumHeight(min(len(children) * 28 + 32, 160))
            self._basic_layout.addWidget(child_tbl)

        # 环境变量
        if env_keys:
            self._basic_layout.addWidget(_section_label('环境变量（相关 key）'))
            env_lbl = QLabel('  ' + '   '.join(env_keys[:30]))
            env_lbl.setStyleSheet('font-size: 11px; color: #555; font-family: Consolas;')
            env_lbl.setWordWrap(True)
            self._basic_layout.addWidget(env_lbl)

        self._basic_layout.addStretch()

    def _update_tab_chat(self, result: dict):
        """更新聊天消息 Tab"""
        scan = result.get('scan_all_data', {}) or {}
        messages = scan.get('chat_messages', []) or []
        self._tbl_chat.setRowCount(0)
        if not messages:
            self._chat_hint.show()
            return
        self._chat_hint.hide()
        for idx, msg in enumerate(messages):
            r = self._tbl_chat.rowCount()
            self._tbl_chat.insertRow(r)
            db_path = msg.get('db_path', '')
            table = msg.get('table', '')
            row_data = msg.get('row', {})
            try:
                row_str = json.dumps(row_data, ensure_ascii=False)
            except Exception:
                row_str = str(row_data)
            self._tbl_chat.setItem(r, 0, _item(str(idx + 1)))
            self._tbl_chat.setItem(r, 1, _item(db_path))
            self._tbl_chat.setItem(r, 2, _item(table))
            self._tbl_chat.setItem(r, 3, _item(row_str[:200]))

    def _update_tab_order(self, result: dict):
        """更新订单/商品 Tab"""
        scan = result.get('scan_all_data', {}) or {}
        orders = scan.get('order_info', []) or []
        self._tbl_order.setRowCount(0)
        if not orders:
            self._order_hint.show()
            return
        self._order_hint.hide()
        for idx, item in enumerate(orders):
            r = self._tbl_order.rowCount()
            self._tbl_order.insertRow(r)
            db_path = item.get('db_path', '')
            table = item.get('table', '')
            row_data = item.get('row', {})
            try:
                row_str = json.dumps(row_data, ensure_ascii=False)
            except Exception:
                row_str = str(row_data)
            self._tbl_order.setItem(r, 0, _item(str(idx + 1)))
            self._tbl_order.setItem(r, 1, _item(db_path))
            self._tbl_order.setItem(r, 2, _item(table))
            self._tbl_order.setItem(r, 3, _item(row_str[:200]))

    def _update_tab_cookies(self, result: dict):
        """更新 Cookies Tab"""
        scan = result.get('scan_all_data', {}) or {}
        cookies = scan.get('cookies', []) or []
        self._tbl_cookies.setRowCount(0)
        self._cookies_count_lbl.setText(f'共 {len(cookies)} 条 Cookies')
        if not cookies:
            self._cookies_hint.show()
            return
        self._cookies_hint.hide()
        for idx, ck in enumerate(cookies):
            r = self._tbl_cookies.rowCount()
            self._tbl_cookies.insertRow(r)
            host = ck.get('host', '')
            name = ck.get('name', '')
            value = str(ck.get('value', ''))[:50]
            path = ck.get('path', '')
            exp = ck.get('expires_utc', 0)
            exp_str = str(exp) if exp else '会话'
            self._tbl_cookies.setItem(r, 0, _item(str(idx + 1)))
            self._tbl_cookies.setItem(r, 1, _item(host))
            self._tbl_cookies.setItem(r, 2, _item(name))
            self._tbl_cookies.setItem(r, 3, _item(value))
            self._tbl_cookies.setItem(r, 4, _item(path))
            self._tbl_cookies.setItem(r, 5, _item(exp_str))

    def _update_tab_idb(self, result: dict):
        """更新 IndexedDB Tab"""
        scan = result.get('scan_all_data', {}) or {}
        idb = scan.get('indexeddb', {}) or {}
        total_files = idb.get('total_files', 0)
        total_size = idb.get('total_size_kb', 0.0)
        files = idb.get('files', []) or []
        self._idb_file_count_lbl.setText(f'总文件数: {total_files}')
        self._idb_size_lbl.setText(f'总大小: {total_size:.1f} KB')
        self._tbl_idb.setRowCount(0)
        if not files:
            self._idb_hint.show()
            return
        self._idb_hint.hide()
        for idx, f in enumerate(files):
            r = self._tbl_idb.rowCount()
            self._tbl_idb.insertRow(r)
            self._tbl_idb.setItem(r, 0, _item(str(idx + 1)))
            self._tbl_idb.setItem(r, 1, _item(f.get('path', '')))
            self._tbl_idb.setItem(r, 2, _item(f'{f.get("size_kb", 0.0):.2f}'))

    def _update_tab_ls(self, result: dict):
        """更新本地存储 Tab"""
        scan = result.get('scan_all_data', {}) or {}
        ls_items = scan.get('local_storage', []) or []
        self._tbl_ls.setRowCount(0)
        if not ls_items:
            self._ls_hint.show()
            return
        self._ls_hint.hide()
        for idx, item in enumerate(ls_items):
            r = self._tbl_ls.rowCount()
            self._tbl_ls.insertRow(r)
            origin = item.get('origin', '')
            key = item.get('key', '')
            value = str(item.get('value', ''))[:80]
            self._tbl_ls.setItem(r, 0, _item(str(idx + 1)))
            self._tbl_ls.setItem(r, 1, _item(origin))
            self._tbl_ls.setItem(r, 2, _item(key))
            self._tbl_ls.setItem(r, 3, _item(value))

    def _update_tab_net(self, result: dict):
        """更新网络连接 Tab"""
        # 优先使用 all_connections（含所有连接），否则用 ws_connections
        all_conns = result.get('all_connections', []) or []
        tcp_count = result.get('tcp_count', 0)
        ws_count = sum(1 for c in all_conns if c.get('is_ws_candidate'))
        self._net_stat_lbl.setText(f'TCP 连接数: {tcp_count}   WS候选: {ws_count}')
        self._tbl_net.setRowCount(0)
        if not all_conns:
            self._net_hint.show()
            return
        self._net_hint.hide()
        for idx, c in enumerate(all_conns):
            r = self._tbl_net.rowCount()
            self._tbl_net.insertRow(r)
            local = f"{c.get('local_ip', '')}:{c.get('local_port', '')}"
            remote = f"{c.get('remote_ip', '')}:{c.get('remote_port', '')}"
            status = c.get('status', '')
            is_ws = c.get('is_ws_candidate', False)
            kind = 'WS候选' if is_ws else '普通TCP'
            color = '#e74c3c' if is_ws else None
            self._tbl_net.setItem(r, 0, _item(str(idx + 1), color))
            self._tbl_net.setItem(r, 1, _item(local, color))
            self._tbl_net.setItem(r, 2, _item(remote, color))
            self._tbl_net.setItem(r, 3, _item(status, color))
            self._tbl_net.setItem(r, 4, _item(kind, color))
            # WS候选行背景高亮
            if is_ws:
                for col in range(5):
                    it = self._tbl_net.item(r, col)
                    if it:
                        it.setBackground(QColor('#fff0f0'))

    def _update_tab_dirs(self, result: dict):
        """更新数据目录&文件 Tab"""
        # 数据目录
        self._dirs_list.clear()
        local_data_dirs = result.get('local_data_dirs', []) or []
        for d in local_data_dirs:
            it = QListWidgetItem(str(d))
            it.setForeground(QColor('#0078d4'))
            self._dirs_list.addItem(it)

        # 相关文件（分类着色）
        self._files_list.clear()
        data_files = result.get('data_files', {}) or {}

        # Cookies 文件（绿色）
        for p in data_files.get('cookies_paths', []):
            it = QListWidgetItem(f'[Cookies] {p}')
            it.setForeground(QColor('#00a550'))
            self._files_list.addItem(it)

        # .db/.sqlite 文件（蓝色）
        for p in data_files.get('db_files', []):
            it = QListWidgetItem(f'[DB] {p}')
            it.setForeground(QColor('#0078d4'))
            self._files_list.addItem(it)

        # IndexedDB 目录（橙色）
        for p in data_files.get('indexeddb_dirs', []):
            it = QListWidgetItem(f'[IndexedDB] {p}')
            it.setForeground(QColor('#e67e22'))
            self._files_list.addItem(it)

        # Local Storage 目录（紫色）
        for p in data_files.get('local_storage_dirs', []):
            it = QListWidgetItem(f'[LocalStorage] {p}')
            it.setForeground(QColor('#8e44ad'))
            self._files_list.addItem(it)

        # JSON 配置文件（灰色）—— 直接取 process_watcher 深度扫描时收集的列表
        # 注意：process_watcher.get_process_detail 返回的 data_files 目前未直接暴露 json_configs，
        # 此处从 scan_all_data 中的 data_dirs 路径做简单推断（只显示已知 .db 旁边的 .json 文件）
        scan_data = result.get('scan_all_data', {}) or {}
        scan_data_dirs = scan_data.get('data_dirs', []) or []
        if scan_data_dirs:
            try:
                import os as _os
                for d in scan_data_dirs:
                    for root, _dirs, files in _os.walk(d, followlinks=False):
                        depth = root.replace(d, '').count(_os.sep)
                        if depth > 4:
                            _dirs.clear()
                            continue
                        for fname in files:
                            if fname.lower().endswith('.json'):
                                fpath = _os.path.join(root, fname)
                                it = QListWidgetItem(f'[JSON] {fpath}')
                                it.setForeground(QColor('#888'))
                                self._files_list.addItem(it)
            except Exception:
                pass

    # ──────────────── 表格行双击展开详情 ───────────────────────────────────
    def _on_chat_row_dblclick(self, row: int, _col: int):
        """聊天消息行双击，弹出详情"""
        try:
            scan = self._last_result.get('scan_all_data', {}) or {}
            messages = scan.get('chat_messages', []) or []
            if row < len(messages):
                content = json.dumps(messages[row], ensure_ascii=False, indent=2)
                dlg = _ContentDialog('聊天消息详情', content, self)
                dlg.exec()
        except Exception:
            pass

    def _on_order_row_dblclick(self, row: int, _col: int):
        """订单/商品行双击，弹出详情"""
        try:
            scan = self._last_result.get('scan_all_data', {}) or {}
            orders = scan.get('order_info', []) or []
            if row < len(orders):
                content = json.dumps(orders[row], ensure_ascii=False, indent=2)
                dlg = _ContentDialog('订单/商品详情', content, self)
                dlg.exec()
        except Exception:
            pass

    # ──────────────── 导出 CSV ─────────────────────────────────────────────
    def _on_export_cookies(self):
        """将 Cookies 数据导出为 CSV 文件"""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, '导出 Cookies', 'cookies_export.csv', 'CSV 文件 (*.csv)'
            )
            if not path:
                return
            scan = self._last_result.get('scan_all_data', {}) or {}
            cookies = scan.get('cookies', []) or []
            buf = io.StringIO()
            writer = csv.DictWriter(
                buf,
                fieldnames=['host', 'name', 'value', 'path', 'expires_utc', '_source'],
                extrasaction='ignore',
            )
            writer.writeheader()
            for ck in cookies:
                writer.writerow(ck)
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                f.write(buf.getvalue())
            InfoBar.success(
                title='导出成功',
                content=f'已导出 {len(cookies)} 条 Cookies 到: {path}',
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                title='导出失败',
                content=str(e),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
