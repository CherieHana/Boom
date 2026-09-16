"""WhalePet 入口（也是 PyInstaller 的打包入口）。

任何启动期异常都要落盘并弹窗——窗口模式没有控制台，静默失败对用户最不友好。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _crash_log_paths() -> list[Path]:
    paths: list[Path] = []
    data = os.environ.get("WHALE_PET_DATA")
    if data:
        paths.append(Path(data) / "logs" / "crash.log")
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / "WhalePet-crash.log")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "WhalePet" / "logs" / "crash.log")
    temp = os.environ.get("TEMP")
    if temp:
        paths.append(Path(temp) / "WhalePet-crash.log")
    return paths


def _report_crash(exc: BaseException) -> str:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    saved = ""
    for path in _crash_log_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            saved = str(path)
            break
        except Exception:
            continue
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(
            None,
            "小鲸鱼启动失败",
            f"{exc}\n\n详细信息已写入：\n{saved or '（未能写入日志文件）'}",
        )
    except Exception:
        pass
    return saved


def _entry() -> int:
    from whalepet.app import main

    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(_entry())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        _report_crash(exc)
        raise SystemExit(1) from exc
