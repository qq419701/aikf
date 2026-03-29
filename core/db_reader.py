# -*- coding: utf-8 -*-
"""
本地数据库深度读取模块
负责读取拼多多/京东等客服软件在本地保存的 SQLite 数据库、Cookies、IndexedDB、LocalStorage 等数据
所有函数异常均被捕获，不向外抛出
"""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime


# SQLite 文件魔数（前 16 字节的前 6 字节）
_SQLITE_MAGIC = b'SQLite'


def _is_sqlite_file(path: str) -> bool:
    """快速判断文件是否为 SQLite 数据库（读取魔数头）"""
    try:
        with open(path, 'rb') as f:
            header = f.read(16)
        return header[:6] == _SQLITE_MAGIC
    except Exception:
        return False


def _copy_db_to_temp(db_path: str) -> str:
    """
    将 SQLite 数据库文件（含 WAL/SHM 辅助文件）复制到临时目录，
    返回临时副本路径。调用方负责在使用完毕后删除临时目录。

    同时复制 .db-wal 和 .db-shm 文件（如果存在），确保 WAL 模式下
    读取的数据尽量完整，并规避原文件被其他进程独占锁定的问题。

    参数:
        db_path (str): 原始数据库文件路径

    返回:
        str: 临时副本文件路径，失败时返回空字符串
    """
    try:
        tmp_dir = tempfile.mkdtemp(prefix='aikf_db_')
        fname = os.path.basename(db_path)
        tmp_path = os.path.join(tmp_dir, fname)
        shutil.copy2(db_path, tmp_path)
        # 同步复制 WAL / SHM 辅助文件（WAL 模式必须同时拷贝才能读到未检查点的数据）
        for suffix in ('-wal', '-shm'):
            aux = db_path + suffix
            if os.path.isfile(aux):
                shutil.copy2(aux, tmp_path + suffix)
        return tmp_path
    except Exception:
        return ''


