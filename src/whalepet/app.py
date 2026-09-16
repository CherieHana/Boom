"""应用装配：单实例、宿主进程、覆盖层、托盘、本地中转、首次向导。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# QtWebEngine 必须在 QApplication 之前完成导入/配置
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")

from PySide6.QtCore import QLockFile, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon  # noqa: E402

from . import APP_NAME, APP_VERSION, PLUGIN_VERSION  # noqa: E402
from .config import data_root, is_first_run, load_config, log_dir, save_config  # noqa: E402
from .host import HostProcess  # noqa: E402
from .migrate import migrate_if_needed  # noqa: E402
from .overlay import Overlay  # noqa: E402
from .proxy import ProxyServer, port_available  # noqa: E402
from .wizard import SettingsDialog, show_about  # noqa: E402


def _icon(plugin_dir: Path | None) -> QIcon:
    candidates = []
    if plugin_dir:
        candidates += [plugin_dir / "assets" / "DSniang1.png", plugin_dir / "assets" / "DSniang02.png"]
    candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "assets" / "DSniang1.png")
    for path in candidates:
        try:
            if path and path.exists():
                pix = QPixmap(str(path))
                if not pix.isNull():
                    return QIcon(pix)
        except Exception:
            continue
    return QIcon()


def _log(message: str) -> None:
    """极简启动日志：只记版本/路径/端口/错误，绝不记录密钥。"""
    try:
        path = log_dir() / "whalepet.log"
        if path.exists() and path.stat().st_size > 512 * 1024:
            path.replace(path.with_suffix(".log.1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


class WhalePetApp:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.app = QApplication(argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setApplicationVersion(APP_VERSION)
        self.app.setQuitOnLastWindowClosed(False)

        self.lock = QLockFile(str(data_root() / "whalepet.lock"))
        self.lock.setStaleLockTime(0)
        self.single = self.lock.tryLock(100)

        self.cfg: dict[str, Any] = load_config()
        self.host: HostProcess | None = None
        self.overlay: Overlay | None = None
        self.proxy: ProxyServer | None = None
        self.tray: QSystemTrayIcon | None = None
        self.settings_dialog: SettingsDialog | None = None
        self.about_action: QAction | None = None
        self.restarts = 0

    # ------------------------------------------------------------------ 启动
    def run(self) -> int:
        _log(f"启动 v{APP_VERSION}（数据目录 {data_root()}，frozen={getattr(sys, 'frozen', False)}）")
        if not self.single:
            _log("已有实例在运行，退出")
            QMessageBox.information(None, APP_NAME, "小鲸鱼已经在运行了（看看右下角托盘）。")
            return 0

        migrate_if_needed(self.cfg)
        self.cfg = load_config()

        try:
            self.host = HostProcess(log_enabled=bool(self.cfg.get("logging", {}).get("enabled")))
            port = self.host.start()
        except Exception as exc:  # noqa: BLE001
            _log(f"宿主启动失败：{exc}")
            QMessageBox.critical(None, APP_NAME, f"启动内置挂件失败：\n{exc}")
            self.lock.unlock()
            return 2
        _log(f"宿主已就绪，端口 {port}")

        self._push_credentials()
        self._create_overlay(port)
        self._create_tray()
        self._start_proxy()
        self._watchdog()

        if is_first_run(self.cfg):
            QTimer.singleShot(1200, lambda: self.open_settings(first_run=True))

        autoquit = os.environ.get("WHALE_PET_AUTOQUIT")
        if autoquit:
            try:
                QTimer.singleShot(max(1, int(float(autoquit))) * 1000, self.quit)
            except Exception:
                pass

        return self.app.exec()

    # ------------------------------------------------------------------ 组件
    def _push_credentials(self) -> None:
        key = str(self.cfg.get("api_key") or "").strip()
        if key and self.host:
            try:
                self.host.set_credential("DEEPSEEK_API_KEY", key)
            except Exception:
                pass

    def _create_overlay(self, port: int) -> None:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.geometry()
        self.overlay = Overlay(f"http://127.0.0.1:{port}/")
        self.overlay.apply_screen(geometry)
        visible = bool(self.cfg.get("overlay", {}).get("visible", True))
        self.overlay.setVisible(visible)
        if os.environ.get("WHALE_PET_SELFCHECK") == "1":
            self.overlay.page_ready.connect(lambda _ok: QTimer.singleShot(4000, self._selfcheck))

    def _selfcheck(self) -> None:
        """自检模式：确认挂件真的渲染进页面、遮罩算出区域，写日志后退出。"""
        if not self.overlay:
            return

        def done(raw: object) -> None:
            widget = 0
            bubble = 0
            try:
                payload = json.loads(raw) if isinstance(raw, str) and raw else {}
                widget = int(payload.get("widget") or 0)
                bubble = int(payload.get("pop") or 0)
            except Exception:
                pass
            regions = len(self.overlay.regions()) if self.overlay else 0
            _log(f"SELFCHECK widget={widget} regions={regions} pop={bubble}")
            QTimer.singleShot(200, self.quit)

        self.overlay.view.page().runJavaScript(
            "JSON.stringify({widget: document.querySelectorAll('.dshwv-root').length,"
            " pop: document.querySelectorAll('.dshwv-pop').length})",
            0,
            done,
        )

    def _create_tray(self) -> None:
        icon = _icon(self.host.plugin if self.host else None)
        if icon.isNull():
            icon = self.app.style().standardIcon(self.app.style().StandardPixmap.SP_ComputerIcon)
        self._icon = icon
        self.tray = QSystemTrayIcon(icon, self.app)
        self.tray.setToolTip(f"{APP_NAME} {APP_VERSION}")

        menu = QMenu()
        self.toggle_action = menu.addAction("显示/隐藏小鲸鱼")
        self.toggle_action.triggered.connect(self.toggle_overlay)
        settings = menu.addAction("设置（API Key / 中转）")
        settings.triggered.connect(lambda: self.open_settings(False))
        about = menu.addAction("关于 / 版本")
        about.triggered.connect(self.show_about)
        open_data = menu.addAction("打开数据目录")
        open_data.triggered.connect(self.open_data_dir)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self.quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._tray_menu = menu

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_overlay()

    def _start_proxy(self) -> None:
        if not self.cfg.get("proxy_enabled", True):
            return
        host = str(self.cfg.get("proxy_host", "127.0.0.1"))
        port = int(self.cfg.get("proxy_port", 11434))
        if not port_available(host, port):
            self._notify("本地中转端口被占用", f"{host}:{port} 已被占用，本次不启用中转统计。")
            return
        try:
            self.proxy = ProxyServer(
                api_base=str(self.cfg.get("api_base", "https://api.deepseek.com")),
                api_key=str(self.cfg.get("api_key") or ""),
                on_usage=self._on_usage,
                host=host,
                port=port,
            )
            self.proxy.start()
        except Exception as exc:  # noqa: BLE001
            self._notify("本地中转启动失败", str(exc))

    def _on_usage(self, payload: dict[str, Any]) -> None:
        if not self.host:
            return
        try:
            self.host.feed_usage(**payload)
        except Exception:
            pass

    def _watchdog(self) -> None:
        timer = QTimer(self.app)
        timer.setInterval(5000)

        def check() -> None:
            if self.host and not self.host.alive:
                if self.restarts < 5:
                    self.restarts += 1
                    try:
                        port = self.host.start()
                        self._push_credentials()
                        if self.overlay:
                            self.overlay.view.load(f"http://127.0.0.1:{port}/")
                        self._notify(APP_NAME, "内置挂件进程已自动重启。")
                    except Exception:
                        pass
                else:
                    timer.stop()
                    self._notify(APP_NAME, "内置挂件反复异常退出，请查看日志。")

        timer.timeout.connect(check)
        timer.start()
        self.watchdog_timer = timer

    # ------------------------------------------------------------------ 交互
    def toggle_overlay(self) -> None:
        if not self.overlay:
            return
        visible = not self.overlay.isVisible()
        self.overlay.setVisible(visible)
        self.cfg.setdefault("overlay", {})["visible"] = visible
        save_config(self.cfg)

    def open_settings(self, first_run: bool = False) -> None:
        if not self.host:
            return
        dialog = SettingsDialog(self.cfg, first_run=first_run)
        if dialog.exec():
            self.cfg = load_config()
            self._push_credentials()
            if self.overlay:
                self.overlay.view.page().runJavaScript("window.location.reload()")
            # 中转端口/开关可能变了，重启中转
            if self.proxy:
                self.proxy.stop()
                self.proxy = None
            self._start_proxy()

    def show_about(self) -> None:
        show_about(
            None,
            self.cfg,
            self.host.port if self.host else None,
            PLUGIN_VERSION,
        )

    def open_data_dir(self) -> None:
        path = data_root()
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass

    def _notify(self, title: str, message: str) -> None:
        if self.tray:
            self.tray.showMessage(title, message, self._icon, 4000)

    def quit(self) -> None:
        try:
            if self.proxy:
                self.proxy.stop()
        except Exception:
            pass
        try:
            if self.host:
                self.host.stop()
        except Exception:
            pass
        try:
            if self.overlay:
                self.overlay.stop()
                self.overlay.hide()
        except Exception:
            pass
        try:
            self.lock.unlock()
        except Exception:
            pass
        self.app.quit()


def main(argv: list[str] | None = None) -> int:
    return WhalePetApp(list(argv if argv is not None else sys.argv)).run()
