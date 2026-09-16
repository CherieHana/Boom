"""阶段 0b 验证：透明覆盖层 + 区域遮罩（点鲸鱼有反应、点别处穿透到桌面）。

用法（项目根目录）：.venv\\Scripts\\python.exe scripts\\spike_overlay.py
产出：build/spike-overlay-*.png、build/spike-overlay-report.json
"""

from __future__ import annotations

import ctypes
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 任务结束音是轮询触发的，默认自动播放策略会拦掉，必须放开
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")

REGION_JS = r"""
(() => {
  const out = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  const root = document.querySelector('.dshwv-root');
  if (!root) return JSON.stringify(out);
  // 角色本体：固定推入（鲸鱼图自身是 pointer-events:none，靠外层容器接事件）
  const rr = root.getBoundingClientRect();
  if (rr.width >= 4 && rr.height >= 4) out.push([rr.left, rr.top, rr.right, rr.bottom]);
  // 面板/泡泡：用命中测试判断"真的可见且能点到"，避免把 display:none 祖先下的子元素也算进来
  const cand = new Set(document.querySelectorAll('.dshwv-pop.dshwv-pop-open'));
  for (const el of document.querySelectorAll('[class*="dshwv-mask"],[class*="dshwv-menuview"],[class*="dshwv-panel"],[class*="dshwv-dialog"],[class*="dshwv-usage"],[class*="dshwv-bubmask"]')) cand.add(el);
  for (const el of cand) {
    const b = el.getBoundingClientRect();
    if (b.width < 6 || b.height < 6) continue;
    const pts = [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]];
    let hit = false;
    for (const [fx, fy] of pts) {
      const x = b.left + b.width * fx, y = b.top + b.height * fy;
      if (x < 0 || y < 0 || x > vw || y > vh) continue;
      const t = document.elementFromPoint(x, y);
      if (t && (t === el || el.contains(t))) { hit = true; break; }
    }
    if (hit) out.push([b.left, b.top, b.right, b.bottom]);
  }
  return JSON.stringify(out.map((a) => a.map(Math.round)));
})()
"""


def find_node() -> pathlib.Path:
    """找 node：优先仓库自带的运行时，其次 PATH，最后 Codex 自带的运行时。"""
    on_path = shutil.which("node")
    candidates = [
        ROOT / "runtime" / "node" / "node.exe",
        pathlib.Path(on_path) if on_path else None,
        pathlib.Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe",
    ]
    for path in candidates:
        if path and path.exists():
            return path
    raise SystemExit("找不到 node.exe：先跑 scripts\\fetch_node.ps1，或把 node 加进 PATH")


