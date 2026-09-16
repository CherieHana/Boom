"""生成 Windows 版本资源（exe 属性里显示的版本/版权）。"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from whalepet import APP_VERSION, PLUGIN_VERSION  # noqa: E402

TARGET = ROOT / "build" / "version_info.txt"


def main() -> int:
    parts = (APP_VERSION.split(".") + ["0", "0", "0"])[:4]
    numbers = ", ".join(str(int(p)) if p.isdigit() else "0" for p in parts)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numbers}),
    prodvers=({numbers}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', 'WhalePet'),
        StringStruct('FileDescription', '小鲸鱼桌宠（内置 dsh-whale-widget {PLUGIN_VERSION}）'),
        StringStruct('FileVersion', '{APP_VERSION}'),
        StringStruct('InternalName', 'WhalePet'),
        StringStruct('OriginalFilename', 'WhalePet.exe'),
        StringStruct('ProductName', 'WhalePet'),
        StringStruct('ProductVersion', '{APP_VERSION} (plugin {PLUGIN_VERSION})'),
        StringStruct('LegalCopyright', 'Whale widget: MeteorNOX/DeepSeek-Balance-Whale-Widget (MIT)')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
  ]
)
"""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"版本资源已生成：{TARGET}（v{APP_VERSION} / plugin {PLUGIN_VERSION}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
