# -*- coding: utf-8 -*-
"""
CDP（Chrome DevTools Protocol）数据采集模块
通过 Electron/Chromium 的远程调试接口，实时获取页面数据
"""

import json
import time
import threading
import queue
import requests
from datetime import datetime


class CdpClient:
    """CDP客户端，管理与单个Chromium页面的WebSocket连接"""

    def __init__(self, debug_port: int, page_ws_url: str):
        self._port = debug_port
        self._ws_url = page_ws_url
        self._ws = None
        self._id_counter = 0
        self._id_lock = threading.Lock()
        self._responses = {}  # cmd_id -> response dict
        self._events = queue.Queue()
        self._recv_thread = None
        self._running = False
        self._event_callbacks = []  # 网络事件回调列表

    def connect(self, timeout: float = 5.0) -> bool:
        """建立WebSocket连接，启动后台接收线程，返回是否成功"""
        try:
            import websocket
            self._ws = websocket.WebSocket()
            self._ws.settimeout(timeout)
            self._ws.connect(self._ws_url)
            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            return True
        except Exception:
            self._ws = None
            return False

    def disconnect(self):
        """断开WebSocket连接"""
        self._running = False
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        self._ws = None

    def _next_id(self) -> int:
        """生成唯一命令ID"""
        with self._id_lock:
            self._id_counter += 1
            return self._id_counter

    def _recv_loop(self):
        """后台线程：持续接收WebSocket消息，分发到responses或events"""
        while self._running:
            try:
                if not self._ws:
                    break
                msg = self._ws.recv()
                if not msg:
                    continue
                data = json.loads(msg)
                if 'id' in data:
                    # 命令响应
                    self._responses[data['id']] = data
                elif 'method' in data:
                    # 事件通知
                    self._events.put(data)
                    # 触发事件回调
                    for cb in self._event_callbacks:
                        try:
                            cb(data)
                        except Exception:
                            pass
            except Exception:
                if self._running:
                    time.sleep(0.1)

    def send_command(self, method: str, params: dict = None, timeout: float = 5.0) -> dict:
        """发送CDP命令，等待响应，返回result字典，超时/异常返回{'error': str}"""
        if not self._ws:
            return {'error': '未连接'}
        cmd_id = self._next_id()
        cmd = {'id': cmd_id, 'method': method, 'params': params or {}}
        try:
            self._ws.send(json.dumps(cmd))
        except Exception as e:
            return {'error': f'发送失败: {e}'}
        # 等待响应
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cmd_id in self._responses:
                resp = self._responses.pop(cmd_id)
                if 'error' in resp:
                    return {'error': str(resp['error'])}
                return resp.get('result', {})
            time.sleep(0.05)
        return {'error': f'命令超时: {method}'}

    def evaluate(self, js_code: str, timeout: float = 8.0):
        """执行JavaScript代码，返回值或None"""
        result = self.send_command('Runtime.evaluate', {
            'expression': js_code,
            'returnByValue': True,
            'awaitPromise': False,
        }, timeout=timeout)
        if 'error' in result:
            return None
        return result.get('result', {}).get('value')

    def add_event_callback(self, callback):
        """添加事件回调函数"""
        self._event_callbacks.append(callback)


def get_pages(debug_port: int) -> list:
    """
    获取调试端口上所有页面列表
    返回 [{'id', 'title', 'url', 'webSocketDebuggerUrl', 'type'}, ...]
    失败返回 []
    """
    try:
        resp = requests.get(f'http://localhost:{debug_port}/json', timeout=3)
        pages = resp.json()
        return [p for p in pages if isinstance(p, dict) and 'webSocketDebuggerUrl' in p]
    except Exception:
        return []


