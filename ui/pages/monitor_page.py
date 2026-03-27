# -*- coding: utf-8 -*-
"""
进程监控页面（核心页面）
左右分栏：左侧进程列表，右侧详情面板
"""

import time
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QScrollArea, QLabel, QFrame, QPlainTextEdit,
    QApplication
)
from qfluentwidgets import (
    SubtitleLabel, CaptionLabel,
    PushButton, PrimaryPushButton, InfoBar, InfoBarPosition
)

from core.process_watcher import ProcessWatcher, ShopProcess


# ─────────────────────────── 后台深度扫描线程 ────────────────────────────
class _DetailWorker(QThread):
    """后台深度扫描，不阻塞 UI 主线程"""
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, watcher: ProcessWatcher, pid: int):
        super().__init__()
        self._watcher = watcher
        self._pid     = pid

    def run(self):
        try:
            result = self._watcher.get_process_detail(self._pid)
            if isinstance(result, dict) and 'error' in result:
                self.error.emit(result['error'])
            else:
                self.finished.emit(result if isinstance(result, dict) else {})
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────── 进程卡片 ────────────────────────────────────
class ProcessCard(QFrame):
    """进程卡片"""
    clicked = pyqtSignal(int)   # 发出 pid

    NORMAL_STYLE = """
        QFrame {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 8px;
        }
        QFrame:hover { border-color: #0078d4; }
        QFrame > QLabel { color: #1a1a1a; background: transparent; }
    """
    SELECTED_STYLE = """
        QFrame {
            background: #e8f0fe;
            border: 2px solid #0078d4;
            border-radius: 8px;
            padding: 8px;
        }
        QFrame > QLabel { color: #1a1a1a; background: transparent; }
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
        status = getattr(self.sp, 'status', '')
        status_icon = '🟢' if status == 'running' else '🟡'
        status_label = QLabel(status_icon)
        status_label.setFixedWidth(20)
        row1.addWidget(status_label)

        platform_name = getattr(self.sp, 'platform_name', '未知')
        proc_name     = getattr(self.sp, 'name', '')
        name_label = QLabel(f'{platform_name} · {proc_name}')
        name_label.setStyleSheet('font-weight: bold; font-size: 13px; color: #1a1a1a;')
        row1.addWidget(name_label)
        row1.addStretch()
        layout.addLayout(row1)

        # 第二行：PID + 内存
        pid       = getattr(self.sp, 'pid', 0)
        memory_mb = getattr(self.sp, 'memory_mb', 0.0)
        pid_label = QLabel(f'PID: {pid}  内存: {memory_mb:.1f} MB')
        pid_label.setStyleSheet('font-size: 11px; color: #555;')
        layout.addWidget(pid_label)

        # 第三行：店铺名（有的话）
        shop_name = getattr(self.sp, 'shop_name', '')
        if shop_name:
            shop_label = QLabel(f'🏪 {shop_name}')
            shop_label.setStyleSheet('font-size: 11px; color: #0078d4;')
            layout.addWidget(shop_label)

    def set_selected(self, selected: bool):
        """设置选中状态"""
        self.selected = selected
        self.setStyleSheet(self.SELECTED_STYLE if selected else self.NORMAL_STYLE)

    def set_click_callback(self, callback):
        """兼容旧接口"""
        self._click_callback = callback

    def mousePressEvent(self, event):
        """点击卡片"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.sp.pid)
            if self._click_callback:
                self._click_callback(self.sp.pid)


