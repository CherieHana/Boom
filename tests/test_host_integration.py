from __future__ import annotations

import json
import pathlib
import time

import pytest

from whalepet import config as cfgmod
from whalepet.host import HostProcess, bundled_payload, resolve_runtime

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _node_available() -> bool:
    try:
        node, _plugin, _host = resolve_runtime()
        return node.exists()
    except Exception:
        return False


requires_node = pytest.mark.skipif(not _node_available(), reason="缺少 node.exe / 插件本体")


@requires_node
def test_host_starts_and_reports_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    host = HostProcess()
    port = host.start(timeout=60)
    try:
        assert port > 0
        status = host.status()
        assert status["ok"] is True
        assert status["routeCount"] >= 20
        paths = "\n".join(status["routes"])
        for expected in ("balance.json", "size.json", "bubble.json", "roles.json", "audio.json", "widget.js"):
            assert expected in paths
        assert any(r.startswith("session/event") for r in status["listeners"])
    finally:
        host.stop()
    assert not host.alive


@requires_node
def test_host_credentials_and_usage_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    host = HostProcess()
    host.start(timeout=60)
    try:
        host.set_credential("DEEPSEEK_API_KEY", "sk-unit-test")
        creds = json.loads((tmp_path / "dsh-home" / "credentials.json").read_text(encoding="utf-8"))
        assert creds["DEEPSEEK_API_KEY"] == "sk-unit-test"

        host.feed_usage(turn=1, model="deepseek-chat", inputTokens=100, cacheReadTokens=0,
                        outputTokens=20, reasoningTokens=0)
        time.sleep(0.4)
        payload = host.get("/dsh-whale/last-turn.json")
        assert payload["ok"] is True
        assert payload["seq"] >= 1
        assert payload["turn"] == 1
        assert payload["tokens"] == 120
        assert payload["amount"] and payload["amount"] > 0
    finally:
        host.stop()


@requires_node
def test_credentials_resolve_returns_object_with_value(tmp_path, monkeypatch):
    """插件读的是 cred.value（真实 DSH 的凭据对象），垫片必须返回对象而不是字符串。"""
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    host = HostProcess()
    host.start(timeout=60)
    try:
        host.set_credential("DEEPSEEK_API_KEY", "sk-object-shape-test")
        models = host.get("/dsh-whale/api-models.json")
        assert models["ok"] is True
        deepseek = next(m for m in models["models"] if m.get("keyRef") == "DEEPSEEK_API_KEY")
        assert deepseek["hasKey"] is True, "credential.resolve() 返回的对象里必须有 value 字段"
    finally:
        host.stop()


@requires_node
def test_host_status_reports_plugin_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    host = HostProcess()
    host.start(timeout=60)
    try:
        status = host.status()
        assert pathlib.Path(status["pluginDir"]).exists()
        assert status["credentialKeys"] == []
    finally:
        host.stop()
