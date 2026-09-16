"""运行时解包 + Node 宿主进程 + 宿主 HTTP 客户端。

打包后：node.exe 与插件本体放在 exe 内的 payload.zip 里，首次运行解到
<数据目录>/runtime/<版本戳>/ 并复用（避免每次启动都解一遍）。
源码运行：直接用仓库里的 runtime/node/node.exe 与 vendor/dsh-whale-widget。
"""

from __future__ import annotations

import json
import hashlib
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from . import APP_VERSION, PLUGIN_VERSION
from .config import app_root, data_root, dsh_home, log_dir, runtime_dir

RUNTIME_BASE = f"{APP_VERSION}-plugin{PLUGIN_VERSION}"
HANDSHAKE_PREFIX = "WHALE_HOST_READY "


def _payload_hash(path: Path) -> str:
    """payload.zip 的内容指纹：改了 host.mjs/插件就换缓存目录，避免用到旧的解包结果。"""
    try:
        digest = hashlib.sha1()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()[:8]
    except Exception:
        return "00000000"


def runtime_stamp() -> str:
    payload = bundled_payload()
    if payload is None:
        return RUNTIME_BASE
    return f"{RUNTIME_BASE}-{_payload_hash(payload)}"


def bundled_payload() -> Path | None:
    """打好的 payload.zip（node + 插件）。源码运行时若不存在则返回 None。"""
    if getattr(sys, "frozen", False):
        candidate = Path(getattr(sys, "_MEIPASS", app_root())) / "payload.zip"
        return candidate if candidate.exists() else None
    candidate = app_root() / "build" / "payload.zip"
    return candidate if candidate.exists() else None


def repo_runtime() -> tuple[Path, Path, Path] | None:
    """源码运行时直接使用仓库里的 node + 插件 + 宿主脚本（改完立刻生效）。"""
    repo = app_root()
    node = repo / "runtime" / "node" / "node.exe"
    plugin = repo / "vendor" / "dsh-whale-widget"
    host_js = repo / "host" / "host.mjs"
    if node.exists() and (plugin / "lib" / "index.js").exists() and host_js.exists():
        return node, plugin, host_js
    return None


def _extract_payload(zip_path: Path, target: Path) -> None:
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    tmp.replace(target)


def resolve_runtime() -> tuple[Path, Path, Path]:
    """返回 (node.exe, 插件目录, 宿主脚本 host.mjs)，必要时先解包并缓存。"""
    # 源码运行优先用仓库：改了 host.mjs / 插件立刻生效，不会误用旧的 payload.zip
    if not getattr(sys, "frozen", False):
        local = repo_runtime()
        if local:
            return local

    target = runtime_dir() / runtime_stamp()
    node = target / "node" / "node.exe"
    plugin = target / "plugin"
    host_js = target / "host.mjs"
    if node.exists() and (plugin / "lib" / "index.js").exists() and host_js.exists():
        _prune_runtime_dirs(target)
        return node, plugin, host_js

    payload = bundled_payload()
    if payload is not None:
        _extract_payload(payload, target)
        if node.exists() and (plugin / "lib" / "index.js").exists() and host_js.exists():
            _prune_runtime_dirs(target)
            return node, plugin, host_js
        raise RuntimeError(f"运行时解包不完整：{target}")

    local = repo_runtime()
    if local:
        return local
    raise RuntimeError(
        "找不到 node.exe / 插件本体。源码运行请先执行："
        " scripts\\fetch_node.ps1（下载 Node）与 scripts\\sync-plugin.ps1（拉取插件）"
    )


def _prune_runtime_dirs(keep: Path) -> None:
    """清掉旧版本的解包结果，省磁盘也避免混用。"""
    try:
        for entry in keep.parent.iterdir():
            if entry.is_dir() and entry != keep:
                shutil.rmtree(entry, ignore_errors=True)
    except Exception:
        pass


