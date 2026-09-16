"""本地 OpenAI 兼容中转：把客户端的请求转给真正的 API，顺便抓 usage 喂给挂件。

桌面版没有 DSH 的会话事件，所以"每轮消耗/模型明细/额度累计"靠这里合成。
用法和旧版桌宠一致：把客户端 base_url 指到 http://127.0.0.1:<端口>/v1。

支持：
  - POST /v1/chat/completions（流式 SSE / 非流式）
  - GET  /v1/models、其余 /v1/* 透明转发
  - GET  /healthz
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlsplit

HOP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "accept-encoding",
}


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """把各家字段折算成挂件要的口径（input=缓存未命中输入，cache=缓存命中输入）。"""
    if not isinstance(usage, dict) or not usage:
        return None
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    details = usage.get("prompt_tokens_details") or {}
    if hit is None:
        hit = details.get("cached_tokens")
    if miss is None:
        miss = prompt - int(hit) if hit is not None else prompt
    cache = int(hit or 0)
    input_tokens = int(miss or 0)
    out_details = usage.get("completion_tokens_details") or {}
    reasoning = int(out_details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0)
    if prompt == 0 and output == 0 and cache == 0:
        return None
    return {
        "inputTokens": max(input_tokens, 0),
        "cacheReadTokens": max(cache, 0),
        "outputTokens": max(output, 0),
        "reasoningTokens": max(reasoning, 0),
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WhalePetProxy/1.0"

    # 静默默认日志（噪音大且可能带密钥）
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ helpers
    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _target(self) -> tuple[str, str, int, bool, str]:
        base = (self.server.api_base or "https://api.deepseek.com").rstrip("/")  # type: ignore[attr-defined]
        parts = urlsplit(base)
        scheme = parts.scheme or "https"
        host = parts.hostname or "api.deepseek.com"
        port = parts.port or (443 if scheme == "https" else 80)
        prefix = parts.path.rstrip("/")
        path = prefix + self.path
        return scheme, host, port, scheme == "https", path

    def _headers(self, body: bytes) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in self.headers.items():
            if key.lower() in HOP_HEADERS:
                continue
            out[key] = value
        if "Authorization" not in out and self.server.api_key:  # type: ignore[attr-defined]
            out["Authorization"] = f"Bearer {self.server.api_key}"  # type: ignore[attr-defined]
        out["Content-Length"] = str(len(body))
        out["Accept-Encoding"] = "identity"
        return out

    # ------------------------------------------------------------------ routes
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            self._json(200, {"ok": True, "service": "whalepet-proxy"})
            return
        self._forward("GET", b"")

    def do_POST(self) -> None:  # noqa: N802
        self._forward("POST", self._read_body())

    def do_PUT(self) -> None:  # noqa: N802
        self._forward("PUT", self._read_body())

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward("DELETE", b"")

    # ------------------------------------------------------------------ forward
    def _forward(self, method: str, body: bytes) -> None:
        try:
            scheme, host, port, use_tls, path = self._target()
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": {"message": f"api_base 解析失败：{exc}"}})
            return

        headers = self._headers(body)
        model = ""
        want_usage = self.path.startswith("/v1/chat/completions") or "/messages" in self.path
        if body and want_usage:
            try:
                model = str(json.loads(body.decode("utf-8")).get("model") or "")
            except Exception:
                model = ""

        conn: http.client.HTTPConnection | None = None
        try:
            if use_tls:
                conn = http.client.HTTPSConnection(host, port, timeout=300, context=ssl.create_default_context())
            else:
                conn = http.client.HTTPConnection(host, port, timeout=300)
            conn.request(method, path, body=body or None, headers=headers)
            resp = conn.getresponse()
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": {"message": f"上游连接失败：{exc}"}})
            if conn:
                conn.close()
            return

        content_type = resp.getheader("Content-Type", "")
        is_sse = "text/event-stream" in content_type
        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() in HOP_HEADERS:
                continue
            self.send_header(key, value)
        if is_sse:
            self.send_header("Cache-Control", "no-cache")
        # 上游可能是 chunked；我们剥掉了长度相关头，所以统一用"读完即关"来界定边界
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        captured: dict[str, Any] | None = None
        text_tail = ""
        try:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                if want_usage:
                    if is_sse:
                        text_tail += chunk.decode("utf-8", "ignore")
                        usage = _usage_from_sse(text_tail)
                        if usage:
                            captured = usage
                            text_tail = text_tail[-4096:]
                    else:
                        text_tail += chunk.decode("utf-8", "ignore")
            if want_usage and not is_sse and text_tail:
                try:
                    payload = json.loads(text_tail)
                    usage = normalize_usage(payload.get("usage"))
                    if usage:
                        captured = {**usage, "model": payload.get("model") or model}
                except Exception:
                    pass
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

        if captured:
            self.server.report_usage(captured)  # type: ignore[attr-defined]


def _usage_from_sse(text: str) -> dict[str, Any] | None:
    """从 SSE 文本里找最后一条带 usage 的 data 行。"""
    found: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        usage = normalize_usage(obj.get("usage"))
        if usage:
            found = {**usage, "model": obj.get("model") or ""}
    return found


class ProxyServer:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        on_usage: Callable[[dict[str, Any]], None],
        host: str = "127.0.0.1",
        port: int = 11434,
        verbose: bool = False,
    ) -> None:
        self.api_base = api_base
        self.api_key = api_key
        self.on_usage = on_usage
        self.host = host
        self.port = port
        self.verbose = verbose
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.turns = 0
        self._lock = threading.Lock()

    def start(self) -> int:
        handler = _Handler
        httpd = ThreadingHTTPServer((self.host, self.port), handler)
        httpd.daemon_threads = True
        httpd.api_base = self.api_base  # type: ignore[attr-defined]
        httpd.api_key = self.api_key  # type: ignore[attr-defined]
        httpd.verbose = self.verbose  # type: ignore[attr-defined]
        httpd.report_usage = self._report  # type: ignore[attr-defined]
        self.httpd = httpd
        self.port = httpd.server_address[1]
        self.thread = threading.Thread(target=httpd.serve_forever, name="whalepet-proxy", daemon=True)
        self.thread.start()
        return self.port

    def _report(self, usage: dict[str, Any]) -> None:
        with self._lock:
            self.turns += 1
            payload = {"turn": self.turns, **usage}
        try:
            self.on_usage(payload)
        except Exception:
            pass

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False