def check_debug_port(debug_port: int) -> dict:
    """
    检测调试端口是否可用，返回详细状态字典。

    返回:
        {
            'ok': bool,           # True 表示可用
            'pages': list,        # 可用页面列表（ok=True 时有值）
            'error': str,         # 错误描述（ok=False 时有值）
            'suggestion': str,    # 操作建议（ok=False 时有值）
        }
    """
    result = {'ok': False, 'pages': [], 'error': '', 'suggestion': ''}
    if not debug_port:
        result['error'] = '未指定调试端口'
        result['suggestion'] = (
            '请先为目标进程添加 --remote-debugging-port=9222 参数并重启，'
            '或在「高级」输入框手动填写已知的调试端口号。'
        )
        return result
    try:
        resp = requests.get(f'http://localhost:{debug_port}/json', timeout=3)
        pages = resp.json()
        usable = [p for p in pages if isinstance(p, dict) and 'webSocketDebuggerUrl' in p]
        if usable:
            result['ok'] = True
            result['pages'] = usable
        else:
            result['error'] = f'端口 {debug_port} 已响应，但没有可用的调试页面'
            result['suggestion'] = (
                '目标软件可能尚未完全加载，请等待主界面出现后再扫描；'
                '也可以尝试在软件中打开一个新页面。'
            )
    except requests.exceptions.ConnectionError:
        result['error'] = f'无法连接到调试端口 {debug_port}（Connection refused）'
        result['suggestion'] = (
            f'进程未以调试模式启动。请关闭当前进程，然后用以下方式重新启动：\n'
            f'在命令行添加参数 --remote-debugging-port={debug_port}\n'
            f'（例如：PddWorkbench.exe --remote-debugging-port={debug_port}）\n'
            f'或直接点击「重启并启用调试」按钮自动完成。'
        )
    except requests.exceptions.Timeout:
        result['error'] = f'连接调试端口 {debug_port} 超时'
        result['suggestion'] = (
            '软件可能正在启动或响应慢，请等待几秒后再试。'
            '如果持续超时，请检查防火墙或安全软件是否拦截了本地端口。'
        )
    except Exception as e:
        result['error'] = f'检测端口 {debug_port} 时出错: {e}'
        result['suggestion'] = '请确认端口号正确，并确保目标软件正在运行。'
    return result


def extract_cookies_via_cdp(client: CdpClient) -> list:
    """
    通过CDP Network.getAllCookies获取所有Cookie
    返回 [{'name', 'value', 'domain', 'path', 'expires', 'httpOnly', 'secure'}, ...]
    """
    # 先启用Network域
    client.send_command('Network.enable', timeout=3)
    result = client.send_command('Network.getAllCookies', timeout=5)
    cookies_raw = result.get('cookies', [])
    cookies = []
    for c in cookies_raw:
        cookies.append({
            'name': c.get('name', ''),
            'value': c.get('value', ''),
            'domain': c.get('domain', ''),
            'path': c.get('path', '/'),
            'expires': c.get('expires', 0),
            'httpOnly': c.get('httpOnly', False),
            'secure': c.get('secure', False),
        })
    return cookies


def extract_local_storage_via_cdp(client: CdpClient) -> dict:
    """
    通过执行JS获取localStorage和sessionStorage全部内容
    返回 {'localStorage': {key: value}, 'sessionStorage': {key: value}}
    """
    js = """
    (function(){
        var ls={}, ss={};
        try{
            for(var i=0;i<localStorage.length;i++){
                var k=localStorage.key(i);
                ls[k]=localStorage.getItem(k);
            }
        }catch(e){}
        try{
            for(var i=0;i<sessionStorage.length;i++){
                var k=sessionStorage.key(i);
                ss[k]=sessionStorage.getItem(k);
            }
        }catch(e){}
        return JSON.stringify({localStorage:ls,sessionStorage:ss});
    })()
    """
    raw = client.evaluate(js, timeout=8)
    if raw and isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {'localStorage': {}, 'sessionStorage': {}}


