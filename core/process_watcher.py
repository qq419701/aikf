# -*- coding: utf-8 -*-
"""
进程监控模块（核心模块）
监控拼多多/京东等平台的商家客服软件进程，采集尽可能多的信息
"""

import os
import re
import sys
import time
import ctypes
from dataclasses import dataclass, field

import psutil
from PyQt6.QtCore import QObject, QThread, pyqtSignal

# 已知进程名称映射
KNOWN_PROCESSES = {
    # 拼多多 - 新版工作台（实测进程名）
    'PddWorkbench.exe': 'pdd',
    'pddworkbench.exe': 'pdd',
    'pddwebworkbench.exe': 'pdd',
    'PddService.exe': 'pdd',
    'PddCoreService.exe': 'pdd',
    'PDDWBGd.exe': 'pdd',
    # 拼多多 - 旧版/其他
    'pddmerchant.exe': 'pdd',
    'pdd_merchant.exe': 'pdd',
    'pinduoduo.exe': 'pdd',
    'pddmerchantapp.exe': 'pdd',
    'merchant.exe': 'pdd',
    'PddBrowser.exe': 'pdd',
    'pddbrowser.exe': 'pdd',
    '拼多多工作台-主程序.exe': 'pdd',
    '拼多多商家工作台-主程序.exe': 'pdd',
    '拼多多商家工作台.exe': 'pdd',
    '拼多多工作台.exe': 'pdd',
    # 京东
    'jd_merchant.exe': 'jd',
    'jdmerchant.exe': 'jd',
    'jingdong.exe': 'jd',
    # 淘宝/千牛
    'AliWorkbench.exe': 'taobao',
    'qianniu.exe': 'taobao',
    # 抖音
    'DouyinMerchant.exe': 'douyin',
    # 快手
    'kwai_merchant.exe': 'kwai',
}

# 窗口标题关键词映射
TITLE_KEYWORDS = {
    '拼多多': 'pdd', 'pinduoduo': 'pdd',
    'PddBrowser': 'pdd',
    'PddWorkbench': 'pdd',
    'pddworkbench': 'pdd',
    '拼多多工作台': 'pdd',
    '拼多多商家工作台': 'pdd',
    '京东': 'jd', '千牛': 'taobao',
    '旺旺': 'taobao', '抖店': 'douyin', '快手': 'kwai',
}

# 平台中文名
PLATFORM_NAMES = {
    'pdd': '拼多多', 'jd': '京东', 'taobao': '淘宝/千牛',
    'douyin': '抖音', 'kwai': '快手', 'unknown': '未知',
}


@dataclass
class NetworkConn:
    """网络连接信息"""
    local_ip: str = ''
    local_port: int = 0
    remote_ip: str = ''
    remote_port: int = 0
    status: str = ''
    is_ws_candidate: bool = False  # 远端 443/80/8080 的 ESTABLISHED 连接


@dataclass
class ShopProcess:
    """店铺进程信息（完整字段）"""
    pid: int = 0
    name: str = ''
    exe_path: str = ''
    platform: str = 'unknown'
    platform_name: str = '未知'
    status: str = ''
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    create_time: float = 0.0
    create_time_str: str = ''
    cmdline: list = field(default_factory=list)
    cmdline_str: str = ''
    connections: list = field(default_factory=list)
    ws_connections: list = field(default_factory=list)
    tcp_count: int = 0
    open_files: list = field(default_factory=list)
    local_data_dirs: list = field(default_factory=list)
    data_files: dict = field(default_factory=dict)
    window_titles: list = field(default_factory=list)
    shop_name: str = ''
    shop_id: str = ''
    debug_port: int = 0
    suspected_tokens: list = field(default_factory=list)
    children: list = field(default_factory=list)
    env_relevant: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)


def _get_window_titles_for_pid(pid: int) -> list:
    """Windows 下枚举指定 pid 的窗口标题"""
    titles = []
    if sys.platform != 'win32':
        return titles
    try:
        EnumWindows = ctypes.windll.user32.EnumWindows
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))

        def callback(hwnd, lParam):
            try:
                if not IsWindowVisible(hwnd):
                    return True
                win_pid = ctypes.c_ulong()
                GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value == pid:
                    length = GetWindowTextLength(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        GetWindowText(hwnd, buf, length + 1)
                        if buf.value:
                            titles.append(buf.value)
            except Exception:
                pass
            return True

        EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        pass
    return titles


def _detect_platform_from_title(titles: list) -> str:
    """从窗口标题检测平台"""
    for title in titles:
        for keyword, platform in TITLE_KEYWORDS.items():
            if keyword.lower() in title.lower():
                return platform
    return 'unknown'


def _extract_shop_name(titles: list) -> str:
    """从窗口标题提取店铺名"""
    pattern = re.compile(r'[-—]\s*(.+?(?:店|旗舰店|专卖店|专营店))')
    for title in titles:
        m = pattern.search(title)
        if m:
            return m.group(1).strip()
    return ''


def _get_local_data_dirs(proc_name: str) -> list:
    """获取应用本地数据目录（含公共目录和用户目录）"""
    dirs = []

    # ── Windows 搜索路径 ──
    if sys.platform == 'win32':
        # 1. C:\Users\Public\Documents\PDD  （拼多多工作台实际写入位置）
        public_docs = os.path.join(os.environ.get('PUBLIC', r'C:\Users\Public'), 'Documents')
        pdd_public_candidates = [
            os.path.join(public_docs, 'PDD'),
            os.path.join(public_docs, 'PDDData'),
            os.path.join(public_docs, 'PinDuoDuo'),
        ]
        for p in pdd_public_candidates:
            if os.path.isdir(p):
                dirs.append(p)

        # 2. 用户目录下常见子目录
        appdata      = os.environ.get('APPDATA', '')
        localappdata = os.environ.get('LOCALAPPDATA', '')
        userprofile  = os.environ.get('USERPROFILE', '')

        app_names = [
            proc_name,
            proc_name.replace('.exe', ''),
            'PDD',
            'PDDData',
            'PddWorkbench',
            'pddworkbench',
            'pinduoduo',
            'PinDuoDuo',
            'pddmerchant',
            'jdmerchant',
            '拼多多',
            '拼多多商家版',
        ]

        base_dirs = []
        if appdata:
            base_dirs.append(appdata)
        if localappdata:
            base_dirs.append(localappdata)
        if userprofile:
            base_dirs.append(os.path.join(userprofile, 'AppData', 'Roaming'))
            base_dirs.append(os.path.join(userprofile, 'AppData', 'Local'))
            base_dirs.append(os.path.join(userprofile, 'Documents'))

        for base in base_dirs:
            for name in app_names:
                candidate = os.path.join(base, name)
                if os.path.isdir(candidate):
                    dirs.append(candidate)

        # 3. 枚举所有用户目录下的 PDD 文件夹（支持多用户场景）
        try:
            users_root = os.path.join(os.environ.get('SystemDrive', 'C:'), 'Users')
            for username in os.listdir(users_root):
                user_path = os.path.join(users_root, username)
                if not os.path.isdir(user_path):
                    continue
                for sub in ['AppData\\Local\\PDD', 'AppData\\Roaming\\PDD',
                            'AppData\\Local\\PddWorkbench', 'AppData\\Roaming\\PddWorkbench',
                            'Documents\\PDD']:
                    p = os.path.join(user_path, sub)
                    if os.path.isdir(p):
                        dirs.append(p)
        except Exception:
            pass

    else:
        # Linux / macOS
        home = os.path.expanduser('~')
        app_names = [
            proc_name,
            proc_name.replace('.exe', ''),
            'pddmerchant',
            'jdmerchant',
            'PddWorkbench',
            'pinduoduo',
        ]
        base_dirs = [
            os.path.join(home, '.config'),
            os.path.join(home, '.local', 'share'),
        ]
        for base in base_dirs:
            for name in app_names:
                candidate = os.path.join(base, name)
                if os.path.isdir(candidate):
                    dirs.append(candidate)

    return list(dict.fromkeys(dirs))  # 去重保序


def _scan_data_files(data_dirs: list) -> dict:
    """在数据目录中扫描���键文件"""
    result = {
        'cookies_files': [],
        'local_storage_dirs': [],
        'indexeddb_dirs': [],
        'json_configs': [],
        'db_files': [],
    }
    for d in data_dirs:
        try:
            for root, dirs, files in os.walk(d, followlinks=False):
                # 跳过太深的目录
                depth = root.replace(d, '').count(os.sep)
                if depth > 6:
                    dirs.clear()
                    continue
                for fname in files:
                    fpath = os.path.join(root, fname)
                    fname_lower = fname.lower()
                    if fname_lower == 'cookies':
                        result['cookies_files'].append(fpath)
                    elif fname_lower.endswith('.json'):
                        result['json_configs'].append(fpath)
                    elif fname_lower.endswith('.db') or fname_lower.endswith('.sqlite'):
                        result['db_files'].append(fpath)
                for dname in dirs:
                    dpath = os.path.join(root, dname)
                    dname_lower = dname.lower()
                    if dname_lower == 'local storage':
                        result['local_storage_dirs'].append(dpath)
                    elif dname_lower == 'indexeddb':
                        result['indexeddb_dirs'].append(dpath)
        except Exception:
            pass
    return result


def _collect_process_info(proc: psutil.Process) -> ShopProcess:
    """采集进程详细信息"""
    sp = ShopProcess()
    try:
        sp.pid = proc.pid
        sp.name = proc.name()
        sp.exe_path = ''
        try:
            sp.exe_path = proc.exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
            pass
        sp.status = proc.status()
        sp.cpu_percent = proc.cpu_percent(interval=0.1)
        try:
            mem = proc.memory_info()
            sp.memory_mb = mem.rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
            pass
        sp.create_time = proc.create_time()
        sp.create_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sp.create_time))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
        pass

    # 命令行
    try:
        sp.cmdline = proc.cmdline()
        sp.cmdline_str = ' '.join(sp.cmdline)
        # 提取调试端口
        m = re.search(r'--remote-debugging-port=(\d+)', sp.cmdline_str)
        if m:
            sp.debug_port = int(m.group(1))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
        pass

    # 网络连接
    try:
        conns = proc.connections('tcp')
        sp.tcp_count = len(conns)
        for c in conns:
            nc = NetworkConn()
            try:
                nc.local_ip = c.laddr.ip if c.laddr else ''
                nc.local_port = c.laddr.port if c.laddr else 0
                nc.remote_ip = c.raddr.ip if c.raddr else ''
                nc.remote_port = c.raddr.port if c.raddr else 0
                nc.status = c.status
                # 判断是否为 WS 候选连接
                if (c.status == 'ESTABLISHED'
                        and c.raddr
                        and c.raddr.port in (443, 80, 8080)):
                    nc.is_ws_candidate = True
                    sp.ws_connections.append(nc)
            except Exception:
                pass
            sp.connections.append(nc)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
        pass

    # 打开的文件（过滤含敏感关键词的路径）
    try:
        sensitive_kws = ['token', 'cookie', 'session', 'auth', 'user', 'login', 'key', 'pdd', 'wbchat']
        open_files = proc.open_files()
        for f in open_files:
            try:
                path_lower = f.path.lower()
                if any(kw in path_lower for kw in sensitive_kws):
                    sp.open_files.append(f.path)
            except Exception:
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
        pass

    # 本地数据目录
    try:
        sp.local_data_dirs = _get_local_data_dirs(sp.name)
    except Exception:
        pass

    # 数据文件扫描
    try:
        if sp.local_data_dirs:
            sp.data_files = _scan_data_files(sp.local_data_dirs)
    except Exception:
        pass

    # 窗口标题（Windows）
    try:
        sp.window_titles = _get_window_titles_for_pid(sp.pid)
    except Exception:
        pass

    # 店铺名提取
    try:
        sp.shop_name = _extract_shop_name(sp.window_titles)
    except Exception:
        pass

    # 疑似 Token（从命令行提取十六进制字符串）
    try:
        tokens = re.findall(r'[0-9a-fA-F]{32,}', sp.cmdline_str)
        sp.suspected_tokens = list(set(tokens))
    except Exception:
        pass

    # 子进程
    try:
        for child in proc.children():
            try:
                sp.children.append({'pid': child.pid, 'name': child.name()})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
        pass

    # 相关环境变量
    try:
        env = proc.environ()
        sensitive_env_kws = ['TOKEN', 'KEY', 'SECRET', 'AUTH', 'USER', 'SHOP']
        sp.env_relevant = {
            k: v for k, v in env.items()
            if any(kw in k.upper() for kw in sensitive_env_kws)
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
        pass

    # 确定平台（进程名匹配，忽略大小写，支持无.exe后缀）
    name_lower = sp.name.lower()
    platform = 'unknown'
    for proc_name, plat in KNOWN_PROCESSES.items():
        if name_lower == proc_name.lower() or name_lower == proc_name.lower().replace('.exe', ''):
            platform = plat
            break
    if platform == 'unknown' and sp.window_titles:
        platform = _detect_platform_from_title(sp.window_titles)
    # 兜底：进程名包含关键词也算
    if platform == 'unknown':
        for keyword, plat in TITLE_KEYWORDS.items():
            if keyword.lower() in name_lower:
                platform = plat
                break
    sp.platform = platform
    sp.platform_name = PLATFORM_NAMES.get(platform, '未知')
    sp.last_updated = time.time()

    return sp


class _ScanThread(QThread):
    """后台扫描线程"""
    process_found = pyqtSignal(object)
    process_lost = pyqtSignal(int)
    process_updated = pyqtSignal(object)
    scan_completed = pyqtSignal(list)
    scan_error = pyqtSignal(str)

    def __init__(self, interval: float = 3.0):
        super().__init__()
        self.interval = interval
        self._running = False
        self._known: dict = {}  # pid -> ShopProcess
        self._force_scan = False

    def run(self):
        """扫描循环"""
        self._running = True
        while self._running:
            try:
                self._do_scan()
            except Exception as e:
                self.scan_error.emit(str(e))
            # 等待间隔，支持强制扫描中断
            elapsed = 0.0
            while self._running and elapsed < self.interval and not self._force_scan:
                time.sleep(0.2)
                elapsed += 0.2
            self._force_scan = False

    def _do_scan(self):
        """执行一次扫描"""
        current_pids = set()
        found_processes = []

        # 构建小写匹配集合（含无.exe后缀形式）
        known_lower = set()
        for k in KNOWN_PROCESSES:
            known_lower.add(k.lower())
            known_lower.add(k.lower().replace('.exe', ''))

        # 标题关键词小写列表（用于进程名兜底匹配）
        title_kw_lower = [kw.lower() for kw in TITLE_KEYWORDS.keys() if kw]

        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    pname = proc.info['name'] or ''
                    pid = proc.info['pid']
                    pname_lower = pname.lower()

                    # 检查是否为已知平台进程
                    is_known = pname_lower in known_lower
                    if not is_known:
                        # 进程名包含平台关键词也纳入
                        is_known = any(kw in pname_lower for kw in title_kw_lower)
                    if not is_known:
                        continue

                    current_pids.add(pid)
                    sp = _collect_process_info(proc)
                    found_processes.append(sp)

                    if pid not in self._known:
                        # 新进程
                        self._known[pid] = sp
                        self.process_found.emit(sp)
                    else:
                        # 已知进程，检查变化
                        old = self._known[pid]
                        if (old.status != sp.status
                                or abs(old.memory_mb - sp.memory_mb) > 5
                                or old.tcp_count != sp.tcp_count):
                            self._known[pid] = sp
                            self.process_updated.emit(sp)
                        else:
                            self._known[pid] = sp

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception):
                    continue
        except Exception as e:
            self.scan_error.emit(f'扫描进程列表失败: {e}')

        # 检查消失的进程
        lost_pids = set(self._known.keys()) - current_pids
        for pid in lost_pids:
            del self._known[pid]
            self.process_lost.emit(pid)

        self.scan_completed.emit(found_processes)

    def trigger_force_scan(self):
        """触发立即扫描"""
        self._force_scan = True

    def stop(self):
        """停止扫描"""
        self._running = False

    def get_all(self) -> list:
        """获取当前所有进程"""
        return list(self._known.values())