def start_host() -> tuple[subprocess.Popen, int]:
    env = dict(os.environ)
    env["WHALE_PET_ROOT"] = str(ROOT)
    env["WHALE_PET_DATA"] = str(BUILD / "data")
    env["WHALE_PET_PORT"] = "0"
    proc = subprocess.Popen(
        [str(find_node()), str(ROOT / "host" / "host.mjs")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=open(BUILD / "spike-host.err.log", "w", encoding="utf-8"),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise SystemExit("host 启动失败：" + proc.stderr.read())
            continue
        match = re.search(r"WHALE_HOST_READY (\{.*\})", line)
        if match:
            return proc, int(json.loads(match.group(1))["port"])
    proc.kill()
    raise SystemExit("host 启动超时")


def step(report: dict, name: str, ok: bool, detail: str = "") -> None:
    report["steps"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(("  [OK] " if ok else "  [!!] ") + name + (f" —— {detail}" if detail else ""))


def real_click(x: int, y: int) -> None:
    """真实鼠标事件，用来验证遮罩确实把点击送进了窗口。"""
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def main() -> int:
    from PySide6.QtCore import QTimer, QUrl, Qt
    from PySide6.QtGui import QGuiApplication, QRegion
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QWidget

    host, port = start_host()
    report: dict = {"url": f"http://127.0.0.1:{port}/", "steps": [], "regions": []}

    app = QApplication(sys.argv)
    screen = QGuiApplication.primaryScreen()
    geo = screen.geometry()
    report["screen"] = {
        "width": geo.width(),
        "height": geo.height(),
        "dpr": screen.devicePixelRatio(),
    }

    window = QWidget()
    window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    window.setAttribute(Qt.WA_NoSystemBackground, True)
    window.setGeometry(geo)

    view = QWebEngineView(window)
    view.setGeometry(0, 0, geo.width(), geo.height())
    view.setAttribute(Qt.WA_TranslucentBackground, True)
    view.page().setBackgroundColor(Qt.transparent)
    view.setContextMenuPolicy(Qt.NoContextMenu)
    window.show()

    state: dict = {"regions": None, "mask": None, "loaded": False, "whale": None}

    def apply_regions(raw: object) -> None:
        # QtWebEngine 回传 JS 对象不可靠（会变成空字符串），统一走 JSON 字符串
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw else []
        except Exception:
            parsed = []
        regions = [tuple(int(v) for v in r) for r in parsed if isinstance(r, list)]
        if regions == state["regions"]:
            return
        state["regions"] = regions
        mask = QRegion()
        for left, top, right, bottom in regions:
            mask = mask.united(QRegion(left, top, right - left, bottom - top))
        state["mask"] = mask
        window.setMask(mask)
        report["regions"] = [list(r) for r in regions]

    def poll_regions() -> None:
        if state["loaded"]:
            view.page().runJavaScript(REGION_JS, 0, apply_regions)

    timer = QTimer()
    timer.setInterval(150)
    timer.timeout.connect(poll_regions)

    def after_load(ok: bool) -> None:
        state["loaded"] = True
        step(report, "页面加载完成", ok)
        timer.start()

    view.loadFinished.connect(after_load)
    view.load(QUrl(report["url"]))

    def snapshot() -> None:
        regions = state["regions"] or []
        total = geo.width() * geo.height()
        covered = sum((r[2] - r[0]) * (r[3] - r[1]) for r in regions)
        report["mask"] = {
            "rects": len(regions),
            "covered_pct": round(100.0 * covered / total, 3),
            "regions": [list(r) for r in regions],
        }
        step(
            report,
            "遮罩生效且面积远小于整屏",
            bool(state["mask"]) and 0 < covered < total * 0.4,
            f"覆盖 {report['mask']['covered_pct']}%，{len(regions)} 个矩形",
        )
        screen.grabWindow(0).save(str(BUILD / "spike-overlay-idle.png"))
        measure_whale()

    def measure_whale() -> None:
        def got(result: object) -> None:
            state["whale"] = result
            QTimer.singleShot(300, phase_click)

        # 挂件用角色图的 alpha 通道判定"点到鲸鱼没有"，透明像素会放行穿透。
        # 取角色图矩形中下部（鲸鱼身体位置）作为落点，调试脚本已验证该处命中。
        view.page().runJavaScript(
            r"""(() => {
                const img = document.querySelector('.dshwv-img');
                if (!img) return '';
                const r = img.getBoundingClientRect();
                return JSON.stringify({
                    x: Math.round(r.left + r.width * 0.5),
                    y: Math.round(r.top + r.height * 0.7),
                });
            })()""",
            0,
            lambda raw: got(json.loads(raw) if isinstance(raw, str) and raw else None),
        )

    def phase_click() -> None:
        whale = state["whale"]
        if not whale:
            step(report, "真实点击鲸鱼弹出气泡", False, "拿不到鲸鱼坐标")
            finish()
            return
        view.page().runJavaScript(
            "window.__spikeClicks = 0;"
            " document.addEventListener('mousedown', () => { window.__spikeClicks++; }, true);"
            " document.addEventListener('pointerdown', () => { window.__spikeClicks++; }, true); 'ok'"
        )
        QTimer.singleShot(500, do_click)

    def do_click(attempt: int = 1) -> None:
        whale = state["whale"]
        dpr = screen.devicePixelRatio()
        x = int(round((geo.x() + whale["x"]) * dpr))
        y = int(round((geo.y() + whale["y"]) * dpr))
        report["click_target"] = {"x": x, "y": y, "attempt": attempt}
        user32 = ctypes.windll.user32
        user32.SetCursorPos(x, y)
        time.sleep(0.25)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        QTimer.singleShot(300, lambda: probe_pressed(attempt))

    def probe_pressed(attempt: int) -> None:
        """按下期间检查：页面收到事件 + 挂件自己的 alpha 命中测试认了这一次点击。"""

        def got(raw: object) -> None:
            parsed = {}
            try:
                parsed = json.loads(raw) if isinstance(raw, str) and raw else {}
            except Exception:
                parsed = {}
            report["pressed"] = {**parsed, "attempt": attempt}
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            if not parsed.get("clicks") and attempt < 3:
                # QtWebEngine 首次合成之前偶发吞掉第一次按下，重试一次
                QTimer.singleShot(800, lambda: do_click(attempt + 1))
                return
            QTimer.singleShot(900, check_click)

        view.page().runJavaScript(
            "JSON.stringify({clicks: window.__spikeClicks || 0,"
            " drag: document.querySelector('.dshwv-root').className.indexOf('dragging') >= 0})",
            0,
            got,
        )

    def check_click() -> None:
        def got(raw: object) -> None:
            parsed = {}
            try:
                parsed = json.loads(raw) if isinstance(raw, str) and raw else {}
            except Exception:
                parsed = {}
            pressed = report.get("pressed", {})
            ok = bool(pressed.get("clicks")) and bool(pressed.get("drag")) and bool(parsed.get("pop"))
            report["click_result"] = {**pressed, "pop": bool(parsed.get("pop"))}
            step(
                report,
                "真实点击鲸鱼被挂件命中并弹出气泡",
                ok,
                f"页面收到 {pressed.get('clicks')} 次指针按下，按下期间拖动态={pressed.get('drag')}，"
                f"松手后气泡={bool(parsed.get('pop'))}",
            )
            screen.grabWindow(0).save(str(BUILD / "spike-overlay-clicked.png"))
            finish()

        view.page().runJavaScript(
            "JSON.stringify({pop: !!document.querySelector('.dshwv-pop.dshwv-pop-open')})",
            0,
            got,
        )

    def finish() -> None:
        report["ok"] = bool(report["steps"]) and all(s["ok"] for s in report["steps"])
        (BUILD / "spike-overlay-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("结论：" + ("阶段 0b 通过 [OK]" if report["ok"] else "阶段 0b 未通过 [FAIL]"))
        app.quit()

    QTimer.singleShot(3500, snapshot)
    QTimer.singleShot(30000, finish)
    app.exec()
    timer.stop()
    window.hide()
    host.terminate()
    try:
        host.wait(timeout=5)
    except Exception:
        host.kill()
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
