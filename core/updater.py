# -*- coding: utf-8 -*-
"""
自动更新检查模块
通过 GitHub Releases API 检查最新版本
"""

import requests
from PyQt6.QtCore import QThread, QObject, pyqtSignal

from version import APP_VERSION, UPDATE_CHECK_URL


def _version_tuple(v: str) -> tuple:
    """将版本字符串转换为元组，用于比较"""
    v = v.lstrip('v')
    try:
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0,)


class UpdateChecker(QThread):
    """版本检查线程"""
    update_found = pyqtSignal(dict)   # {'version', 'url', 'body'}
    no_update = pyqtSignal()
    check_error = pyqtSignal(str)

    def run(self):
        """执行版本检查"""
        try:
            resp = requests.get(UPDATE_CHECK_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            tag = data.get('tag_name', '')
            latest = _version_tuple(tag)
            current = _version_tuple(APP_VERSION)
            if latest > current:
                self.update_found.emit({
                    'version': tag,
                    'url': data.get('html_url', ''),
                    'body': data.get('body', ''),
                })
            else:
                self.no_update.emit()
        except Exception as e:
            self.check_error.emit(str(e))


class Updater(QObject):
    """更新检查管理器"""
    update_found = pyqtSignal(dict)
    no_update = pyqtSignal()
    check_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checker: UpdateChecker = None

    def check(self):
        """启动版本检查线程"""
        self._checker = UpdateChecker()
        self._checker.update_found.connect(self.update_found)
        self._checker.no_update.connect(self.no_update)
        self._checker.check_error.connect(self.check_error)
        self._checker.start()
