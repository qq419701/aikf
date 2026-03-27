# AIKF 客服助手

> 版本: 3.0.0 | Build: 20260327

全新拼多多/京东客服自动化工具，纯客户端，不依赖服务端。

## 功能特性

- 🔍 **进程监控**：自动检测拼多多/京东/淘宝/抖音/快手商家客服软件进程，采集网络连接、数据目录、窗口标题等详细信息
- 🤖 **AI 自动回复**（即将上线）：支持 GPT/Qwen/DeepSeek/本地 Ollama
- 📚 **快捷话术**（即将上线）：话术库管理、变量模板、批量导入
- ⚡ **自动化规则**（即将上线）：关键词触发、订单状态联动
- 🎮 **U号租**（即将上线）：API 直连，无需浏览器
- 📊 **数据统计**（即将上线）：消息量、AI 命中率、响应时间分析

## 技术栈

| 模块 | 技术 |
|------|------|
| UI 框架 | PyQt6 + pyqt6-fluent-widgets |
| 异步 | asyncio + qasync |
| 进程监控 | psutil |
| 数据库 | sqlite3（内置） |
| 加密 | pycryptodome AES-256-CBC |
| HTTP | requests + aiohttp |
| 打包 | PyInstaller |

## 安装与运行

```bash
pip install -r requirements.txt
python app.py
```

## 项目结构

```
aikf/
├── app.py               # 入口
├── version.py           # 版本信息
├── config.py            # 本地配置管理（AES-256-CBC 加密）
├── requirements.txt
├── core/
│   ├── logger.py        # 日志模块（按天轮转）
│   ├── db.py            # SQLite 数据库
│   ├── updater.py       # 自动更新检查
│   ├── process_watcher.py  # 进程监控（核心）
│   └── notify.py        # 系统托盘通知
├── ui/
│   ├── login_window.py  # 激活/登录窗口
│   ├── main_window.py   # 主窗口（FluentWindow）
│   └── pages/           # 各功能页面
└── models/
    └── shop.py          # 店铺数据模型
```

## 支持平台

| 进程名 | 平台 |
|--------|------|
| pddmerchant.exe / pdd_merchant.exe | 拼多多 |
| jd_merchant.exe / jdmerchant.exe | 京东 |
| AliWorkbench.exe / qianniu.exe | 淘宝/千牛 |
| DouyinMerchant.exe | 抖音 |
| kwai_merchant.exe | 快手 |

## GitHub

[qq419701/aikf](https://github.com/qq419701/aikf)