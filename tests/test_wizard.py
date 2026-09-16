from __future__ import annotations

import os

import pytest

from whalepet import config as cfgmod


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


def test_settings_dialog_result_config(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    from whalepet.wizard import SettingsDialog

    cfg = cfgmod.load_config()
    dialog = SettingsDialog(cfg, first_run=True)
    dialog.api_key.setText("  sk-test-key  ")
    dialog.api_base.setText("https://api.deepseek.com/")
    dialog.proxy_enabled.setChecked(False)
    dialog.proxy_port.setValue(18888)

    result = dialog.result_config()
    assert result["api_key"] == "sk-test-key"
    assert result["api_base"] == "https://api.deepseek.com"
    assert result["proxy_enabled"] is False
    assert result["proxy_port"] == 18888
    dialog.deleteLater()


def test_settings_dialog_accept_requires_key(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("WHALE_PET_DATA", str(tmp_path))
    from whalepet.wizard import SettingsDialog

    dialog = SettingsDialog(cfgmod.load_config(), first_run=True)
    dialog.api_key.setText("")
    seen: list[str] = []
    monkeypatch.setattr("whalepet.wizard.QMessageBox.warning", lambda *a, **k: seen.append("warn"))
    dialog.accept()
    assert seen == ["warn"]
    assert dialog.result() == 0
    dialog.deleteLater()
