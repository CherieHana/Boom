"""分发前校验：产物里不能有个人数据/密钥，必需的运行时文件必须在。"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "WhalePet.exe"
PAYLOAD = ROOT / "build" / "payload.zip"
OLD_CONFIG = pathlib.Path(os.environ.get("APPDATA", "")) / "WhalePet" / "config.json"

SECRET_PATTERN = re.compile(rb"sk-[A-Za-z0-9_\-]{20,}")
FORBIDDEN_PAYLOAD_MEMBERS = (
    "credentials.json",
    "config.json",
    "ledger.json",
    "phrases.json",
    ".dshw-",
    "whale-roles",
    "whale-audio",
)


def check(condition: bool, name: str, detail: str = "") -> bool:
    print(("  [OK] " if condition else "  [!!] ") + name + (f" —— {detail}" if detail else ""))
    return bool(condition)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ok = True
    if not EXE.exists():
        print(f"缺少 {EXE}", file=sys.stderr)
        return 2
    size_mb = EXE.stat().st_size / 1024 / 1024
    ok &= check(True, "产物存在", f"{EXE}（{size_mb:.1f} MB）")

    data = EXE.read_bytes()
    matches = SECRET_PATTERN.findall(data)
    ok &= check(not matches, "产物里没有 sk- 形式的密钥", f"命中 {len(matches)} 处")

    real_key = ""
    try:
        real_key = str(json.loads(OLD_CONFIG.read_text(encoding="utf-8")).get("api_key") or "")
    except Exception:
        real_key = ""
    if real_key:
        ok &= check(real_key.encode("utf-8") not in data, "产物里没有本机正在用的 API Key")
    else:
        print("  [--] 跳过：本机没有可比的 API Key")

    username = pathlib.Path(os.environ.get("USERPROFILE", "C:/")).name
    if username and len(username) > 1:
        ok &= check(username.encode("utf-8") not in data, "产物里没有本机用户名")

    if not PAYLOAD.exists():
        ok &= check(False, "payload.zip 存在")
        print()
        print("分发校验：" + ("通过 [OK]" if ok else "失败 [FAIL]"))
        return 0 if ok else 1

    with zipfile.ZipFile(PAYLOAD) as zf:
        names = zf.namelist()
    for name in (
        "node/node.exe",
        "host.mjs",
        "plugin/lib/index.js",
        "plugin/assets/whale-widget.js",
        "plugin/package.json",
    ):
        ok &= check(name in names, f"payload 含 {name}")
    bad = [n for n in names if any(marker in n for marker in FORBIDDEN_PAYLOAD_MEMBERS)]
    ok &= check(not bad, "payload 不含个人数据/密钥文件", ", ".join(bad[:5]))
    ok &= check((ROOT / "build" / "version_info.txt").exists(), "版本资源已生成")

    print()
    print("分发校验：" + ("通过 [OK]" if ok else "失败 [FAIL]"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
