"""WhalePet —— 把 DSH 小鲸鱼挂件（dsh-whale-widget）搬到桌面上的独立程序。

架构：Python/Qt 只做"外壳"（透明覆盖层、托盘、配置、本地中转），
挂件本体是插件自己的 Node 端与浏览器端代码，跑在本机的一个 Node 子进程里。
"""

from __future__ import annotations

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "SHELL_VERSION",
    "PLUGIN_VERSION",
]

APP_NAME = "WhalePet"
APP_VERSION = "1.0.0"
SHELL_VERSION = "1.0.0"
# 随包内置的插件版本（换插件时改这里，构建脚本会用它做运行时缓存戳）
PLUGIN_VERSION = "0.3.0"
