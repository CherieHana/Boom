"""首次运行向导 / 设置对话框（Qt 原生，不依赖插件面板）。"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .config import save_config
from .proxy import port_available


class SettingsDialog(QDialog):
    """填 API Key、选中转开关与端口；顺带能自检连通性。"""

    def __init__(self, cfg: dict[str, Any], first_run: bool = False, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.setWindowTitle("小鲸鱼设置" + ("（首次启动）" if first_run else ""))
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        form = QFormLayout()
        self.api_key = QLineEdit(str(self.cfg.get("api_key", "")))
        self.api_key.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.api_key.setPlaceholderText("sk-...（只保存在本机，不会上传）")
        form.addRow("DeepSeek API Key", self.api_key)

        self.api_base = QLineEdit(str(self.cfg.get("api_base", "https://api.deepseek.com")))
        form.addRow("接口地址", self.api_base)

        self.proxy_enabled = QCheckBox("启用本地中转（统计每轮消耗 / 模型明细）")
        self.proxy_enabled.setChecked(bool(self.cfg.get("proxy_enabled", True)))
        form.addRow("", self.proxy_enabled)

        row = QHBoxLayout()
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1024, 65535)
        self.proxy_port.setValue(int(self.cfg.get("proxy_port", 11434)))
        row.addWidget(QLabel("http://127.0.0.1:"))
        row.addWidget(self.proxy_port)
        row.addWidget(QLabel("/v1"))
        row.addStretch(1)
        form.addRow("中转端口", row)

        self.test_btn = QPushButton("测试连通性")
        self.test_btn.clicked.connect(self._test)
        form.addRow("", self.test_btn)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        form.addRow("", self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        tip = QLabel(
            "小鲸鱼本体是 DSH 挂件插件，功能与插件完全一致。\n"
            "这里的设置只影响启动参数与本机中转，其余（角色/音效/泡泡/记账）都在挂件菜单里改。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addLayout(form)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ 自检
    def _test(self) -> None:
        key = self.api_key.text().strip()
        if not key:
            self.status.setText("请先填 API Key。")
            return
        base = self.api_base.text().strip().rstrip("/") or "https://api.deepseek.com"
        url = base + "/user/balance"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            infos = payload.get("balance_infos") or []
            if infos:
                info = infos[0]
                self.status.setText(
                    f"连接成功：余额 {info.get('total_balance')} {info.get('currency', '')}"
                )
            else:
                self.status.setText(f"连接成功：{json.dumps(payload, ensure_ascii=False)[:160]}")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"连接失败：{exc}")

    # ------------------------------------------------------------------ 结果
    def result_config(self) -> dict[str, Any]:
        cfg = dict(self.cfg)
        cfg["api_key"] = self.api_key.text().strip()
        cfg["api_base"] = self.api_base.text().strip().rstrip("/") or "https://api.deepseek.com"
        cfg["proxy_enabled"] = bool(self.proxy_enabled.isChecked())
        cfg["proxy_port"] = int(self.proxy_port.value())
        return cfg

    def accept(self) -> None:  # noqa: D102
        cfg = self.result_config()
        if not cfg["api_key"]:
            QMessageBox.warning(self, "缺少 API Key", "没有 API Key 时余额会显示为空，先填一个吧。")
            return
        port = int(cfg["proxy_port"])
        host = str(cfg.get("proxy_host", "127.0.0.1"))
        if cfg["proxy_enabled"] and not port_available(host, port):
            QMessageBox.warning(
                self,
                "端口被占用",
                f"{host}:{port} 已被占用（旧版小鲸鱼或其它程序？）。\n换一个端口，或先关掉占用它的程序。",
            )
            return
        cfg["first_run_done"] = True
        save_config(cfg)
        self.cfg = cfg
        super().accept()


def show_about(parent, cfg: dict[str, Any], host_port: int | None, plugin_version: str) -> None:
    from . import APP_VERSION
    from .config import data_root

    QMessageBox.information(
        parent,
        "关于小鲸鱼",
        f"WhalePet 外壳版本：{APP_VERSION}\n"
        f"内置挂件插件：dsh-whale-widget {plugin_version}\n"
        f"数据目录：{data_root()}\n"
        f"宿主端口：{host_port or '-'}\n\n"
        "挂件本体来自开源项目 MeteorNOX/DeepSeek-Balance-Whale-Widget（MIT）。\n"
        "所有数据都保存在本机，余额查询只走你自己填的接口。",
    )
