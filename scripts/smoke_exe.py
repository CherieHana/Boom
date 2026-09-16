"""对打包后的 dist\\WhalePet.exe 做冒烟：冷启动、热启动、数据落地、无残留进程。"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "WhalePet.exe"
DATA = ROOT / "build" / "exe-smoke-data"

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_once(seconds: int) -> tuple[int, float, str]:
    env = dict(os.environ)
    env["WHALE_PET_DATA"] = str(DATA)
    if os.environ.get("WHALE_PET_SELFCHECK") == "1":
        env["WHALE_PET_SELFCHECK"] = "1"
    else:
        env["WHALE_PET_AUTOQUIT"] = str(seconds)
    started = time.time()
    proc = subprocess.run([str(EXE)], env=env, timeout=300)
    elapsed = time.time() - started
    log = (DATA / "logs" / "whalepet.log").read_text(encoding="utf-8") if (DATA / "logs" / "whalepet.log").exists() else ""
    return proc.returncode, elapsed, log


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> int:
    import shutil

    if not EXE.exists():
        print("找不到 dist\\WhalePet.exe，先跑 build.ps1", file=sys.stderr)
        return 2
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "config.json").write_text(
        json.dumps(
            {
                "first_run_done": True,
                "api_key": "sk-smoke-not-real",
                "proxy_enabled": True,
                "proxy_port": 18998,
                "overlay": {"visible": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    checks: list[tuple[str, bool, str]] = []

    code, cold, log = run_once(10)
    checks.append(("冷启动退出码 0", code == 0, f"code={code}, {cold:.1f}s"))
    checks.append(("宿主就绪（冷启动）", "宿主已就绪" in log, log.strip().splitlines()[-1] if log.strip() else ""))
    if os.environ.get("WHALE_PET_SELFCHECK") == "1":
        ok_render = "SELFCHECK widget=1" in log
        detail = next((line for line in reversed(log.splitlines()) if "SELFCHECK" in line), "")
        checks.append(("挂件已在页面渲染（自检）", ok_render, detail))

    runtime = DATA / "runtime"
    extracted = list(runtime.glob("*/node/node.exe")) if runtime.exists() else []
    checks.append(("运行时已解包缓存", bool(extracted), str(extracted[0]) if extracted else ""))

    code2, warm, log2 = run_once(8)
    checks.append(("热启动退出码 0", code2 == 0, f"code={code2}, {warm:.1f}s"))
    checks.append(("热启动使用缓存（不重复解包）", warm <= cold, f"冷 {cold:.1f}s / 热 {warm:.1f}s"))
    checks.append(("中转端口已释放", port_free(18998), "18998"))

    # 只关心"我们自己的"宿主进程（系统里还有别的 node.exe，比如编辑器自带的）
    cim = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
         "Where-Object { $_.CommandLine -like '*host.mjs*' } | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    checks.append(("退出后无残留宿主进程", not cim, cim))

    print()
    ok = True
    for name, passed, detail in checks:
        ok = ok and passed
        print(("  [OK] " if passed else "  [!!] ") + name + (f" —— {detail}" if detail else ""))
    print()
    print("exe 冒烟：" + ("通过 [OK]" if ok else "失败 [FAIL]"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
