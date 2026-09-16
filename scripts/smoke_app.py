"""源码态端到端冒烟：起一次完整程序，确认宿主/覆盖层/中转都能起来，再正常退出。

用法：.venv\\Scripts\\python.exe scripts\\smoke_app.py
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DATA = BUILD / "smoke-data"

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    import shutil

    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "config.json").write_text(
        json.dumps(
            {
                "first_run_done": True,
                "api_key": "sk-smoke-test-not-a-real-key",
                "proxy_enabled": True,
                "proxy_port": 18999,
                "overlay": {"visible": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["WHALE_PET_DATA"] = str(DATA)
    env["WHALE_PET_AUTOQUIT"] = "9"
    env["PYTHONIOENCODING"] = "utf-8"

    started = time.time()
    proc = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(ROOT / "main.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    elapsed = time.time() - started
    print(f"退出码 {proc.returncode}，用时 {elapsed:.1f}s")
    if proc.stdout.strip():
        print("stdout:", proc.stdout.strip()[:2000])
    if proc.stderr.strip():
        print("stderr:", proc.stderr.strip()[:3000])

    checks: list[tuple[str, bool, str]] = []
    log_path = DATA / "logs" / "whalepet.log"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    checks.append(("启动日志存在", bool(log_text), log_text.strip().splitlines()[-1] if log_text else ""))
    checks.append(("宿主已就绪", "宿主已就绪" in log_text, ""))
    checks.append(("进程正常退出", proc.returncode == 0, f"code={proc.returncode}"))

    dsh = DATA / "dsh-home"
    checks.append(("插件数据目录已建", dsh.exists(), str(dsh)))
    cred = dsh / "credentials.json"
    has_key = False
    if cred.exists():
        try:
            has_key = bool(json.loads(cred.read_text(encoding="utf-8")).get("DEEPSEEK_API_KEY"))
        except Exception:
            has_key = False
    checks.append(("API Key 已写入插件密钥库", has_key, str(cred)))
    checks.append(("插件状态文件已生成", (dsh / ".dshw-size.json").exists(), ""))

    # 中转端口应已释放
    import socket

    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 18999))
            released = True
        except OSError:
            released = False
    checks.append(("退出后中转端口已释放", released, "18999"))

    print()
    ok = True
    for name, passed, detail in checks:
        ok = ok and passed
        print(("  [OK] " if passed else "  [!!] ") + name + (f" —— {detail}" if detail else ""))
    print()
    print("冒烟结果：" + ("通过 [OK]" if ok else "失败 [FAIL]"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
