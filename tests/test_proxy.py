from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from whalepet.proxy import ProxyServer, normalize_usage, _usage_from_sse


def test_normalize_usage_deepseek_fields():
    usage = normalize_usage(
        {
            "prompt_tokens": 1000,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 10},
        }
    )
    assert usage == {
        "inputTokens": 200,
        "cacheReadTokens": 800,
        "outputTokens": 50,
        "reasoningTokens": 10,
    }


def test_normalize_usage_openai_style_without_cache_split():
    usage = normalize_usage({"prompt_tokens": 300, "completion_tokens": 20})
    assert usage == {"inputTokens": 300, "cacheReadTokens": 0, "outputTokens": 20, "reasoningTokens": 0}


def test_normalize_usage_empty():
    assert normalize_usage({}) is None
    assert normalize_usage(None) is None


def test_usage_from_sse_picks_last_usage_block():
    text = (
        'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
        'data: {"usage":{"prompt_tokens":10,"completion_tokens":5},"model":"deepseek-chat"}\n\n'
        "data: [DONE]\n\n"
    )
    usage = _usage_from_sse(text)
    assert usage is not None
    assert usage["inputTokens"] == 10
    assert usage["outputTokens"] == 5
    assert usage["model"] == "deepseek-chat"


class _Upstream(BaseHTTPRequestHandler):
    mode = "json"

    def log_message(self, *args):  # noqa: ANN002
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.mode == "sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
            self.wfile.write(
                (
                    "data: "
                    + json.dumps(
                        {
                            "model": body.get("model"),
                            "usage": {"prompt_tokens": 700, "completion_tokens": 30},
                        }
                    )
                    + "\n\n"
                ).encode("utf-8")
            )
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = {
            "model": body.get("model"),
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {
                "prompt_tokens": 500,
                "prompt_cache_hit_tokens": 400,
                "prompt_cache_miss_tokens": 100,
                "completion_tokens": 25,
            },
        }
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture()
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _call(port: int, body: dict) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    raw = json.dumps(body).encode("utf-8")
    conn.request(
        "POST",
        "/v1/chat/completions",
        body=raw,
        headers={"Content-Type": "application/json", "Content-Length": str(len(raw))},
    )
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return {"status": resp.status, "raw": data}


def test_proxy_relays_and_reports_usage(upstream):
    seen: list[dict] = []
    proxy = ProxyServer(
        api_base=f"http://127.0.0.1:{upstream.server_address[1]}",
        api_key="sk-test",
        on_usage=seen.append,
        port=0,
    )
    port = proxy.start()
    try:
        result = _call(port, {"model": "deepseek-chat", "messages": []})
        assert result["status"] == 200
        assert json.loads(result["raw"])["choices"][0]["message"]["content"] == "hi"
    finally:
        proxy.stop()
    assert seen, "应当抓到 usage"
    usage = seen[0]
    assert usage["inputTokens"] == 100
    assert usage["cacheReadTokens"] == 400
    assert usage["outputTokens"] == 25
    assert usage["model"] == "deepseek-chat"
    assert usage["turn"] == 1


def test_proxy_streaming_reports_usage(upstream):
    _Upstream.mode = "sse"
    seen: list[dict] = []
    proxy = ProxyServer(
        api_base=f"http://127.0.0.1:{upstream.server_address[1]}",
        api_key="sk-test",
        on_usage=seen.append,
        port=0,
    )
    port = proxy.start()
    try:
        result = _call(port, {"model": "deepseek-reasoner", "stream": True, "messages": []})
        assert result["status"] == 200
        assert b"[DONE]" in result["raw"]
    finally:
        proxy.stop()
        _Upstream.mode = "json"
    assert seen and seen[0]["outputTokens"] == 30
    assert seen[0]["model"] == "deepseek-reasoner"


def test_proxy_healthz():
    proxy = ProxyServer(api_base="https://api.deepseek.com", api_key="", on_usage=lambda _u: None, port=0)
    port = proxy.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        conn.close()
    finally:
        proxy.stop()
    assert payload["ok"] is True
