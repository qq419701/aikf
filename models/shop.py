# -*- coding: utf-8 -*-
"""
店铺数据模型
"""

from dataclasses import dataclass, field


@dataclass
class Shop:
    """店铺信息"""
    id: str = ''
    name: str = ''
    platform: str = 'pdd'
    process_name: str = ''
    process_pid: int = 0
    is_active: bool = True
    first_seen: str = ''
    last_seen: str = ''
