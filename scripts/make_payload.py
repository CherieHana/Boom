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

INCLUDE_PLUGIN = ["lib", "assets", "package.json", "cordis.patch.yml", "LICENSE", "README.md"]


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
        for item in INCLUDE_PLUGIN:
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
