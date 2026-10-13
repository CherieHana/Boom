"""把 node.exe + 插件本体 + 宿主脚本打成 payload.zip（PyInstaller 的打包输入）。"""

from __future__ import annotations

import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PLUGIN = ROOT / "vendor" / "dsh-whale-widget"
NODE = ROOT / "runtime" / "node" / "node.exe"
HOST = ROOT / "host" / "host.mjs"

# 兜底清单：读不到 package.json 的 files 时用它
FALLBACK_INCLUDE = ["lib", "assets", "package.json", "cordis.patch.yml", "LICENSE", "README.md", "PROVENANCE.md"]


def plugin_files() -> list[str]:
    """按 package.json 的 files 白名单打包，避免上游新增文件（如 icon.png）被漏掉。"""
    import json

    declared: list[str] = []
    try:
        pkg = json.loads((PLUGIN / "package.json").read_text(encoding="utf-8"))
        declared = [str(x) for x in (pkg.get("files") or []) if str(x).strip()]
    except Exception:
        declared = []
    names = list(dict.fromkeys(declared + FALLBACK_INCLUDE))
    return [name for name in names if (PLUGIN / name).exists()]


def main() -> int:
    for path, what in ((NODE, "node.exe"), (HOST, "host/host.mjs"), (PLUGIN, "插件目录")):
        if not path.exists():
            print(f"缺少{what}：{path}", file=sys.stderr)
            return 2
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "payload.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(NODE, "node/node.exe")
        zf.write(HOST, "host.mjs")
        for item in plugin_files():
            source = PLUGIN / item
            if source.is_dir():
                for file in sorted(source.rglob("*")):
                    if file.is_file():
                        zf.write(file, f"plugin/{source.name}/{file.relative_to(source).as_posix()}")
            elif source.is_file():
                zf.write(source, f"plugin/{item}")
    size = out.stat().st_size
    print(f"payload.zip 已生成：{out}（{size / 1024 / 1024:.1f} MB）")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        print(f"  条目 {len(names)} 个，含 lib/index.js：{'plugin/lib/index.js' in names}，"
              f"含 whale-widget.js：{'plugin/assets/whale-widget.js' in names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
