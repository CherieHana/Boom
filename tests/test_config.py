from __future__ import annotations

import json
import pathlib

import pytest

from whalepet import config as cfgmod


def test_data_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path / "data"))
    root = cfgmod.data_root()
    assert root == (tmp_path / "data").resolve()
    assert root.exists()


def test_portable_mode_uses_folder_next_to_program(tmp_path, monkeypatch):
    monkeypatch.delenv("WHALE_PET_DATA", raising=False)
    (tmp_path / "portable.flag").write_text("", encoding="utf-8")
    monkeypatch.setattr(cfgmod, "app_root", lambda: tmp_path)
    assert cfgmod.is_portable() is True
    assert cfgmod.data_root() == tmp_path / "WhalePetData"


def test_roaming_mode_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("WHALE_PET_DATA", raising=False)
    monkeypatch.setattr(cfgmod, "app_root", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert cfgmod.is_portable() is False
    assert cfgmod.data_root() == tmp_path / "roaming" / "WhalePet"


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    cfgmod.save_config({"api_key": "sk-x", "proxy_port": 1234, "overlay": {"visible": False}})
    loaded = cfgmod.load_config()
    assert loaded["api_key"] == "sk-x"
    assert loaded["proxy_port"] == 1234
    assert loaded["overlay"]["visible"] is False
    # 默认值补全，未知键保留
    assert loaded["scale"] == cfgmod.DEFAULTS["scale"]
    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert payload["app_version"] == cfgmod.APP_VERSION


def test_deep_merge_keeps_nested_defaults():
    merged = cfgmod.deep_merge({"a": 1, "n": {"x": 1, "y": 2}}, {"n": {"y": 9}})
    assert merged == {"a": 1, "n": {"x": 1, "y": 9}}


def test_first_run_detection():
    assert cfgmod.is_first_run({"first_run_done": False, "api_key": "sk"}) is True
    assert cfgmod.is_first_run({"first_run_done": True, "api_key": ""}) is True
    assert cfgmod.is_first_run({"first_run_done": True, "api_key": "sk"}) is False
