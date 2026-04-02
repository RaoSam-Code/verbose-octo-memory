---
title: Keep-Alive Pinger
emoji: 🏃
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "4.44.1"
app_file: app.py
pinned: false
license: mit
---

# 🏃 Keep-Alive Pinger

A lightweight Hugging Face Space (or any Docker/server deployment) that
periodically sends HTTP GET requests to your apps and APIs so they never
fall asleep, get recycled, or have their Docker container marked as
unhealthy.

## Features

- **Automatic background pinging** – pings every URL at a configurable
  interval (default: every 5 minutes).
- **Gradio UI** – add URLs on the fly, trigger an instant ping, and inspect
  the live status table.
- **Environment-variable configuration** – set your target URLs and interval
  without touching any code.
- **Zero external dependencies beyond `gradio` and `requests`**.

## Quick Start

### Deploy to Hugging Face Spaces

1. Fork / duplicate this Space.
2. In **Settings → Variables and secrets**, add:
   - `PING_URLS` – comma-separated list of URLs, e.g.
     `https://my-api.railway.app,https://my-app.hf.space`
   - *(optional)* `PING_INTERVAL` – seconds between pings (default `300`)
   - *(optional)* `REQUEST_TIMEOUT` – per-request timeout in seconds
     (default `15`)
3. The Space starts automatically and begins pinging in the background.

### Run Locally

```bash
pip install -r requirements.txt
PING_URLS="https://my-app.example.com" python app.py
```

Open `http://localhost:7860` in your browser.

## Environment Variables

| Variable         | Default | Description                                         |
|------------------|---------|-----------------------------------------------------|
| `PING_URLS`      | *(empty)* | Comma-separated URLs to ping                      |
| `PING_INTERVAL`  | `300`   | Seconds between automatic ping rounds               |
| `REQUEST_TIMEOUT`| `15`    | Seconds to wait for each individual request         |

## How It Works

1. On startup a background daemon thread is spawned that loops forever,
   pinging all registered URLs and then sleeping for `PING_INTERVAL`
   seconds.
2. The Gradio UI lets you add extra URLs at runtime and displays the
   latest status (HTTP code, latency, timestamp) for every URL.
3. Each ping is a plain `GET` request – most server frameworks and reverse
   proxies treat this as normal traffic, which is enough to reset idle
   timers and satisfy Docker `HEALTHCHECK` probes.
