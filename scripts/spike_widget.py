"""阶段 0a 验证：把真插件跑在假 DSH 宿主里，用真实浏览器确认挂件能渲染、能交互。

用法（在项目根目录）：
    .venv\\Scripts\\python.exe scripts\\spike_widget.py

产出：
    build/spike-widget-*.png   各步骤截图
    build/spike-report.json    每步结果 + 浏览器控制台报错
"""

from __future__ import annotations

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

# 控制台默认是 GBK，直接 print 中文/符号会炸，这里统一切到 UTF-8。
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

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
    node = find_node()
    env = dict(os.environ)
    env["WHALE_PET_ROOT"] = str(ROOT)
    env["WHALE_PET_DATA"] = str(BUILD / "data")
    env["WHALE_PET_PORT"] = "0"
    proc = subprocess.Popen(
        [str(node), str(ROOT / "host" / "host.mjs")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise SystemExit(f"host 启动失败：{proc.stderr.read()}")
            continue
        match = re.search(r"WHALE_HOST_READY (\{.*\})", line)
        if match:
            return proc, int(json.loads(match.group(1))["port"])
    proc.kill()
    raise SystemExit("host 启动超时")


def main() -> int:
    from playwright.sync_api import sync_playwright

    host, port = start_host()
    url = f"http://127.0.0.1:{port}/"
    report: dict = {"url": url, "steps": [], "console": [], "errors": []}

    def step(name: str, ok: bool, detail: str = "") -> None:
        report["steps"].append({"name": name, "ok": bool(ok), "detail": detail})
        print(("  [OK] " if ok else "  [!!] ") + name + (f" — {detail}" if detail else ""))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda m: report["console"].append(f"{m.type}: {m.text}"))
            page.on("pageerror", lambda e: report["errors"].append(str(e)))

            page.goto(url, wait_until="load")
            print(f"已打开 {url}")

            # 1. 挂件根节点出现
            try:
                page.wait_for_selector(".dshwv-root", timeout=15000)
                step("挂件根节点 .dshwv-root 出现", True)
            except Exception as exc:  # noqa: BLE001
                step("挂件根节点 .dshwv-root 出现", False, str(exc)[:200])

            # 2. 角色图加载成功（naturalWidth > 0 说明 /dsh-whale/image.png 正常）
            whale_size = page.evaluate(
                """() => {
                    const img = document.querySelector('.dshwv-img');
                    if (!img) return null;
                    return { src: img.getAttribute('src'), w: img.naturalWidth, h: img.naturalHeight };
                }"""
            )
            step(
                "角色图已加载",
                bool(whale_size and whale_size.get("w")),
                json.dumps(whale_size, ensure_ascii=False),
            )
            page.screenshot(path=str(BUILD / "spike-widget-idle.png"))

            # 3. 点击角色 → 弹出气泡
            bubble_text = ""
            try:
                box = page.locator(".dshwv-img").bounding_box()
                if box:
                    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.85)
                page.wait_for_selector(".dshwv-pop.dshwv-pop-open", timeout=8000)
                bubble_text = page.evaluate(
                    """() => {
                        const el = document.querySelector('.dshwv-pop.dshwv-pop-open');
                        return el ? (el.innerText || el.textContent || '').trim().slice(0, 200) : '';
                    }"""
                )
                step("点击角色弹出气泡", True, bubble_text.replace("\n", " | "))
            except Exception as exc:  # noqa: BLE001
                step("点击角色弹出气泡", False, str(exc)[:200])
            page.screenshot(path=str(BUILD / "spike-widget-bubble.png"))

            # 4. 打开菜单/面板
            panel_ok = False
            panel_detail = ""
            try:
                page.evaluate(
                    """() => {
                        const btn = document.querySelector('.dshwv-menu-btn');
                        if (btn) btn.click();
                    }"""
                )
                time.sleep(1.0)
                panel_detail = page.evaluate(
                    """() => {
                        const nodes = [...document.querySelectorAll('[class*="dshwv-"][class*="mask"], [class*="dshwv-"][class*="panel"], [class*="dshwv-"][class*="menu"]')];
                        const visible = nodes.filter((n) => n.offsetParent !== null && n.getBoundingClientRect().width > 40);
                        return visible.slice(0, 5).map((n) => n.className + ' ' + Math.round(n.getBoundingClientRect().width) + 'x' + Math.round(n.getBoundingClientRect().height)).join(' || ');
                    }"""
                )
                panel_ok = bool(panel_detail)
                step("点击菜单按钮后面板出现", panel_ok, panel_detail[:200])
            except Exception as exc:  # noqa: BLE001
                step("点击菜单按钮后面板出现", False, str(exc)[:200])
            page.screenshot(path=str(BUILD / "spike-widget-menu.png"), full_page=False)

            # 5. 关键接口在页面内可用
            api = page.evaluate(
                """async () => {
                    const out = {};
                    for (const path of ['roles.json', 'audio.json', 'size.json', 'bubble.json', 'balance.json', 'usage-records.json']) {
                        try {
                            const r = await fetch('/dsh-whale/' + path, { cache: 'no-store' });
                            const t = await r.text();
                            out[path] = { status: r.status, len: t.length, head: t.slice(0, 60) };
                        } catch (err) { out[path] = { error: String(err) }; }
                    }
                    return out;
                }"""
            )
            step("页面内接口可用", all(v.get("status") == 200 for v in api.values()), json.dumps(api, ensure_ascii=False)[:300])

            browser.close()
    finally:
        host.terminate()
        try:
            host.wait(timeout=5)
        except Exception:  # noqa: BLE001
            host.kill()

    report["ok"] = bool(report["steps"]) and all(s["ok"] for s in report["steps"])
    (BUILD / "spike-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print("结论：" + ("阶段 0a 通过 [OK]" if report["ok"] else "阶段 0a 未通过 [FAIL]"))
    if report["errors"]:
        print("页面报错：")
        for err in report["errors"][:10]:
            print("  -", err[:200])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
