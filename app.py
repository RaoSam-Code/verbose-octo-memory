import os
import re
import time
import threading
import requests
import gradio as gr
from datetime import datetime, timezone
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Configuration (override via Space / container environment variables)
# ---------------------------------------------------------------------------
# Comma-separated list of URLs to keep alive, e.g.:
#   PING_URLS=https://my-app.hf.space,https://my-api.railway.app
PING_URLS: list[str] = [
    u.strip()
    for u in os.getenv("PING_URLS", "").split(",")
    if u.strip()
]

# How often (in seconds) to ping each URL (default: 5 minutes)
PING_INTERVAL: int = int(os.getenv("PING_INTERVAL", "300"))

# Request timeout in seconds
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))

# ---------------------------------------------------------------------------
# SSRF safeguard – block well-known internal / cloud-metadata hostnames
# ---------------------------------------------------------------------------
_BLOCKED_HOST_PATTERNS: list[re.Pattern] = [
    re.compile(r"^169\.254\."),           # AWS / Azure / GCP link-local metadata
    re.compile(r"^fd[0-9a-f]{2}:", re.I),  # IPv6 link-local / ULA
    re.compile(r"metadata\.google\.internal$", re.I),
    re.compile(r"^0\.0\.0\.0$"),
]


def _is_blocked_host(url: str) -> bool:
    """Return True if *url* targets a known-dangerous internal address."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return True
    return any(p.search(host) for p in _BLOCKED_HOST_PATTERNS)


_lock = threading.Lock()
_status: dict[str, dict] = {}   # url -> {status, code, last_ping, latency_ms}
_extra_urls: list[str] = []      # URLs added via the UI
_scheduler_started = False


def _all_urls() -> list[str]:
    """Return the merged list of env-configured + UI-added URLs (no duplicates)."""
    seen = set()
    result = []
    for u in PING_URLS + _extra_urls:
        if u and u not in seen:
            seen.add(u)
            result.append(u)
    return result


# ---------------------------------------------------------------------------
# Ping logic
# ---------------------------------------------------------------------------
def ping_url(url: str) -> dict:
    """Send a GET request to *url* and return a status dict."""
    start = time.monotonic()
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "status": "✅ OK",
            "code": resp.status_code,
            "last_ping": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "latency_ms": latency_ms,
        }
    except requests.exceptions.Timeout:
        return {
            "status": "⏱ Timeout",
            "code": None,
            "last_ping": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "latency_ms": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": f"❌ {type(exc).__name__}",
            "code": None,
            "last_ping": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "latency_ms": None,
        }


def ping_all() -> None:
    """Ping every registered URL and update shared state."""
    for url in _all_urls():
        result = ping_url(url)
        with _lock:
            _status[url] = result


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------
def _scheduler_loop() -> None:
    while True:
        ping_all()
        time.sleep(PING_INTERVAL)


def start_scheduler() -> None:
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Gradio helpers
# ---------------------------------------------------------------------------
def _build_status_table() -> list[list]:
    """Return rows for the status dataframe."""
    with _lock:
        snapshot = dict(_status)

    rows = []
    for url in _all_urls():
        info = snapshot.get(url, {})
        rows.append(
            [
                url,
                info.get("status", "⏳ Pending"),
                info.get("code", "—"),
                info.get("latency_ms", "—"),
                info.get("last_ping", "Never"),
            ]
        )
    return rows


def refresh_status() -> gr.Dataframe:
    return _build_status_table()


def add_url(new_url: str) -> tuple[gr.Dataframe, str]:
    new_url = new_url.strip()
    if not new_url:
        return _build_status_table(), "⚠️ Please enter a URL."
    if not new_url.startswith(("http://", "https://")):
        return _build_status_table(), "⚠️ URL must start with http:// or https://"
    if _is_blocked_host(new_url):
        return _build_status_table(), "⚠️ That host is not allowed."

    if new_url not in _extra_urls and new_url not in PING_URLS:
        with _lock:
            if new_url not in _extra_urls:
                _extra_urls.append(new_url)
        # Ping immediately so the user sees a result right away
        result = ping_url(new_url)
        with _lock:
            _status[new_url] = result

    return _build_status_table(), f"✅ Added and pinged: {new_url}"


def ping_now() -> tuple[gr.Dataframe, str]:
    ping_all()
    return _build_status_table(), f"🔁 Pinged all URLs at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"


# ---------------------------------------------------------------------------
# Build the Gradio UI
# ---------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Keep-Alive Pinger") as demo:
        gr.Markdown(
            """
# 🏃 Keep-Alive Pinger

Keeps your deployed apps, APIs, and Docker containers healthy by sending
periodic HTTP GET requests so they never fall asleep or get recycled.

**Configure target URLs** via the `PING_URLS` environment variable
(comma-separated) *or* add them below.  The pinger runs automatically
every **{interval}s** in the background.
""".format(
                interval=PING_INTERVAL
            )
        )

        with gr.Row():
            url_input = gr.Textbox(
                label="Add a URL to ping",
                placeholder="https://my-app.hf.space",
                scale=4,
            )
            add_btn = gr.Button("Add & Ping", variant="primary", scale=1)

        add_msg = gr.Markdown("")

        status_table = gr.Dataframe(
            headers=["URL", "Status", "HTTP Code", "Latency (ms)", "Last Ping"],
            datatype=["str", "str", "str", "str", "str"],
            value=_build_status_table(),
            label="Ping Status",
            wrap=True,
        )

        with gr.Row():
            refresh_btn = gr.Button("🔄 Refresh", scale=1)
            ping_now_btn = gr.Button("⚡ Ping Now", variant="secondary", scale=1)

        ping_msg = gr.Markdown("")

        # Wire up events
        add_btn.click(
            fn=add_url,
            inputs=[url_input],
            outputs=[status_table, add_msg],
        )
        url_input.submit(
            fn=add_url,
            inputs=[url_input],
            outputs=[status_table, add_msg],
        )
        refresh_btn.click(fn=refresh_status, outputs=[status_table])
        ping_now_btn.click(fn=ping_now, outputs=[status_table, ping_msg])

        gr.Markdown(
            """
---
### ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PING_URLS` | *(empty)* | Comma-separated list of URLs to ping |
| `PING_INTERVAL` | `300` | Seconds between automatic pings |
| `REQUEST_TIMEOUT` | `15` | Per-request timeout in seconds |
"""
        )

    return demo


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    start_scheduler()
    app = build_ui()
    app.launch(server_name="0.0.0.0", server_port=7860)
else:
    # When Hugging Face imports this module, start the scheduler and expose
    # the Gradio app as the top-level `demo` variable.
    start_scheduler()
    demo = build_ui()
