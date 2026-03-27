# -*- coding: utf-8 -*-
"""
日志模块
日志文件: ~/.aikf/logs/aikf_YYYYMMDD.log
按天轮转，保留7天
同时输出到控制台（DEBUG）和文件（INFO）
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

import config

_loggers: dict = {}


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 Logger，全局单例"""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 格式
    fmt = logging.Formatter(
        fmt='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器（DEBUG 级别）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(fmt)

    # 文件处理器（INFO 级别，按天轮转，保留7天）
    log_dir = config.get_log_dir()
    today = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(log_dir, f'aikf_{today}.log')

    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger
