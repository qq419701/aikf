# -*- coding: utf-8 -*-
# 在 QApplication 创建前设置 DPI
import os
import sys

os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from qfluentwidgets import setTheme, Theme
import asyncio
import qasync

import config
from core.logger import get_logger
from core.db import Database


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName('AIKF 客服助手')
    setTheme(Theme.LIGHT)

    db = Database(config.get_db_path())
    logger = get_logger('app')
    logger.info('AIKF 启动, 版本 3.0.0')

    if config.is_activated():
        from ui.main_window import MainWindow
        w = MainWindow(db=db)
        w.show()
    else:
        from ui.login_window import LoginWindow
        login = LoginWindow()

        def on_activated():
            login.close()
            from ui.main_window import MainWindow
            w = MainWindow(db=db)
            w.show()

        login.activated.connect(on_activated)
        login.show()

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        loop.run_forever()


if __name__ == '__main__':
    main()