class HostProcess:
    """Node 宿主子进程：起服务、握手拿端口、退出时清理。"""

    def __init__(self, log_enabled: bool = False) -> None:
        self.node, self.plugin, self.host_js = resolve_runtime()
        self.log_enabled = log_enabled
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr_log = log_dir() / "host.log"
        self._record = data_root() / ".host.json"

    # ------------------------------------------------------------------ 生命周期
    def start(self, timeout: float = 40.0) -> int:
        self._reap_orphan()
        env = dict(os.environ)
        env.update(
            WHALE_PET_ROOT=str(app_root()),
            WHALE_PET_PLUGIN=str(self.plugin),
            WHALE_PET_DATA=str(data_root()),
            DSH_HOME=str(dsh_home()),
            WHALE_PET_PORT="0",
            WHALE_PET_QUIET="0" if self.log_enabled else "1",
        )
        creation = 0
        if os.name == "nt":
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        stderr_target = open(self._stderr_log, "a", encoding="utf-8") if self.log_enabled else subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [str(self.node), str(self.host_js)],
            cwd=str(app_root()),
            env=env,
            stdout=subprocess.PIPE,
            stderr=stderr_target,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation,
        )
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"宿主进程已退出（code={self.proc.returncode}）")
            try:
                line = self._lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if line.startswith(HANDSHAKE_PREFIX):
                payload = json.loads(line[len(HANDSHAKE_PREFIX):])
                self.port = int(payload["port"])
                self._write_record()
                return self.port
        self.stop()
        raise RuntimeError("宿主进程启动超时")

    def _pump_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self._lines.put(line.rstrip("\r\n"))

    def stop(self, timeout: float = 6.0) -> None:
        proc = self.proc
        if not proc:
            return
        try:
            if proc.poll() is None:
                try:
                    self.post("/__host/shutdown", {}, timeout=1.0)
                except Exception:
                    pass
                try:
                    proc.wait(timeout=timeout * 0.6)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=timeout * 0.4)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        finally:
            self.proc = None
            try:
                self._record.unlink(missing_ok=True)
            except Exception:
                pass

    # --------------------------------------------------------- 孤儿进程处理
    def _write_record(self) -> None:
        try:
            self._record.write_text(
                json.dumps({"pid": self.proc.pid if self.proc else 0, "port": self.port}),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _reap_orphan(self) -> None:
        """上次被强杀时宿主会变成孤儿进程，这里按记录先礼后兵地收掉它。"""
        try:
            record = json.loads(self._record.read_text(encoding="utf-8"))
        except Exception:
            return
        pid = int(record.get("pid") or 0)
        port = int(record.get("port") or 0)
        if port:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/__host/status", timeout=2
                ) as resp:
                    status = json.loads(resp.read().decode("utf-8") or "{}")
                if status.get("plugin") == "whale-balance-widget":
                    try:
                        urllib.request.urlopen(
                            urllib.request.Request(
                                f"http://127.0.0.1:{port}/__host/shutdown", data=b"{}", method="POST"
                            ),
                            timeout=1.0,
                        )
                    except Exception:
                        pass
                    time.sleep(0.5)
            except Exception:
                pass
        if pid:
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    creationflags=creation,
                    timeout=5,
                )
            except Exception:
                pass
        try:
            self._record.unlink(missing_ok=True)
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # ------------------------------------------------------------------ HTTP 客户端
    def _url(self, path: str) -> str:
        if not self.port:
            raise RuntimeError("宿主进程尚未启动")
        return f"http://127.0.0.1:{self.port}{path}"

    def post(self, path: str, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"宿主请求失败 {path}: {exc}") from exc

    def get(self, path: str, timeout: float = 5.0) -> dict[str, Any]:
        with urllib.request.urlopen(self._url(path), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    # ------------------------------------------------------------------ 便捷方法
    def status(self) -> dict[str, Any]:
        return self.get("/__host/status")

    def set_credential(self, ref: str, value: str) -> None:
        self.post("/__host/credential", {"ref": ref, "value": value})

    def feed_usage(self, **usage: Any) -> dict[str, Any]:
        return self.post("/__host/usage", usage)
