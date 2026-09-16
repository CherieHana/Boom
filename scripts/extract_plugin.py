"""把下载好的插件 tar.gz 解到 vendor/dsh-whale-widget（供 sync-plugin.ps1 调用）。"""

from __future__ import annotations

import pathlib
import shutil
import sys
import tarfile


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: extract_plugin.py <tar.gz> <目标目录>", file=sys.stderr)
        return 2
    tarball = pathlib.Path(sys.argv[1])
    target = pathlib.Path(sys.argv[2])
    work = tarball.parent / "src"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as tf:
        tf.extractall(work)
    inner = next(p for p in work.iterdir() if p.is_dir())
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(inner, target)
    print(f"插件已更新到 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
