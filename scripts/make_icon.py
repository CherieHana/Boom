"""从插件角色图生成 exe 图标（多尺寸 ICO）。"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "dsh-whale-widget" / "assets" / "DSniang1.png"
TARGET = ROOT / "build" / "whalepet.ico"
# 窗口/托盘图标素材也放 build/：它来自插件（第三方素材），只作为构建产物，不入库
WINDOW_ASSET = ROOT / "build" / "DSniang1.png"


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPixmap

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    if not SOURCE.exists():
        print(f"缺少角色图：{SOURCE}", file=sys.stderr)
        return 2
    src = QPixmap(str(SOURCE))
    if src.isNull():
        print("角色图读取失败", file=sys.stderr)
        return 3
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # Qt 的 ICO 写出只保留一张位图，这里手工拼多尺寸
    pngs: list[bytes] = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        scaled = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        tmp = TARGET.with_name(f"icon-{size}.png")
        scaled.save(str(tmp), "PNG")
        pngs.append(tmp.read_bytes())
        tmp.unlink()
    _write_ico(TARGET, [(16, pngs[0]), (24, pngs[1]), (32, pngs[2]), (48, pngs[3]),
                        (64, pngs[4]), (128, pngs[5]), (256, pngs[6])])
    WINDOW_ASSET.write_bytes(SOURCE.read_bytes())
    print(f"图标已生成：{TARGET}（{TARGET.stat().st_size} 字节），窗口图标素材：{WINDOW_ASSET}")
    return 0


def _write_ico(path: pathlib.Path, entries: list[tuple[int, bytes]]) -> None:
    import struct

    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + count * 16
    directory = b""
    payload = b""
    for size, data in entries:
        directory += struct.pack(
            "<BBBBHHII", 0 if size >= 256 else size, 0 if size >= 256 else size, 0, 0, 1, 32, len(data), offset
        )
        payload += data
        offset += len(data)
    path.write_bytes(header + directory + payload)


if __name__ == "__main__":
    raise SystemExit(main())
