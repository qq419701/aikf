# -*- coding: utf-8 -*-
"""
本地配置管理模块
使用 pycryptodome AES-256-CBC 加密敏感字段
"""

import os
import json
import uuid
import base64
import time
from datetime import datetime, timedelta

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad, unpad

# 固定盐值（16字节）
_SALT = b'AIKF_SALT_202603'


def _derive_key() -> bytes:
    """从机器UUID和固定盐值派生AES-256密钥"""
    node = str(uuid.getnode()).encode()
    key = PBKDF2(node, _SALT, dkLen=32, count=10000)
    return key


def _encrypt(text: str) -> str:
    """AES-256-CBC 加密字符串，返回 base64 编码结果"""
    if not text:
        return ''
    key = _derive_key()
    iv = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
    # 将 iv + 密文 合并后 base64 编码
    return base64.b64encode(iv + ct).decode('utf-8')


def _decrypt(text: str) -> str:
    """解密 _encrypt 加密的字符串"""
    if not text:
        return ''
    try:
        key = _derive_key()
        raw = base64.b64decode(text.encode('utf-8'))
        iv = raw[:16]
        ct = raw[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        pt = unpad(cipher.decrypt(ct), AES.block_size)
        return pt.decode('utf-8')
    except Exception:
        return ''


def get_config_dir() -> str:
    """创建并返回 ~/.aikf/ 目录"""
    path = os.path.join(os.path.expanduser('~'), '.aikf')
    os.makedirs(path, exist_ok=True)
    return path


def get_db_path() -> str:
    """返回 ~/.aikf/aikf.db 路径"""
    return os.path.join(get_config_dir(), 'aikf.db')


def get_log_dir() -> str:
    """返回 ~/.aikf/logs/ 目录"""
    path = os.path.join(get_config_dir(), 'logs')
    os.makedirs(path, exist_ok=True)
    return path


def _get_config_file() -> str:
    """返回配置文件路径"""
    return os.path.join(get_config_dir(), 'config.json')


def load_config() -> dict:
    """读取配置文件，返回字典"""
    cfg_file = _get_config_file()
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(data: dict):
    """保存配置字典到文件"""
    cfg_file = _get_config_file()
    with open(cfg_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_activated() -> bool:
    """检查是否已激活（有有效激活码或试用期未过期）"""
    cfg = load_config()
    # 检查激活码
    if cfg.get('license_key_enc'):
        key = get_license()
        if key:
            return True
    # 检查试用期
    remaining = get_trial_remaining()
    if remaining >= 0:
        return True
    return False


def save_license(key: str):
    """加密保存激活码"""
    cfg = load_config()
    cfg['license_key_enc'] = _encrypt(key)
    save_config(cfg)


def get_license() -> str:
    """解密获取激活码"""
    cfg = load_config()
    enc = cfg.get('license_key_enc', '')
    return _decrypt(enc)


def save_trial(days: int = 7):
    """记录试用 expire 时间戳"""
    cfg = load_config()
    expire = datetime.now() + timedelta(days=days)
    cfg['trial_expire'] = expire.timestamp()
    save_config(cfg)


def get_trial_remaining() -> int:
    """返回试用剩余天数，-1 表示过期或未开启试用"""
    cfg = load_config()
    expire_ts = cfg.get('trial_expire')
    if not expire_ts:
        return -1
    remaining = expire_ts - time.time()
    if remaining < 0:
        return -1
    return int(remaining / 86400)


def get_app_config() -> dict:
    """返回应用配置（扫描间隔/托盘/通知等），带默认值"""
    cfg = load_config()
    app_cfg = cfg.get('app', {})
    defaults = {
        'scan_interval': 3,
        'minimize_to_tray': True,
        'desktop_notify': True,
        'auto_start': False,
        'db_type': 'sqlite',
        'mysql_host': 'localhost',
        'mysql_port': 3306,
        'mysql_db': 'aikf',
        'mysql_user': 'root',
        'mysql_pass_enc': '',
    }
    defaults.update(app_cfg)
    return defaults


def save_app_config(data: dict):
    """保存应用配置"""
    cfg = load_config()
    cfg['app'] = data
    save_config(cfg)