# ─────────────────────────── 监控页面 ────────────────────────────────────
class MonitorPage(QWidget):
    """进程监控页面"""

    def __init__(self, watcher: ProcessWatcher = None, parent=None):
        super().__init__(parent)
        self._watcher = watcher
        self._cards: dict = {}       # pid -> ProcessCard
        self._selected_pid: int = -1
        self._detail_worker: _DetailWorker = None
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
        card.clicked.connect(self._on_card_clicked)
        self._cards[sp.pid] = card
        self._cards_layout.addWidget(card)
        self._empty_label.hide()

    def _on_process_lost(self, pid: int):
        """移除进程卡片"""
        if pid in self._cards:
            card = self._cards.pop(pid)
            self._cards_layout.removeWidget(card)
            try:
                card.deleteLater()
            except RuntimeError:
                pass
            if self._selected_pid == pid:
                self._selected_pid = -1
                self._clear_detail()
        if not self._cards:
            self._empty_label.show()

    def _on_process_updated(self, sp: ShopProcess):
        """进程信息更新"""
        if sp.pid in self._cards:
            old_card = self._cards[sp.pid]
            idx = self._cards_layout.indexOf(old_card)
            new_card = ProcessCard(sp)
            new_card.clicked.connect(self._on_card_clicked)
            if self._selected_pid == sp.pid:
                new_card.set_selected(True)
            self._cards_layout.insertWidget(idx, new_card)
            self._cards_layout.removeWidget(old_card)
            try:
                old_card.deleteLater()
            except RuntimeError:
                pass
            self._cards[sp.pid] = new_card
            if self._selected_pid == sp.pid:
                self._show_basic_detail(sp)

    def _on_scan_completed(self, processes: list):
        """扫描完成，更新时间戳"""
        now = datetime.now().strftime('%H:%M:%S')
        self._status_label.setText(f'自动扫描中... 上次: {now}')

    def _on_card_clicked(self, pid: int):
        """点击卡片，仅显示已缓存的基本信息（不阻塞主线程）"""
        try:
            if self._selected_pid in self._cards:
                self._cards[self._selected_pid].set_selected(False)
            self._selected_pid = pid
            if pid in self._cards:
                self._cards[pid].set_selected(True)
            for sp in (self._watcher.get_all() if self._watcher else []):
                if sp.pid == pid:
                    self._show_basic_detail(sp)
                    return
        except Exception as e:
            self._show_error_detail(f'加载进程信息失败: {e}')

    def _on_force_scan(self):
        """立即扫描"""
        if self._watcher:
            self._watcher.force_scan()
        self._status_label.setText('正在扫描...')

    def _clear_detail(self):
        """彻底清空右侧详情区域，包括 widget 和 layout 条目"""
        # 逐一取出并销毁所有子项（含嵌套 layout）
        def _remove_layout_items(layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.hide()
                    try:
                        w.deleteLater()
                    except RuntimeError:
                        pass
                else:
                    sub = item.layout()
                    if sub is not None:
                        _remove_layout_items(sub)
                        try:
                            sub.deleteLater()
                        except RuntimeError:
                            pass

        _remove_layout_items(self._detail_layout)

        # 重置"空占位"提示
        self._no_select_label = QLabel('← 点击左侧进程查看详情')
        self._no_select_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_select_label.setStyleSheet('color: #aaa; font-size: 14px; padding: 60px;')
        self._detail_layout.addWidget(self._no_select_label)

    def _show_error_detail(self, msg: str):
        """右侧显示错误信息"""
        self._clear_detail()
        lbl = QLabel(f'⚠️ {msg}')
        lbl.setStyleSheet('color: #e74c3c; font-size: 13px; padding: 20px;')
        lbl.setWordWrap(True)
        self._detail_layout.addWidget(lbl)

    def _show_basic_detail(self, sp: ShopProcess):
        """在右侧显示进程基本详情（使用已缓存数据，不阻塞）"""
        # ── 先彻底清空旧内容（包括嵌套 layout）──
        def _remove_layout_items(layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.hide()
                    try:
                        w.deleteLater()
                    except RuntimeError:
                        pass
                else:
                    sub = item.layout()
                    if sub is not None:
                        _remove_layout_items(sub)
                        try:
                            sub.deleteLater()
                        except RuntimeError:
                            pass

        _remove_layout_items(self._detail_layout)

        create_time = getattr(sp, 'create_time', 0) or 0
        elapsed = int(time.time() - create_time) if create_time else 0
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60

        def section(title: str) -> QLabel:
            lbl = QLabel(title)
            lbl.setStyleSheet(
                'font-size: 12px; font-weight: bold; color: #555; '
                'border-bottom: 1px solid #eee; padding-bottom: 2px; margin-top: 8px;'
            )
            return lbl

        def row(label: str, value: str, color: str = '#333') -> QHBoxLayout:
            h_layout = QHBoxLayout()
            key_lbl = QLabel(label)
            key_lbl.setStyleSheet('font-size: 12px; color: #888; min-width: 90px;')
            key_lbl.setFixedWidth(100)
            val_lbl = QLabel(str(value))
            val_lbl.setStyleSheet(f'font-size: 12px; color: {color};')
            val_lbl.setWordWrap(True)
            h_layout.addWidget(key_lbl)
            h_layout.addWidget(val_lbl, 1)
            return h_layout

        # ── 基本信息 ──
        self._detail_layout.addWidget(section('基本信息'))
        self._detail_layout.addLayout(row('进程名', getattr(sp, 'name', '')))
        self._detail_layout.addLayout(row('PID', str(getattr(sp, 'pid', ''))))
        platform_name = getattr(sp, 'platform_name', '未知')
        self._detail_layout.addLayout(row('平台', platform_name, '#0078d4'))
        status = getattr(sp, 'status', '')
        self._detail_layout.addLayout(row('状态', status,
                                          '#00a550' if status == 'running' else '#e67e22'))
        self._detail_layout.addLayout(row('路径', getattr(sp, 'exe_path', '') or '未知'))
        self._detail_layout.addLayout(row('内存', f"{getattr(sp, 'memory_mb', 0.0):.1f} MB"))
        self._detail_layout.addLayout(row('CPU', f"{getattr(sp, 'cpu_percent', 0.0):.1f}%"))
        self._detail_layout.addLayout(row('启动时间', getattr(sp, 'create_time_str', '')))
        self._detail_layout.addLayout(row('运行时长', f'{h}h {m}m {s}s'))

        # ── 店铺信息 ──
        shop_name     = getattr(sp, 'shop_name', '')
        window_titles = getattr(sp, 'window_titles', []) or []
        if shop_name or window_titles:
            self._detail_layout.addWidget(section('店铺信息'))
            if shop_name:
                self._detail_layout.addLayout(row('店铺名', shop_name, '#0078d4'))
            if window_titles:
                self._detail_layout.addLayout(row('窗口标题', window_titles[0]))

        # ── 网络连接 ──
        ws_connections = getattr(sp, 'ws_connections', []) or []
        tcp_count      = getattr(sp, 'tcp_count', 0)
        debug_port     = getattr(sp, 'debug_port', 0)
        self._detail_layout.addWidget(section('网络连接'))
        self._detail_layout.addLayout(row('TCP连接数', str(tcp_count)))
        self._detail_layout.addLayout(
            row('WS候选连接', str(len(ws_connections)),
                '#e74c3c' if ws_connections else '#333')
        )
        if debug_port:
            self._detail_layout.addLayout(row('调试端口', str(debug_port), '#e74c3c'))
        for ws in ws_connections[:5]:
            if isinstance(ws, dict):
                remote_ip   = ws.get('remote_ip', '')
                remote_port = ws.get('remote_port', '')
                ws_status   = ws.get('status', '')
            else:
                remote_ip   = getattr(ws, 'remote_ip', '')
                remote_port = getattr(ws, 'remote_port', '')
                ws_status   = getattr(ws, 'status', '')
            self._detail_layout.addLayout(
                row('', f'{remote_ip}:{remote_port}  [{ws_status}]', '#e74c3c')
            )

        # ── 数据目录 ──
        local_data_dirs = getattr(sp, 'local_data_dirs', []) or []
        if local_data_dirs:
            self._detail_layout.addWidget(section('数据目录'))
            for d in local_data_dirs[:5]:
                lbl = QLabel(str(d))
                lbl.setStyleSheet('font-size: 11px; color: #0078d4;')
                lbl.setWordWrap(True)
                self._detail_layout.addWidget(lbl)

        # ── 命令行 ──
        cmdline_str = getattr(sp, 'cmdline_str', '')
        if cmdline_str:
            self._detail_layout.addWidget(section('命令行'))
            cmd_box = QPlainTextEdit(cmdline_str)
            cmd_box.setReadOnly(True)
            cmd_box.setMaximumHeight(80)
            font = QFont('Consolas', 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            cmd_box.setFont(font)
            self._detail_layout.addWidget(cmd_box)

        # ── 相关文件 ──
        open_files = getattr(sp, 'open_files', []) or []
        if open_files:
            self._detail_layout.addWidget(section('相关文件（最多10个）'))
            for fpath in open_files[:10]:
                lbl = QLabel(str(fpath))
                font = QFont('Consolas', 10)
                font.setStyleHint(QFont.StyleHint.Monospace)
                lbl.setFont(font)
                lbl.setStyleSheet('font-size: 11px; color: #555;')
                lbl.setWordWrap(True)
                self._detail_layout.addWidget(lbl)

        # ── 子进程 ──
        children = getattr(sp, 'children', []) or []
        if children:
            self._detail_layout.addWidget(section('子进程（最多5个）'))
            for child in children[:5]:
                if isinstance(child, dict):
                    c_pid  = str(child.get('pid', ''))
                    c_name = child.get('name', '')
                else:
                    c_pid  = str(getattr(child, 'pid', ''))
                    c_name = getattr(child, 'name', '')
                self._detail_layout.addLayout(row(c_pid, c_name))

        # 提示用户可做深度扫描
        hint = QLabel('点击「🔍 深度扫描」获取数据目录、IndexedDB 等更多信息')
        hint.setStyleSheet('color: #aaa; font-size: 11px; padding-top: 8px;')
        self._detail_layout.addWidget(hint)

        self._detail_layout.addStretch()

    # 保留旧名以防外部引用
    def _show_detail(self, sp: ShopProcess):
        self._show_basic_detail(sp)

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

        ws_connections   = getattr(sp, 'ws_connections', []) or []
        window_titles    = getattr(sp, 'window_titles', []) or []
        suspected_tokens = getattr(sp, 'suspected_tokens', []) or []
        local_data_dirs  = getattr(sp, 'local_data_dirs', []) or []

        lines = [
            f"进程名: {getattr(sp, 'name', '')}",
            f"PID: {getattr(sp, 'pid', '')}",
            f"平台: {getattr(sp, 'platform_name', '')}",
            f"路径: {getattr(sp, 'exe_path', '')}",
            f"状态: {getattr(sp, 'status', '')}",
            f"CPU: {getattr(sp, 'cpu_percent', 0.0):.1f}%",
            f"内存: {getattr(sp, 'memory_mb', 0.0):.1f} MB",
            f"启动时间: {getattr(sp, 'create_time_str', '')}",
            f"命令行: {getattr(sp, 'cmdline_str', '')}",
            f"TCP连接数: {getattr(sp, 'tcp_count', 0)}",
            f"WS连接数: {len(ws_connections)}",
            f"调试端口: {getattr(sp, 'debug_port', 0) or '无'}",
            f"窗口标题: {'; '.join(window_titles)}",
            f"店铺名: {getattr(sp, 'shop_name', '') or '未知'}",
            f"疑似Token数: {len(suspected_tokens)}",
            f"数据目录: {'; '.join(local_data_dirs)}",
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
        """后台深度扫描当前选中进程，不阻塞 UI"""
        if self._selected_pid < 0 or not self._watcher:
            return

        # 防止重复启动
        if self._detail_worker and self._detail_worker.isRunning():
            InfoBar.warning(
                title='扫描中',
                content='深度扫描正在进行，请稍候...',
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self
            )
            return

        # 断开旧信号防止重复触发
        if self._detail_worker is not None:
            try:
                self._detail_worker.finished.disconnect()
                self._detail_worker.error.disconnect()
            except RuntimeError:
                pass
            self._detail_worker = None

        self._deep_scan_btn.setEnabled(False)
        self._deep_scan_btn.setText('⏳ 扫描中...')

        self._detail_worker = _DetailWorker(self._watcher, self._selected_pid)
        self._detail_worker.finished.connect(self._on_deep_scan_finished)
        self._detail_worker.error.connect(self._on_deep_scan_error)
        self._detail_worker.start()

    def _on_deep_scan_finished(self, detail: dict):
        """深度扫描完成"""
        self._deep_scan_btn.setEnabled(True)
        self._deep_scan_btn.setText('🔍 深度扫描')
        data_files  = detail.get('data_files', {}) or {}
        idb_files   = data_files.get('indexeddb_files', 0)
        cookies     = data_files.get('cookies_count', 0)
        InfoBar.success(
            title='深度扫描完成',
            content=f'IndexedDB文件: {idb_files} 个  Cookies: {cookies} 个',
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def _on_deep_scan_error(self, msg: str):
        """深度扫描失败"""
        self._deep_scan_btn.setEnabled(True)
        self._deep_scan_btn.setText('🔍 深度扫描')
        InfoBar.error(
            title='深度扫描失败',
            content=msg,
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self
        )

