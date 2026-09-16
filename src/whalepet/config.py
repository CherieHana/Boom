"""配置与数据目录。

数据目录优先级：
  1. 环境变量 WHALE_PET_DATA（调试/测试用）
  2. 便携模式：exe/脚本同目录存在 portable.flag 或 config.json → 同级 WhalePetData/
  3. %APPDATA%/WhalePet（默认）

配置文件是 <数据目录>/config.json，兼容旧版桌宠的同名字段，只增不删。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import APP_NAME, APP_VERSION, PLUGIN_VERSION

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "app_version": APP_VERSION,
    "plugin_version": PLUGIN_VERSION,
    "first_run_done": False,
    "api_key": "",
    "api_base": "https://api.deepseek.com",
    "proxy_enabled": True,
    "proxy_host": "127.0.0.1",
    "proxy_port": 11434,
    "scale": 0.8,
    "sound": True,
    "sound_set": "duck",
    "volume": 0.9,
    "bubble_on": True,
    "turn_cost_on": True,
    "turn_cost_close_ms": 5000,
    "peak_mode": "liangwen",
    "usage_mode": "ledger",
    "alert_balance_on": True,
    "alert_balance": 5.0,
    "alert_daily_on": True,
    "alert_daily": 10.0,
    "overlay": {"visible": True},
    "migration": {},
    "logging": {"enabled": False},
}


def app_root() -> Path:
    """程序所在目录：打包后是 exe 目录，源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def is_portable() -> bool:
    root = app_root()
    return (root / "portable.flag").exists() or (root / "config.json").exists()


def data_root() -> Path:
    override = os.environ.get("WHALE_PET_DATA")
    if override:
        path = Path(override).expanduser().resolve()
    elif is_portable():
        path = app_root() / "WhalePetData"
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_root() / "config.json"


def dsh_home() -> Path:
    path = data_root() / "dsh-home"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    path = data_root() / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def webengine_dir() -> Path:
    path = data_root() / "webengine"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    raw: dict[str, Any] = {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except FileNotFoundError:
        raw = {}
    except Exception:
        raw = {}
    return deep_merge(DEFAULTS, raw)


def save_config(cfg: dict[str, Any], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = deep_merge(DEFAULTS, cfg)
    payload["app_version"] = APP_VERSION
    payload["plugin_version"] = PLUGIN_VERSION
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def is_first_run(cfg: dict[str, Any]) -> bool:
    return not cfg.get("first_run_done") or not cfg.get("api_key")
