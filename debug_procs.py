# -*- coding: utf-8 -*-
"""
临时诊断脚本：列出所有正在运行的进程名，帮助确认拼多多工作台的真实进程名
"""
import psutil

print("=" * 60)
print("当前所有进程（过滤含 pdd/拼多多/merchant/browser 的）：")
print("=" * 60)

keywords = ['pdd', '拼多多', 'merchant', 'browser', 'pinduoduo', 'jd', 'taobao', 'douyin']

for proc in psutil.process_iter(['pid', 'name', 'exe']):
    try:
        name = proc.info['name'] or ''
        pid = proc.info['pid']
        exe = proc.info['exe'] or ''
        name_lower = name.lower()
        exe_lower = exe.lower()
        if any(kw in name_lower or kw in exe_lower for kw in keywords):
            print(f"PID={{pid:6d}}  name={{name!r:50s}}  exe={{exe}}")
    except Exception as e:
        pass

print("=" * 60)
print("完成，请把上面的输出截图或复制给我")