def read_sqlite_safe(db_path: str, table_hint: str = None, limit: int = 200) -> dict:
    """
    以只读方式打开 SQLite 文件，枚举所有表，返回 {table_name: [row_dict, ...]}。
    如果提供 table_hint，则只读取表名包含该关键词的表。
    捕获所有异常，失败返回 {'error': str}。

    策略：
    1. 优先尝试 file:?mode=ro URI 方式（无副作用，适合未被锁定的文件）。
    2. 若出现数据库锁定错误（database is locked / unable to open），
       自动将文件复制到临时目录再打开（规避进程独占锁）。

    参数:
        db_path (str): SQLite 文件路径
        table_hint (str): 可选，只读取包含此关键词的表（不区分大小写）
        limit (int): 每张表最多读取的行数，默认 200

    返回:
        dict: {表名: [行字典, ...]}，失败时返回 {'error': '错误信息', 'locked': bool}
    """
    def _read_conn(conn) -> dict:
        result = {}
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        for table in tables:
            if table_hint and table_hint.lower() not in table.lower():
                continue
            try:
                cursor.execute(f'SELECT * FROM "{table}" LIMIT {int(limit)}')
                rows = [dict(r) for r in cursor.fetchall()]
                result[table] = rows
            except Exception as table_err:
                result[table] = [{'__read_error__': str(table_err)}]
        conn.close()
        return result

    # 第一次尝试：只读 URI 模式
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=3)
        return _read_conn(conn)
    except Exception as e:
        first_error = str(e)
        # 如果是锁定/无法打开错误，回退到临时副本策略
        locked_keywords = ('locked', 'unable to open', 'disk i/o error', 'readonly')
        if not any(kw in first_error.lower() for kw in locked_keywords):
            return {'error': first_error, 'locked': False}

    # 第二次尝试：复制到临时目录后打开
    tmp_path = _copy_db_to_temp(db_path)
    if not tmp_path:
        return {'error': f'数据库已锁定且无法创建临时副本: {first_error}', 'locked': True}
    tmp_dir = os.path.dirname(tmp_path)
    try:
        conn = sqlite3.connect(tmp_path, timeout=3)
        result = _read_conn(conn)
        result['_read_method'] = '临时副本（原文件已锁定）'
        return result
    except Exception as e2:
        return {'error': f'临时副本读取也失败: {e2}（原始错误: {first_error}）', 'locked': True}
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def extract_chat_messages(data_dirs: list) -> list:
    """
    遍历 data_dirs 下所有 Msg.db / chat.db / message.db 文件，
    读取全部表内容，每条记录返回一个 dict，包含字段：db_path, table, row。

    参数:
        data_dirs (list): 需要搜索的目录路径列表

    返回:
        list[dict]: [{'db_path': str, 'table': str, 'row': dict}, ...]
    """
    messages = []
    # 目标文件名（小写匹配）——包含 WBChat / Xiaoer 常用聊天库文件名
    target_names = {
        'msg.db', 'chat.db', 'message.db',
        'wbchat.db', 'xiaoer.db', 'im.db', 'session.db',
    }
    # 优先搜索的聊天相关子目录（名称含这些关键词则优先进入）
    priority_dir_keywords = {'wbchat', 'xiaoer', 'chat', 'msg', 'im', 'session'}

    def _process_db(db_path: str):
        """读取单个 db 文件并追加结果"""
        try:
            tables_data = read_sqlite_safe(db_path)
            if 'error' in tables_data:
                messages.append({
                    'db_path': db_path,
                    'table': '__error__',
                    'row': {
                        'error': tables_data['error'],
                        'locked': tables_data.get('locked', False),
                    },
                })
                return
            for table_name, rows in tables_data.items():
                if table_name.startswith('__'):
                    continue
                for row in rows:
                    messages.append({
                        'db_path': db_path,
                        'table': table_name,
                        'row': row,
                    })
        except Exception as e:
            messages.append({
                'db_path': db_path,
                'table': '__error__',
                'row': {'error': str(e)},
            })

    for d in data_dirs:
        try:
            for root, dirs, files in os.walk(d, followlinks=False):
                # 限制遍历深度，避免无限递归
                depth = root.replace(d, '').count(os.sep)
                if depth > 8:
                    dirs.clear()
                    continue
                # 仅在浅层（前3级）对子目录排序，优先进入聊天相关目录
                if depth <= 3:
                    dirs.sort(key=lambda x: (
                        0 if any(kw in x.lower() for kw in priority_dir_keywords) else 1,
                        x,
                    ))
                for fname in files:
                    fname_lower = fname.lower()
                    fpath = os.path.join(root, fname)
                    # 1. 名称匹配
                    if fname_lower in target_names:
                        _process_db(fpath)
                        continue
                    # 2. WBChat / Xiaoer 目录下无扩展名文件（可能是 SQLite）
                    dir_lower = root.lower()
                    if (not os.path.splitext(fname)[1]
                            and any(kw in dir_lower for kw in ('wbchat', 'xiaoer'))
                            and _is_sqlite_file(fpath)):
                        _process_db(fpath)
        except Exception:
            pass
    return messages


def extract_order_info(data_dirs: list) -> list:
    """
    遍历 data_dirs 下所有 Info2.db / info.db / order.db / search.db 文件，
    读取订单/商品相关表内容，返回 list[dict]。
    每条记录包含字段：db_path, table, row。

    参数:
        data_dirs (list): 需要搜索的目录路径列表

    返回:
        list[dict]: [{'db_path': str, 'table': str, 'row': dict}, ...]
    """
    orders = []
    # 目标文件名（小写匹配）
    target_names = {'info2.db', 'info.db', 'order.db', 'search.db', 'footprint.db', 'trace.db'}
    for d in data_dirs:
        try:
            for root, dirs, files in os.walk(d, followlinks=False):
                depth = root.replace(d, '').count(os.sep)
                if depth > 8:
                    dirs.clear()
                    continue
                for fname in files:
                    if fname.lower() in target_names:
                        db_path = os.path.join(root, fname)
                        try:
                            tables_data = read_sqlite_safe(db_path)
                            if 'error' in tables_data:
                                orders.append({
                                    'db_path': db_path,
                                    'table': '__error__',
                                    'row': {
                                        'error': tables_data['error'],
                                        'locked': tables_data.get('locked', False),
                                    },
                                })
                                continue
                            for table_name, rows in tables_data.items():
                                if table_name.startswith('__'):
                                    continue
                                for row in rows:
                                    orders.append({
                                        'db_path': db_path,
                                        'table': table_name,
                                        'row': row,
                                    })
                        except Exception as e:
                            orders.append({
                                'db_path': db_path,
                                'table': '__error__',
                                'row': {'error': str(e)},
                            })
        except Exception:
            pass
    return orders