class ProcessWatcher(QObject):
    """进程监控管理器"""
    process_found = pyqtSignal(object)
    process_lost = pyqtSignal(int)
    process_updated = pyqtSignal(object)
    scan_completed = pyqtSignal(list)
    scan_error = pyqtSignal(str)

    def __init__(self, scan_interval: float = 3.0):
        super().__init__()
        self.scan_interval = scan_interval
        self._thread: _ScanThread = None

    def start(self):
        """启动后台扫描"""
        if self._thread and self._thread.isRunning():
            return
        self._thread = _ScanThread(self.scan_interval)
        self._thread.process_found.connect(self.process_found)
        self._thread.process_lost.connect(self.process_lost)
        self._thread.process_updated.connect(self.process_updated)
        self._thread.scan_completed.connect(self.scan_completed)
        self._thread.scan_error.connect(self.scan_error)
        self._thread.start()

    def stop(self):
        """停止扫描"""
        if self._thread:
            self._thread.stop()
            self._thread.wait(5000)
            self._thread = None

    def force_scan(self):
        """立即触发一次扫描"""
        if self._thread:
            self._thread.trigger_force_scan()

    def get_all(self) -> list:
        """获取所有检测到的进程"""
        if self._thread:
            return self._thread.get_all()
        return []

    def get_process_detail(self, pid: int) -> dict:
        """深度扫描指定进程，返回详细信息字典"""
        try:
            proc = psutil.Process(pid)
            sp = _collect_process_info(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, Exception) as e:
            return {'error': str(e)}

        result = {
            'pid': sp.pid,
            'name': sp.name,
            'exe_path': sp.exe_path,
            'platform': sp.platform,
            'platform_name': sp.platform_name,
            'status': sp.status,
            'cpu_percent': sp.cpu_percent,
            'memory_mb': sp.memory_mb,
            'create_time_str': sp.create_time_str,
            'cmdline_str': sp.cmdline_str,
            'debug_port': sp.debug_port,
            'tcp_count': sp.tcp_count,
            'ws_connections': [
                {
                    'remote': f'{c.remote_ip}:{c.remote_port}',
                    'status': c.status,
                }
                for c in sp.ws_connections
            ],
            'open_files': sp.open_files,
            'local_data_dirs': sp.local_data_dirs,
            'shop_name': sp.shop_name,
            'window_titles': sp.window_titles,
            'suspected_tokens_count': len(sp.suspected_tokens),
            'children': sp.children,
            'env_relevant_keys': list(sp.env_relevant.keys()),
        }

        # 深度扫描数据目录
        detail_data_files = {}
        try:
            if sp.local_data_dirs:
                sp.data_files = _scan_data_files(sp.local_data_dirs)
                detail_data_files['cookies_count'] = len(sp.data_files.get('cookies_files', []))
                detail_data_files['json_count'] = len(sp.data_files.get('json_configs', []))
                detail_data_files['db_files'] = sp.data_files.get('db_files', [])
                detail_data_files['db_count'] = len(detail_data_files['db_files'])
                detail_data_files['local_storage'] = bool(sp.data_files.get('local_storage_dirs', []))
                detail_data_files['indexeddb'] = bool(sp.data_files.get('indexeddb_dirs', []))
                # 统计 IndexedDB 文件数量
                idb_count = 0
                for idb_dir in sp.data_files.get('indexeddb_dirs', []):
                    try:
                        idb_count += sum(1 for _ in os.scandir(idb_dir))
                    except Exception:
                        pass
                detail_data_files['indexeddb_files'] = idb_count
        except Exception:
            pass
        result['data_files'] = detail_data_files

        return result
