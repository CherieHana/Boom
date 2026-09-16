"""验证桌面版面板观感：打开挂件菜单，截图并读取面板的实际背景色。

用法（源码态）：.venv\\Scripts\\python.exe scripts\\verify_menu_look.py
产出：build/menu-look.png、build/menu-look-report.json
"""

from __future__ import annotations

import ctypes
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")


def start_host() -> tuple[subprocess.Popen, int]:
    env = dict(os.environ)
    env.update(WHALE_PET_ROOT=str(ROOT), WHALE_PET_DATA=str(BUILD / "menu-data"), WHALE_PET_PORT="0")
    proc = subprocess.Popen(
        [str(ROOT / "runtime" / "node" / "node.exe"), str(ROOT / "host" / "host.mjs")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        match = re.search(r"WHALE_HOST_READY (\{.*\})", proc.stdout.readline() or "")
        if match:
            return proc, int(json.loads(match.group(1))["port"])
    raise SystemExit("host 启动超时")


def main() -> int:
    from PySide6.QtCore import QTimer, QUrl, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QWidget

    host, port = start_host()
    report: dict = {}
    app = QApplication(sys.argv)
    screen = QGuiApplication.primaryScreen()
    geo = screen.geometry()
    dpr = screen.devicePixelRatio()

    window = QWidget()
    window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    window.setGeometry(geo)
    view = QWebEngineView(window)
    view.setGeometry(0, 0, geo.width(), geo.height())
    view.setAttribute(Qt.WA_TranslucentBackground, True)
    view.page().setBackgroundColor(Qt.transparent)
    window.show()
    view.load(QUrl(f"http://127.0.0.1:{port}/"))

    def click_menu_button() -> None:
        view.page().runJavaScript(
            "(() => { const b = document.querySelector('.dshwv-menu-btn'); if (!b) return '';"
            " const r = b.getBoundingClientRect();"
            " return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)}); })()",
            0,
            do_click,
        )

    def do_click(raw: object) -> None:
        pos = json.loads(raw) if isinstance(raw, str) and raw else None
        if not pos:
            report["error"] = "找不到菜单按钮"
            finish()
            return
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(pos["x"] * dpr), int(pos["y"] * dpr))
        time.sleep(0.3)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.06)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        QTimer.singleShot(1200, inspect)

    def inspect() -> None:
        view.page().runJavaScript(
            "(() => { const m = document.querySelector('.dshwv-menu');"
            " const s = m ? getComputedStyle(m) : null;"
            " const mask = document.querySelector('.dshwv-bubmask, .dshwv-resmask, .dshwv-usage-mask');"
            " const ms = mask ? getComputedStyle(mask) : null;"
            " return JSON.stringify({menuOpen: !!(m && m.className.indexOf('open') >= 0),"
            " menuBg: s ? s.backgroundColor : null, maskBg: ms ? ms.backgroundColor : null}); })()",
            0,
            lambda raw: after_inspect(json.loads(raw) if isinstance(raw, str) and raw else {}),
        )

    def after_inspect(data: dict) -> None:
        report.update(data)
        screen.grabWindow(0).save(str(BUILD / "menu-look.png"))
        finish()

    def finish() -> None:
        report["ok"] = report.get("menuBg") == "rgb(255, 255, 255)"
        (BUILD / "menu-look-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
        print("菜单面板不透明：" + ("是 [OK]" if report["ok"] else "否 [FAIL]"))
        app.quit()

    QTimer.singleShot(4000, click_menu_button)
    QTimer.singleShot(20000, finish)
    app.exec()
    window.hide()
    host.terminate()
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