def extract_cookies(cookie_paths: list) -> list:
    """
    读取 Cookies 文件（Chromium/Electron 使用的 SQLite 格式），
    返回 Cookies 列表，每条 dict 包含字段：host, name, value, path, expires_utc。
    捕获所有异常，失败时在列表中记录错误信息。

    参数:
        cookie_paths (list): Cookies 文件路径列表

    返回:
        list[dict]: [{'host': str, 'name': str, 'value': str, 'path': str, 'expires_utc': int}, ...]
    """
    cookies = []
    for cookie_path in cookie_paths:
        def _read_cookies_from_conn(conn, src_path):
            cursor = conn.cursor()
            try:
                cursor.execute(
                    'SELECT host_key, name, value, path, expires_utc FROM cookies LIMIT 2000'
                )
                rows = cursor.fetchall()
                for r in rows:
                    cookies.append({
                        'host': r[0] or '',
                        'name': r[1] or '',
                        'value': r[2] or '',
                        'path': r[3] or '',
                        'expires_utc': r[4] or 0,
                        '_source': src_path,
                    })
            except Exception as inner_e:
                # 尝试枚举所有表查找 cookies 相关表
                try:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]
                    cookies.append({
                        'host': '',
                        'name': '__info__',
                        'value': f'可用表: {tables}',
                        'path': src_path,
                        'expires_utc': 0,
                        '_error': str(inner_e),
                    })
                except Exception:
                    cookies.append({
                        'host': '',
                        'name': '__error__',
                        'value': str(inner_e),
                        'path': src_path,
                        'expires_utc': 0,
                    })
            conn.close()

        # 第一次尝试：只读 URI 模式
        try:
            conn = sqlite3.connect(f'file:{cookie_path}?mode=ro', uri=True, timeout=3)
            _read_cookies_from_conn(conn, cookie_path)
        except Exception as e:
            first_err = str(e)
            locked_kws = ('locked', 'unable to open', 'disk i/o error', 'readonly')
            if any(kw in first_err.lower() for kw in locked_kws):
                # 尝试临时副本
                tmp_path = _copy_db_to_temp(cookie_path)
                tmp_dir = os.path.dirname(tmp_path) if tmp_path else None
                try:
                    if tmp_path:
                        conn2 = sqlite3.connect(tmp_path, timeout=3)
                        _read_cookies_from_conn(conn2, cookie_path)
                    else:
                        cookies.append({
                            'host': '', 'name': '__error__',
                            'value': f'锁定且无法创建副本: {first_err}',
                            'path': cookie_path, 'expires_utc': 0,
                        })
                except Exception as e2:
                    cookies.append({
                        'host': '', 'name': '__error__',
                        'value': str(e2),
                        'path': cookie_path, 'expires_utc': 0,
                    })
                finally:
                    if tmp_dir:
                        try:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                        except Exception:
                            pass
            else:
                cookies.append({
                    'host': '', 'name': '__error__',
                    'value': first_err,
                    'path': cookie_path, 'expires_utc': 0,
                })
    return cookies


def extract_indexeddb_summary(indexeddb_dirs: list) -> dict:
    """
    列出 IndexedDB 目录内所有 .ldb / .log / .idb 文件，统计数量与大小。
    返回汇总字典。

    参数:
        indexeddb_dirs (list): IndexedDB 目录路径列表

    返回:
        dict: {
            'total_files': int,
            'total_size_kb': float,
            'files': [{'path': str, 'size_kb': float}, ...]
        }
    """
    summary = {
        'total_files': 0,
        'total_size_kb': 0.0,
        'files': [],
    }
    # 关注的文件后缀
    target_exts = {'.ldb', '.log', '.idb', '.sst', '.manifest', '.current'}
    for idb_dir in indexeddb_dirs:
        try:
            for root, dirs, files in os.walk(idb_dir, followlinks=False):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in target_exts or not ext:
                        fpath = os.path.join(root, fname)
                        try:
                            size_kb = os.path.getsize(fpath) / 1024.0
                        except Exception:
                            size_kb = 0.0
                        summary['files'].append({'path': fpath, 'size_kb': round(size_kb, 2)})
                        summary['total_files'] += 1
                        summary['total_size_kb'] += size_kb
        except Exception:
            pass
    summary['total_size_kb'] = round(summary['total_size_kb'], 2)
    return summary