def extract_chat_messages_via_cdp(client: CdpClient) -> list:
    """
    通过JS从页面DOM中抓取聊天消息，适配拼多多工作台多套选择器
    返回 [{'index': int, 'content': str, 'raw_html': str}, ...]
    """
    js = """
    (function(){
        var msgs = [];
        var selectors = [
            '.chat-message-item',
            '.msg-item',
            '.message-item',
            '.chat-item',
            '[class*="message-item"]',
            '[class*="chat-message"]',
            '[class*="msg-item"]',
            '.bubble-wrap',
            '[class*="bubble"]',
            '[class*="MessageItem"]',
            '[class*="ChatMessage"]',
            '.im-chat-message',
            '.chat-msg-item'
        ];
        var items = [];
        for(var s of selectors){
            try{
                var found = document.querySelectorAll(s);
                if(found && found.length > 0){ items = found; break; }
            }catch(e){}
        }
        for(var i=0;i<Math.min(items.length,200);i++){
            var el = items[i];
            try{
                var text = (el.innerText || el.textContent || '').trim();
                msgs.push({
                    index: i,
                    content: text.substring(0,500),
                    raw_html: (el.innerHTML||'').substring(0,800)
                });
            }catch(e){}
        }
        return JSON.stringify(msgs);
    })()
    """
    raw = client.evaluate(js, timeout=10)
    if raw and isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []


def extract_page_data_via_cdp(client: CdpClient) -> dict:
    """
    综合提取页面所有有价值数据
    返回 {'title', 'url', 'cookies', 'local_storage', 'chat_messages', 'page_text', 'error'}
    """
    data = {
        'title': '',
        'url': '',
        'cookies': [],
        'local_storage': {},
        'chat_messages': [],
        'page_text': '',
        'error': '',
    }
    try:
        data['title'] = client.evaluate('document.title') or ''
        data['url'] = client.evaluate('location.href') or ''
        data['page_text'] = client.evaluate('(document.body&&document.body.innerText||"").substring(0,8000)') or ''
        data['cookies'] = extract_cookies_via_cdp(client)
        data['local_storage'] = extract_local_storage_via_cdp(client)
        data['chat_messages'] = extract_chat_messages_via_cdp(client)
    except Exception as e:
        data['error'] = str(e)
    return data


def scan_all_pages(debug_port: int) -> dict:
    """
    一次性扫描指定调试端口上的所有页面，返回汇总数据
    """
    summary = {
        'debug_port': debug_port,
        'pages': [],
        'total_cookies': 0,
        'all_cookies': [],
        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'error': '',
        'suggestion': '',
    }
    try:
        check = check_debug_port(debug_port)
        if not check['ok']:
            summary['error'] = check['error']
            summary['suggestion'] = check['suggestion']
            return summary
        pages = check['pages']
        seen_cookie_keys = set()
        for page in pages:
            page_result = {
                'id': page.get('id', ''),
                'title': page.get('title', ''),
                'url': page.get('url', ''),
                'type': page.get('type', ''),
                'data': {},
            }
            ws_url = page.get('webSocketDebuggerUrl', '')
            if ws_url:
                client = CdpClient(debug_port, ws_url)
                if client.connect(timeout=5):
                    try:
                        page_result['data'] = extract_page_data_via_cdp(client)
                        # 汇总去重Cookie
                        for ck in page_result['data'].get('cookies', []):
                            key = (ck.get('domain', ''), ck.get('name', ''))
                            if key not in seen_cookie_keys:
                                seen_cookie_keys.add(key)
                                summary['all_cookies'].append(ck)
                    except Exception as e:
                        page_result['data'] = {'error': str(e)}
                    finally:
                        client.disconnect()
                else:
                    page_result['data'] = {'error': 'WebSocket连接失败'}
            summary['pages'].append(page_result)
        summary['total_cookies'] = len(summary['all_cookies'])
    except Exception as e:
        summary['error'] = str(e)
    return summary


def start_network_intercept(client: CdpClient, callback) -> bool:
    """
    启动网络请求监听，每次收到响应事件时调用callback(event_dict)
    返回是否成功启动
    """
    try:
        result = client.send_command('Network.enable', timeout=3)
        if 'error' in result:
            return False
        client.add_event_callback(callback)
        return True
    except Exception:
        return False
