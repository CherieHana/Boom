"""把旧版 Qt 桌宠（pet 包）的数据迁到新版：配置、账本、密钥、插件状态。

原则：只增不删。原文件先备份成 *.pre-v030.bak，再写插件自己的状态文件。
同一个迁移只跑一次（config.migration.done），失败也不会让程序起不来。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import data_root, dsh_home, load_config, save_config

BACKUP_SUFFIX = ".pre-v030.bak"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _backup(path: Path) -> str | None:
    if not path.exists():
        return None
    target = path.with_name(path.name + BACKUP_SUFFIX)
    if not target.exists():
        shutil.copy2(path, target)
    return str(target)


def _history_to_plugin(old: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    raw = old.get("history")
    if isinstance(raw, dict):
        for day, value in raw.items():
            if isinstance(value, dict):
                usage = value.get("usage")
                if isinstance(usage, (int, float)):
                    out[str(day)] = round(float(usage), 2)
            elif isinstance(value, (int, float)):
                out[str(day)] = round(float(value), 2)
    return out


def write_plugin_state(cfg: dict[str, Any]) -> dict[str, str]:
    """把外壳配置同步成插件自己的状态文件（.dshw-size.json / .dshw-usage.json）。"""
    home = dsh_home()
    written: dict[str, str] = {}

    size = {
        "scale": cfg.get("scale", 0.8),
        "sound": bool(cfg.get("sound", True)),
        "vol": cfg.get("volume", 0.9),
        "soundSet": cfg.get("sound_set", "duck"),
        "usageMode": cfg.get("usage_mode", "ledger"),
        "peakMode": cfg.get("peak_mode", "liangwen"),
        "bubbleOn": bool(cfg.get("bubble_on", True)),
        "turnCostOn": bool(cfg.get("turn_cost_on", True)),
        "turnCostCloseMs": int(cfg.get("turn_cost_close_ms", 5000) or 0),
        "scrollGapOn": False,
        "scrollGapPx": 0,
        "menuBtnHide": False,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    size_path = home / ".dshw-size.json"
    _write_json(size_path, size)
    written["size"] = str(size_path)
    return written


def migrate_if_needed(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回迁移结果；已经迁过就直接返回 config 里的记录。"""
    cfg = cfg or load_config()
    record = cfg.get("migration") or {}
    if record.get("done"):
        return record

    root = data_root()
    old_config = root / "config.json"
    old_ledger = root / "ledger.json"
    old_phrases = root / "phrases.json"

    backups: list[str] = []
    result: dict[str, Any] = {
        "done": True,
        "at": datetime.now().isoformat(timespec="seconds"),
        "source": "pet-qt",
        "backups": backups,
    }

    # 1) 备份旧文件
    for path in (old_config, old_ledger, old_phrases):
        backup = _backup(path)
        if backup:
            backups.append(backup)

    # 2) 旧配置里的键并进新配置（旧键名与新键名一致，直接合并）
    if old_config.exists():
        legacy = _read_json(old_config)
        for key in (
            "api_key",
            "api_base",
            "proxy_enabled",
            "proxy_host",
            "proxy_port",
            "scale",
            "volume",
            "sound_set",
            "bubble_on",
            "turn_cost_on",
            "turn_cost_close_ms",
            "peak_mode",
            "usage_mode",
            "alert_balance_on",
            "alert_balance",
            "alert_daily_on",
            "alert_daily",
        ):
            if key in legacy and legacy[key] not in (None, ""):
                cfg[key] = legacy[key]

    # 3) 账本：旧 history 是 {day: {usage, models}} → 插件要 {day: number}
    ledger = _read_json(old_ledger)
    if ledger:
        usage = {
            "date": str(ledger.get("date") or datetime.now().strftime("%Y-%m-%d")),
            "dayStart": ledger.get("dayStart"),
            "lastBalance": ledger.get("lastBalance"),
            "todayUsage": round(float(ledger.get("todayUsage") or 0), 2),
            "history": _history_to_plugin(ledger),
            "events": [],
            "migratedFrom": "pet-qt",
        }
        usage_path = dsh_home() / ".dshw-usage.json"
        if not usage_path.exists():
            _write_json(usage_path, usage)
            result["ledger"] = str(usage_path)
            result["historyDays"] = len(usage["history"])

    # 4) 插件状态文件（缩放/音效/开关）
    result["state"] = write_plugin_state(cfg)

    # 5) 自定义台词文件保留原样，只做备份记录；新版泡泡系统自带编辑器
    if old_phrases.exists():
        result["phrases"] = str(old_phrases)

    cfg["migration"] = result
    cfg["first_run_done"] = bool(cfg.get("api_key")) and bool(cfg.get("first_run_done"))
    save_config(cfg)
    return result