def extract_local_storage(local_storage_dirs: list) -> list:
    """
    读取 Local Storage 目录下的 .localstorage 文件（SQLite 格式），
    返回键值记录列表，每条 dict 包含字段：origin, key, value。

    参数:
        local_storage_dirs (list): Local Storage 目录路径列表

    返回:
        list[dict]: [{'origin': str, 'key': str, 'value': str}, ...]
    """
    items = []
    for ls_dir in local_storage_dirs:
        try:
            for fname in os.listdir(ls_dir):
                if not fname.lower().endswith('.localstorage'):
                    continue
                fpath = os.path.join(ls_dir, fname)
                # 文件名通常就是 origin（如 https_xxx.localstorage）
                origin = fname.replace('.localstorage', '')
                try:
                    conn = sqlite3.connect(f'file:{fpath}?mode=ro', uri=True, timeout=3)
                    cursor = conn.cursor()
                    try:
                        # Chromium LocalStorage 的主表名为 ItemTable
                        cursor.execute('SELECT key, value FROM ItemTable LIMIT 500')
                        for r in cursor.fetchall():
                            val = r[1]
                            # value 可能是 bytes
                            if isinstance(val, bytes):
                                try:
                                    val = val.decode('utf-8', errors='replace')
                                except Exception:
                                    val = repr(val)
                            items.append({
                                'origin': origin,
                                'key': r[0] or '',
                                'value': str(val) if val is not None else '',
                            })
                    except Exception as inner_e:
                        items.append({
                            'origin': origin,
                            'key': '__error__',
                            'value': str(inner_e),
                        })
                    conn.close()
                except Exception as e:
                    items.append({
                        'origin': origin,
                        'key': '__error__',
                        'value': str(e),
                    })
        except Exception:
            pass
    return items


def scan_all(
    data_dirs: list,
    cookies_files: list,
    indexeddb_dirs: list,
    local_storage_dirs: list,
) -> dict:
    """
    一次性调用所有检测方法，返回完整的数据汇总字典。
    所有子调用的异常均在内部处理，不会向外抛出。

    参数:
        data_dirs (list): 数据目录列表（用于聊天/订单数据库扫描）
        cookies_files (list): Cookies 文件路径列表
        indexeddb_dirs (list): IndexedDB 目录路径列表
        local_storage_dirs (list): Local Storage 目录路径列表

    返回:
        dict: {
            'chat_messages': list,
            'order_info': list,
            'cookies': list,
            'indexeddb': dict,
            'local_storage': list,
            'scan_time': str,
            'data_dirs': list,
        }
    """
    result = {
        'chat_messages': [],
        'order_info': [],
        'cookies': [],
        'indexeddb': {},
        'local_storage': [],
        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_dirs': list(data_dirs) if data_dirs else [],
    }

    # 读取聊天消息
    try:
        result['chat_messages'] = extract_chat_messages(data_dirs or [])
    except Exception as e:
        result['chat_messages'] = [{'db_path': '', 'table': '__error__', 'row': {'error': str(e)}}]

    # 读取订单/商品信息
    try:
        result['order_info'] = extract_order_info(data_dirs or [])
    except Exception as e:
        result['order_info'] = [{'db_path': '', 'table': '__error__', 'row': {'error': str(e)}}]

    # 读取 Cookies
    try:
        result['cookies'] = extract_cookies(cookies_files or [])
    except Exception as e:
        result['cookies'] = [{'host': '', 'name': '__error__', 'value': str(e), 'path': '', 'expires_utc': 0}]

    # 分析 IndexedDB
    try:
        result['indexeddb'] = extract_indexeddb_summary(indexeddb_dirs or [])
    except Exception as e:
        result['indexeddb'] = {'total_files': 0, 'total_size_kb': 0.0, 'files': [], 'error': str(e)}

    # 读取 LocalStorage
    try:
        result['local_storage'] = extract_local_storage(local_storage_dirs or [])
    except Exception as e:
        result['local_storage'] = [{'origin': '', 'key': '__error__', 'value': str(e)}]

    return result
