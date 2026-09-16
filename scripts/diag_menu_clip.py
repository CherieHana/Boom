"""复现"鲸鱼调小后菜单边框显示不全"：按指定 scale 打开菜单，量面板与遮罩的真实尺寸。

用法：.venv\\Scripts\\python.exe scripts\\diag_menu_clip.py [scale]
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
SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.6

sys.path.insert(0, str(ROOT / "src"))
from whalepet.overlay import REGION_JS  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")


def start_host(data_dir: pathlib.Path) -> tuple[subprocess.Popen, int]:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "dsh-home").mkdir(parents=True, exist_ok=True)
    (data_dir / "dsh-home" / ".dshw-size.json").write_text(
        json.dumps({"scale": SCALE, "sound": True, "vol": 0.9, "soundSet": "duck",
                    "usageMode": "ledger", "peakMode": "default", "bubbleOn": True,
                    "turnCostOn": True, "turnCostCloseMs": 5000}),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(WHALE_PET_ROOT=str(ROOT), WHALE_PET_DATA=str(data_dir), WHALE_PET_PORT="0")
    proc = subprocess.Popen(
        [str(ROOT / "runtime" / "node" / "node.exe"), str(ROOT / "host" / "host.mjs")],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        match = re.search(r"WHALE_HOST_READY (\{.*\})", proc.stdout.readline() or "")
        if match:
            return proc, int(json.loads(match.group(1))["port"])
    raise SystemExit("host 启动超时")


def main() -> int:
    from PySide6.QtCore import QTimer, QUrl, Qt
    from PySide6.QtGui import QGuiApplication, QRegion
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QWidget

    host, port = start_host(BUILD / f"menu-scale-{SCALE}")
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

    report: dict = {"scale": SCALE, "screen": [geo.width(), geo.height()], "dpr": dpr}

    def apply_mask(raw: object) -> None:
        try:
            regions = json.loads(raw) if isinstance(raw, str) and raw else []
        except Exception:
            regions = []
        report["regions"] = regions
        mask = QRegion()
        for left, top, right, bottom in regions:
            mask = mask.united(QRegion(left, top, right - left, bottom - top))
        if not mask.isEmpty():
            window.setMask(mask)

    def poll() -> None:
        # 直接用产品里的区域逻辑，保证诊断与实现一致
        view.page().runJavaScript(REGION_JS, 0, apply_mask)

    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(poll)
    view.loadFinished.connect(lambda ok: timer.start())

    def open_menu() -> None:
        view.page().runJavaScript(
            "(() => { const b = document.querySelector('.dshwv-menu-btn'); if (!b) return '';"
            " const r = b.getBoundingClientRect();"
            " return JSON.stringify({x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)}); })()",
            0, click, 
        )

    def click(raw: object) -> None:
        pos = json.loads(raw) if isinstance(raw, str) and raw else None
        if not pos:
            report["error"] = "no menu button"
            dump()
            return
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(pos["x"] * dpr), int(pos["y"] * dpr))
        time.sleep(0.3)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.08)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        QTimer.singleShot(1500, measure)

    def measure() -> None:
        view.page().runJavaScript(
            r"""(() => {
                const root = document.querySelector('.dshwv-root');
                const menu = document.querySelector('.dshwv-menu');
                const view2 = document.querySelector('.dshwv-menuview');
                const pick = (el) => el ? (() => { const b = el.getBoundingClientRect(); const s = getComputedStyle(el);
                    return {rect: [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)],
                            clientW: el.clientWidth, scrollW: el.scrollWidth,
                            fontSize: s.fontSize, transform: s.transform, overflow: s.overflow,
                            cls: String(el.className)}; })() : null;
                return JSON.stringify({root: pick(root), menu: pick(menu), menuview: pick(view2),
                    rootCssScale: root ? getComputedStyle(root).getPropertyValue('--dshw-scale').trim() : null,
                    rootFont: root ? getComputedStyle(root).fontSize : null,
                    bodyFont: getComputedStyle(document.body).fontSize});
            })()""",
            0, lambda raw: after_measure(json.loads(raw) if isinstance(raw, str) and raw else {}),
        )

    def after_measure(data: dict) -> None:
        report.update(data)
        screen.grabWindow(0).save(str(BUILD / f"menu-scale-{SCALE}.png"))
        dump()

    def dump() -> None:
        (BUILD / "diag-menu-clip.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False)[:1200])
        app.quit()

    QTimer.singleShot(4000, open_menu)
    QTimer.singleShot(20000, dump)
    app.exec()
    timer.stop()
    window.hide()
    host.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
