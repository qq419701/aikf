# -*- coding: utf-8 -*-
"""
数据库模块
使用 sqlite3 管理6张核心表
"""

import sqlite3
import os
from datetime import datetime


class Database:
    """SQLite 数据库管理类"""

    def __init__(self, db_path: str):
        """初始化数据库连接并建表"""
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """初始化所有数据表"""
        sql_list = [
            """
            CREATE TABLE IF NOT EXISTS shops (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT 'pdd',
                process_name TEXT DEFAULT '',
                process_pid INTEGER DEFAULT 0,
                token_hint TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                first_seen TEXT DEFAULT (datetime('now','localtime')),
                last_seen TEXT DEFAULT (datetime('now','localtime'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT DEFAULT '',
                session_id TEXT DEFAULT '',
                buyer_id TEXT DEFAULT '',
                buyer_name TEXT DEFAULT '',
                order_sn TEXT DEFAULT '',
                goods_id TEXT DEFAULT '',
                goods_name TEXT DEFAULT '',
                direction TEXT DEFAULT 'in',
                content TEXT DEFAULT '',
                msg_type TEXT DEFAULT 'text',
                ai_generated INTEGER DEFAULT 0,
                ai_confidence REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT DEFAULT '0',
                category TEXT DEFAULT '通用',
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_settings (
                shop_id TEXT PRIMARY KEY DEFAULT '0',
                provider TEXT DEFAULT 'openai',
                model TEXT DEFAULT 'gpt-4o-mini',
                api_key_enc TEXT DEFAULT '',
                api_url TEXT DEFAULT 'https://api.openai.com/v1',
                auto_send INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.85,
                system_prompt TEXT DEFAULT '你是一名专业的电商客服，请用简洁友好的语气回复买家问题。',
                max_tokens INTEGER DEFAULT 300,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS quick_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT DEFAULT '0',
                category TEXT DEFAULT '通用',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS auto_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT DEFAULT '0',
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'keyword',
                trigger_value TEXT DEFAULT '',
                action_type TEXT NOT NULL DEFAULT 'reply',
                action_config TEXT DEFAULT '{}',
                is_enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """,
        ]
        cursor = self._conn.cursor()
        for sql in sql_list:
            cursor.execute(sql)
        self._conn.commit()

    def execute(self, sql: str, params: tuple = ()):
        """执行 SQL 语句"""
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        self._conn.commit()
        return cursor

    def upsert_shop(self, data: dict):
        """插入或更新店铺信息"""
        sql = """
        INSERT INTO shops (id, name, platform, process_name, process_pid, token_hint, is_active, last_seen)
        VALUES (:id, :name, :platform, :process_name, :process_pid, :token_hint, :is_active, datetime('now','localtime'))
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            platform = excluded.platform,
            process_name = excluded.process_name,
            process_pid = excluded.process_pid,
            token_hint = excluded.token_hint,
            is_active = excluded.is_active,
            last_seen = datetime('now','localtime')
        """
        cursor = self._conn.cursor()
        cursor.execute(sql, data)
        self._conn.commit()

    def get_shops(self, active_only: bool = False) -> list:
        """获取店铺列表"""
        if active_only:
            cursor = self._conn.cursor()
            cursor.execute('SELECT * FROM shops WHERE is_active=1')
        else:
            cursor = self._conn.cursor()
            cursor.execute('SELECT * FROM shops')
        return [dict(row) for row in cursor.fetchall()]

    def save_message(self, data: dict):
        """保存消息记录"""
        sql = """
        INSERT INTO messages (shop_id, session_id, buyer_id, buyer_name, order_sn,
            goods_id, goods_name, direction, content, msg_type, ai_generated, ai_confidence)
        VALUES (:shop_id, :session_id, :buyer_id, :buyer_name, :order_sn,
            :goods_id, :goods_name, :direction, :content, :msg_type, :ai_generated, :ai_confidence)
        """
        cursor = self._conn.cursor()
        cursor.execute(sql, data)
        self._conn.commit()

    def get_messages(self, shop_id: str = None, limit: int = 50) -> list:
        """获取消息记录"""
        cursor = self._conn.cursor()
        if shop_id:
            cursor.execute(
                'SELECT * FROM messages WHERE shop_id=? ORDER BY id DESC LIMIT ?',
                (shop_id, limit)
            )
        else:
            cursor.execute(
                'SELECT * FROM messages ORDER BY id DESC LIMIT ?',
                (limit,)
            )
        return [dict(row) for row in cursor.fetchall()]

    def count_messages_today(self) -> int:
        """统计今日消息数量"""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE date(created_at)=date('now','localtime')"
        )
        return cursor.fetchone()[0]

    def get_ai_settings(self, shop_id: str = '0') -> dict:
        """获取AI配置"""
        cursor = self._conn.cursor()
        cursor.execute('SELECT * FROM ai_settings WHERE shop_id=?', (shop_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            'shop_id': shop_id,
            'provider': 'openai',
            'model': 'gpt-4o-mini',
            'api_key_enc': '',
            'api_url': 'https://api.openai.com/v1',
            'auto_send': 0,
            'confidence': 0.85,
            'system_prompt': '你是一名专业的电商客服，请用简洁友好的语气回复买家问题。',
            'max_tokens': 300,
        }

    def save_ai_settings(self, shop_id: str, data: dict):
        """保存AI配置"""
        data['shop_id'] = shop_id
        sql = """
        INSERT INTO ai_settings (shop_id, provider, model, api_key_enc, api_url,
            auto_send, confidence, system_prompt, max_tokens, updated_at)
        VALUES (:shop_id, :provider, :model, :api_key_enc, :api_url,
            :auto_send, :confidence, :system_prompt, :max_tokens, datetime('now','localtime'))
        ON CONFLICT(shop_id) DO UPDATE SET
            provider = excluded.provider,
            model = excluded.model,
            api_key_enc = excluded.api_key_enc,
            api_url = excluded.api_url,
            auto_send = excluded.auto_send,
            confidence = excluded.confidence,
            system_prompt = excluded.system_prompt,
            max_tokens = excluded.max_tokens,
            updated_at = datetime('now','localtime')
        """
        cursor = self._conn.cursor()
        cursor.execute(sql, data)
        self._conn.commit()

    def get_quick_replies(self, shop_id: str = '0') -> list:
        """获取快捷话术"""
        cursor = self._conn.cursor()
        cursor.execute(
            'SELECT * FROM quick_replies WHERE shop_id=? OR shop_id=\'0\' ORDER BY sort_order',
            (shop_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
