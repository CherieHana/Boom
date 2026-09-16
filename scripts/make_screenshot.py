"""生成 README 用的产品截图（无头浏览器渲染，不带桌面/其它窗口内容）。

用法：.venv\\Scripts\\python.exe scripts\\make_screenshot.py
产出：docs/screenshot.png
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshot.png"

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def start_host() -> tuple[subprocess.Popen, int]:
    data = ROOT / "build" / "shot-data"
    (data / "dsh-home").mkdir(parents=True, exist_ok=True)
    # 截图用一份干净配置：中等大小、音效小黄鸭
    (data / "dsh-home" / ".dshw-size.json").write_text(
        json.dumps(
            {
                "scale": 1.3,
                "sound": True,
                "vol": 0.9,
                "soundSet": "duck",
                "usageMode": "ledger",
                "peakMode": "default",
                "bubbleOn": True,
                "turnCostOn": True,
                "turnCostCloseMs": 5000,
            }
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(WHALE_PET_ROOT=str(ROOT), WHALE_PET_DATA=str(data), WHALE_PET_PORT="0")
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


BACKDROP = """
html, body { background: linear-gradient(145deg, #eef2fb 0%, #dfe6f6 45%, #cfd9f0 100%) !important; }
#shot-note { position: fixed; left: 28px; top: 24px; font: 13px/1.7 "Microsoft YaHei UI", sans-serif;
  color: #5a6b9a; letter-spacing: .02em; }
#shot-note b { display: block; font-size: 20px; color: #203170; letter-spacing: 0; margin-bottom: 6px; }
"""

NOTE = """
<div id="shot-note">
  <b>WhalePet</b>
  桌面小鲸鱼余额挂件<br>
  点鲸鱼弹泡泡，点右上角按钮开设置面板
</div>
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    host, port = start_host()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 860, "height": 780}, device_scale_factor=2)
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_selector(".dshwv-root", timeout=15000)
            page.add_style_tag(content=BACKDROP)
            page.evaluate(
                "(html) => { const d = document.createElement('div'); d.innerHTML = html;"
                " document.body.appendChild(d); }",
                NOTE,
            )
            # 打开设置面板（比泡泡更能体现功能）
            page.evaluate("document.querySelector('.dshwv-menu-btn').click()")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT))
            browser.close()
    finally:
        host.terminate()
    print(f"截图已生成：{OUT}（{OUT.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
