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

    def __init__(self, watcher: ProcessWatcher, pid: int, parent=None):
        super().__init__(parent)
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
        name_label.setStyleSheet('font-weight: bold; font-size: 13px; color: #1a1a1a;')
        row1.addWidget(name_label)
        row1.addStretch()
        layout.addLayout(row1)

        # 第二行：PID + 内存
        pid_label = QLabel(f'PID: {self.sp.pid}  内存: {self.sp.memory_mb:.1f} MB')
        pid_label.setStyleSheet('font-size: 11px; color: #555;')
        layout.addWidget(pid_label)

        # 第三行：店铺名
        if self.sp.shop_name:
            shop_label = QLabel(f'🏪 {self.sp.shop_name}')
            shop_label.setStyleSheet('font-size: 11px; color: #0078d4;')
            layout.addWidget(shop_label)

    def set_selected(self, selected: bool):
        self.selected = selected
        self.setStyleSheet(self.SELECTED_STYLE if selected else self.NORMAL_STYLE)

    # 兼容旧接口
    def set_click_callback(self, callback):
        self._click_callback = callback

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.sp.pid)
            if self._click_callback:
                self._click_callback(self.sp.pid)


# ─────────────────────────── 监控页面 ────────────────────────────────────

class MonitorPage(QWidget):
    """进程监控页面"""

    def __init__(self, watcher: ProcessWatcher = None, parent=None):
        super().__init__(parent)
        self._watcher            = watcher
        self._cards: dict        = {}   # pid -> ProcessCard
        self._selected_pid: int  = -1
        self._detail_worker      = None
        self._current_sp         = None  # 当前右侧显示的 ShopProcess
        self.setObjectName('monitorPage')
        self._setup_ui()
        self._connect_signals()

    # ── 构建 UI ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ── 左侧 ──
        left_widget = QWidget()
        left_widget.setMinimumWidth(260)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(16, 16, 8, 16)
        left_layout.setSpacing(8)

        title_row = QHBoxLayout()
        left_title = SubtitleLabel('检测到的进程')
        self._scan_btn = PushButton('🔄 立即扫描')
        self._scan_btn.setFixedHeight(32)
        self._scan_btn.clicked.connect(self._on_force_scan)
        title_row.addWidget(left_title)
        title_row.addStretch()
        title_row.addWidget(self._scan_btn)
        left_layout.addLayout(title_row)

        self._status_label = CaptionLabel('等待扫描...')
        self._status_label.setStyleSheet('color: #888;')
        left_layout.addWidget(self._status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cards_container = QWidget()
        self._cards_layout    = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_label = QLabel('🔍 未检测到客服软件\n请打开拼多多/京东商家客服软件')
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet('color: #aaa; font-size: 13px; padding: 24px;')
        self._cards_layout.addWidget(self._empty_label)

        scroll.setWidget(self._cards_container)
        left_layout.addWidget(scroll)

        # ── 右侧 ──
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 16, 16, 16)
        right_layout.setSpacing(8)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._detail_container = QWidget()
        self._detail_layout    = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(8)
        self._detail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._placeholder = QLabel('← 点击左侧进程查看详情')
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet('color: #aaa; font-size: 14px; padding: 60px;')
        self._detail_layout.addWidget(self._placeholder)

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

    # ── 信号连接 ───────────────────────────────────────────────────────────

    def _connect_signals(self):
        if not self._watcher:
            return
        self._watcher.process_found.connect(self._on_process_found)
        self._watcher.process_lost.connect(self._on_process_lost)
        self._watcher.process_updated.connect(self._on_process_updated)
        self._watcher.scan_completed.connect(self._on_scan_completed)

    # ── watcher 信号槽 ─────────────────────────────────────────────────────

    def _on_process_found(self, sp: ShopProcess):
        card = ProcessCard(sp)
        card.clicked.connect(self._on_card_clicked)
        self._cards[sp.pid] = card
        self._cards_layout.addWidget(card)
        self._empty_label.hide()

    def _on_process_lost(self, pid: int):
        if pid in self._cards:
            card = self._cards.pop(pid)
            self._cards_layout.removeWidget(card)
            card.deleteLater()
            if self._selected_pid == pid:
                self._selected_pid  = -1
                self._current_sp    = None
                self._clear_detail()
        if not self._cards:
            self._empty_label.show()

    def _on_process_updated(self, sp: ShopProcess):
        if sp.pid not in self._cards:
            return
        old_card = self._cards[sp.pid]
        idx      = self._cards_layout.indexOf(old_card)
        if idx < 0:
            return
        was_selected = (self._selected_pid == sp.pid)
        new_card = ProcessCard(sp)
        new_card.clicked.connect(self._on_card_clicked)
        if was_selected:
            new_card.set_selected(True)
        self._cards_layout.insertWidget(idx, new_card)
        self._cards_layout.removeWidget(old_card)
        old_card.deleteLater()
        self._cards[sp.pid] = new_card
        if was_selected:
            self._current_sp = sp
            self._show_basic_detail(sp)

    def _on_scan_completed(self, processes: list):
        now = datetime.now().strftime('%H:%M:%S')
        self._status_label.setText(f'自动扫描中... 上次: {now}')

    # ── 卡片点击 ──────────────────────────────────────────────────────────

    def _on_card_clicked(self, pid: int):
        """点击卡片 — 只用缓存数据，不做任何阻塞 IO"""
        # 取消旧选中
        if self._selected_pid in self._cards:
            self._cards[self._selected_pid].set_selected(False)

        self._selected_pid = pid

        if pid in self._cards:
            self._cards[pid].set_selected(True)

        # 直接从卡片对象拿 ShopProcess，不遍历 get_all()
        if pid in self._cards:
            sp = self._cards[pid].sp
            self._current_sp = sp
            self._show_basic_detail(sp)

    # ── 详情面板 ──────────────────────────────────────────────────────────

    def _clear_detail(self):
        """安全清空右侧详情区"""
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                # layout item
                sub = item.layout()
                if sub is not None:
                    while sub.count():
                        si = sub.takeAt(0)
                        sw = si.widget()
                        if sw:
                            sw.setParent(None)
                            sw.deleteLater()

    def _show_basic_detail(self, sp: ShopProcess):
        """右侧显示进程基本详情（纯缓存数据，零 IO，零阻塞）"""
        self._clear_detail()

        # 安全计算运行时长
        elapsed_str = '未知'
        try:
            if sp.create_time and sp.create_time > 0:
                elapsed = int(time.time() - sp.create_time)
                elapsed = max(0, elapsed)
                h = elapsed // 3600
                m = (elapsed % 3600) // 60
                s = elapsed % 60
                elapsed_str = f'{h}h {m}m {s}s'
        except Exception:
            pass

        def section(title: str) -> QLabel:
            lbl = QLabel(title)
            lbl.setStyleSheet(
                'font-size: 12px; font-weight: bold; color: #555;'
                'border-bottom: 1px solid #eee; padding-bottom: 2px; margin-top: 8px;'
            )
            return lbl

        def kv_row(label: str, value: str, color: str = '#333') -> QWidget:
            """返回一个装好的 QWidget，避免裸 QHBoxLayout 被 GC"""
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            key_lbl = QLabel(label)
            key_lbl.setStyleSheet('font-size: 12px; color: #888;')
            key_lbl.setFixedWidth(100)
            val_lbl = QLabel(str(value))
            val_lbl.setStyleSheet(f'font-size: 12px; color: {color};')
            val_lbl.setWordWrap(True)
            h.addWidget(key_lbl)
            h.addWidget(val_lbl, 1)
            return w

        # ── 基本信息 ──
        self._detail_layout.addWidget(section('基本信息'))
        self._detail_layout.addWidget(kv_row('进程名', sp.name))
        self._detail_layout.addWidget(kv_row('PID', str(sp.pid)))
        self._detail_layout.addWidget(kv_row('平台', sp.platform_name, '#0078d4'))
        self._detail_layout.addWidget(kv_row('状态', sp.status,
                                              '#00a550' if sp.status == 'running' else '#e67e22'))
        self._detail_layout.addWidget(kv_row('路径', sp.exe_path or '未知'))
        self._detail_layout.addWidget(kv_row('内存', f'{sp.memory_mb:.1f} MB'))
        self._detail_layout.addWidget(kv_row('CPU', f'{sp.cpu_percent:.1f}%'))
        self._detail_layout.addWidget(kv_row('启动时间', sp.create_time_str or '未知'))
        self._detail_layout.addWidget(kv_row('运行时长', elapsed_str))

        # ── 店铺信息 ──
        if sp.shop_name or sp.window_titles:
            self._detail_layout.addWidget(section('店铺信息'))
            if sp.shop_name:
                self._detail_layout.addWidget(kv_row('店铺名', sp.shop_name, '#0078d4'))
            if sp.window_titles:
                self._detail_layout.addWidget(kv_row('窗口标题', sp.window_titles[0]))

        # ── 网络连接 ──
        self._detail_layout.addWidget(section('网络连接'))
        self._detail_layout.addWidget(kv_row('TCP连接数', str(sp.tcp_count)))
        ws_count = len(sp.ws_connections) if sp.ws_connections else 0
        self._detail_layout.addWidget(
            kv_row('WS候选连接', str(ws_count), '#e74c3c' if ws_count else '#333')
        )
        if sp.debug_port:
            self._detail_layout.addWidget(kv_row('调试端口', str(sp.debug_port), '#e74c3c'))
        for ws in (sp.ws_connections or [])[:5]:
            try:
                self._detail_layout.addWidget(
                    kv_row('', f'{ws.remote_ip}:{ws.remote_port}  [{ws.status}]', '#e74c3c')
                )
            except Exception:
                pass

        # ── 命令行 ──
        if sp.cmdline_str:
            self._detail_layout.addWidget(section('命令行'))
            cmd_box = QPlainTextEdit(sp.cmdline_str)
            cmd_box.setReadOnly(True)
            cmd_box.setMaximumHeight(80)
            f = QFont('Consolas', 10)
            f.setStyleHint(QFont.StyleHint.Monospace)
            cmd_box.setFont(f)
            self._detail_layout.addWidget(cmd_box)

        # ── 相关文件 ──
        if sp.open_files:
            self._detail_layout.addWidget(section(f'相关文件（{min(len(sp.open_files),10)}/{len(sp.open_files)}）'))
            for fpath in sp.open_files[:10]:
                lbl = QLabel(str(fpath))
                f2  = QFont('Consolas', 10)
                f2.setStyleHint(QFont.StyleHint.Monospace)
                lbl.setFont(f2)
                lbl.setStyleSheet('font-size: 11px; color: #555;')
                lbl.setWordWrap(True)
                self._detail_layout.addWidget(lbl)

        # ── 子进程 ──
        if sp.children:
            self._detail_layout.addWidget(section(f'子进程（{min(len(sp.children),5)}/{len(sp.children)}）'))
            for child in sp.children[:5]:
                try:
                    self._detail_layout.addWidget(
                        kv_row(str(child.get('pid', '')), str(child.get('name', '')))
                    )
                except Exception:
                    pass

        hint = QLabel('点击「🔍 深度扫描」获取数据目录、IndexedDB 等更多信息')
        hint.setStyleSheet('color: #aaa; font-size: 11px; padding-top: 8px;')
        self._detail_layout.addWidget(hint)
        self._detail_layout.addStretch()

    # ── 工具按钮 ──────────────────────────────────────────────────────────

    def _on_force_scan(self):
        if self._watcher:
            self._watcher.force_scan()
        self._status_label.setText('正在扫描...')

    def _on_copy_info(self):
        if self._current_sp is None:
            return
        sp = self._current_sp
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
            f'WS连接数: {len(sp.ws_connections) if sp.ws_connections else 0}',
            f'调试端口: {sp.debug_port or "无"}',
            f'窗口标题: {"; ".join(sp.window_titles) if sp.window_titles else ""}',
            f'店铺名: {sp.shop_name or "未知"}',
            f'疑似Token数: {len(sp.suspected_tokens) if sp.suspected_tokens else 0}',
            f'数据目录: {"; ".join(sp.local_data_dirs) if sp.local_data_dirs else ""}',
        ]
        QApplication.clipboard().setText('\n'.join(lines))
        InfoBar.success(
            title='已复制',
            content='进程信息已复制到剪贴板',
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def _on_deep_scan(self):
        """后台深度扫描，不阻塞 UI"""
        if self._selected_pid < 0 or not self._watcher:
            return
        if self._detail_worker and self._detail_worker.isRunning():
            InfoBar.warning(
                title='扫描中',
                content='深度扫描正在进行，请稍候...',
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self
            )
            return
        self._deep_scan_btn.setEnabled(False)
        self._deep_scan_btn.setText('⏳ 扫描中...')
        self._detail_worker = _DetailWorker(self._watcher, self._selected_pid, self)
        self._detail_worker.finished.connect(self._on_deep_scan_finished)
        self._detail_worker.error.connect(self._on_deep_scan_error)
        self._detail_worker.start()

    def _on_deep_scan_finished(self, detail: dict):
        self._deep_scan_btn.setEnabled(True)
        self._deep_scan_btn.setText('🔍 深度扫描')
        idb_files = detail.get('data_files', {}).get('indexeddb_files', 0)
        cookies   = detail.get('data_files', {}).get('cookies_count', 0)
        InfoBar.success(
            title='深度扫描完成',
            content=f'IndexedDB文件: {idb_files} 个  Cookies: {cookies} 个',
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def _on_deep_scan_error(self, msg: str):
        self._deep_scan_btn.setEnabled(True)
        self._deep_scan_btn.setText('🔍 深度扫描')
        InfoBar.error(
            title='深度扫描失败',
            content=msg,
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self
        )