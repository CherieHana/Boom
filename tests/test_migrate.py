from __future__ import annotations

import json

from whalepet import config as cfgmod
from whalepet.migrate import BACKUP_SUFFIX, migrate_if_needed


def _prepare(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "api_key": "sk-legacy",
                "proxy_enabled": True,
                "proxy_port": 11434,
                "scale": 0.8,
                "volume": 0.9,
                "sound_set": "duck",
                "peak_mode": "liangwen",
                "usage_mode": "ledger",
                "alert_balance": 5,
                "first_run_done": True,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "ledger.json").write_text(
        json.dumps(
            {
                "date": "2026-09-16",
                "dayStart": 13.61,
                "lastBalance": 10.03,
                "todayUsage": 3.58,
                "history": {
                    "2026-09-11": {"usage": 0.09, "models": {}},
                    "2026-09-12": {"usage": 3.23, "models": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "phrases.json").write_text(json.dumps({"version": 1, "groups": []}), encoding="utf-8")


def test_migration_creates_backups_and_plugin_state(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    cfg = cfgmod.load_config()
    result = migrate_if_needed(cfg)

    assert result["done"] is True
    assert (tmp_path / ("config.json" + BACKUP_SUFFIX)).exists()
    assert (tmp_path / ("ledger.json" + BACKUP_SUFFIX)).exists()
    assert (tmp_path / ("phrases.json" + BACKUP_SUFFIX)).exists()

    size = json.loads((tmp_path / "dsh-home" / ".dshw-size.json").read_text(encoding="utf-8"))
    assert size["scale"] == 0.8
    assert size["soundSet"] == "duck"
    assert size["usageMode"] == "ledger"
    assert size["bubbleOn"] is True

    usage = json.loads((tmp_path / "dsh-home" / ".dshw-usage.json").read_text(encoding="utf-8"))
    assert usage["dayStart"] == 13.61
    assert usage["history"]["2026-09-12"] == 3.23
    assert usage["history"]["2026-09-11"] == 0.09

    cfg_after = cfgmod.load_config()
    assert cfg_after["api_key"] == "sk-legacy"
    assert cfg_after["migration"]["done"] is True


def test_migration_is_idempotent(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    first = migrate_if_needed(cfgmod.load_config())
    # 再动一次旧账本，然后重跑迁移：不应该覆盖已经迁好的插件账本
    (tmp_path / "dsh-home" / ".dshw-usage.json").write_text(
        json.dumps({"date": "2026-09-17", "history": {"2026-09-17": 1.0}}), encoding="utf-8"
    )
    second = migrate_if_needed(cfgmod.load_config())
    assert second["at"] == first["at"]
    usage = json.loads((tmp_path / "dsh-home" / ".dshw-usage.json").read_text(encoding="utf-8"))
    assert usage["date"] == "2026-09-17"
