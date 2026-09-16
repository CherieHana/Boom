# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台、内嵌 payload.zip（node + 插件本体）。"""

import os
from pathlib import Path

ROOT = Path(SPECPATH)

# 这台机器 PATH 里有 Codex 运行时/MySQL 等自带的 DLL（poppler 的 ICU 78、libheif 的 ucrtbase、
# MySQL 的 libcrypto…）。PyInstaller 会拿它们去补依赖，结果打进包里就是版本打架：
# Qt6Core 报 "DLL load failed ... 找不到指定的程序"。构建前先把这些目录从 PATH 摘掉。
_SKIP_PATH_MARKERS = (
    ".cache\\codex-runtimes",
    ".cache/codex-runtimes",
    "poppler",
    "libheif",
    "mysql",
    "windowsapps",
)
_paths = [
    p
    for p in os.environ.get("PATH", "").split(os.pathsep)
    if p and not any(marker in p.lower() for marker in _SKIP_PATH_MARKERS)
]
os.environ["PATH"] = os.pathsep.join(_paths)

EXCLUDES = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebSockets",
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "pytest",
    "playwright",
]

datas = [
    (str(ROOT / "build" / "payload.zip"), "."),
    (str(ROOT / "build" / "DSniang1.png"), "assets"),
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# MSVC 运行时必须"同一套"：PyInstaller 会从 Python 安装目录收 14.42 的 VCRUNTIME140*.dll，
# 而 PySide6 轮子里带的是 14.50 的 MSVCP140*.dll。混版本会让 QtCore.pyd 报
# "DLL load failed ... 找不到指定的程序"。这里统一换成系统里的同一版本。
_SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
_RUNTIME_NAMES = {
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}


def _unify_msvc_runtime(toc):
    fixed = []
    for dest, src, kind in toc:
        name = Path(dest).name.lower()
        # ICU 一律不打包：Qt6Core 用的是 Windows 自带的 icuuc.dll（PySide6 轮子本身也不带 ICU）。
        # 一旦打进外来版本，Qt6Core 会因为符号对不上直接加载失败。
        if name.startswith("icu") and name.endswith(".dll"):
            continue
        if name in _RUNTIME_NAMES:
            replacement = _SYS32 / Path(dest).name
            if replacement.exists():
                fixed.append((dest, str(replacement), kind))
                continue
            continue
        fixed.append((dest, src, kind))
    return fixed


# 数据裁剪：开发版 devtools 资源、Qt/Chromium 的其它语言包都进不了最终包。
_DROP_DATA_SUBSTRINGS = (
    "qtwebengine_devtools_resources",
    ".debug.pak",
    "v8_context_snapshot.debug.bin",
)
_KEEP_LOCALES = {"en-us", "zh-cn"}


def _filter_datas(toc):
    out = []
    for dest, src, kind in toc:
        logical = str(dest).replace("\\", "/")
        low = logical.lower()
        name = Path(logical).name.lower()
        if any(marker in low for marker in _DROP_DATA_SUBSTRINGS):
            continue
        if "translations/qtwebengine_locales/" in low:
            if Path(name).stem not in _KEEP_LOCALES:
                continue
        elif name.endswith(".qm"):
            if not (name.endswith("_zh_cn.qm") or name.endswith("_en.qm")):
                continue
        out.append((dest, src, kind))
    return out


a.binaries = _unify_msvc_runtime(a.binaries)
a.datas = _filter_datas(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WhalePet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "build" / "whalepet.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
)
