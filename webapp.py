#!/usr/bin/env python3
"""Web front-end for PythonDirBuster.

Serves a single page where you enter a target URL and watch results stream in
live (via Server-Sent Events). Reuses the exact same scan engine as the CLI.

Run:  python webapp.py   ->  http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import json

from flask import Flask, Response, render_template, request, stream_with_context

from pythondirbuster import (
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT,
    DEFAULT_WORDLIST,
    load_wordlist,
    normalize_url,
    scan,
)

app = Flask(__name__)


def category(status: int) -> str:
    if 200 <= status < 300:
        return "found"
    if 300 <= status < 400:
        return "redirect"
    if status in (401, 403):
        return "protected"
    return "other"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.route("/")
def index() -> str:
    return render_template("index.html", defaults={
        "wordlist": DEFAULT_WORDLIST,
        "threads": DEFAULT_THREADS,
        "timeout": DEFAULT_TIMEOUT,
    })


@app.route("/scan")
def scan_stream() -> Response:
    raw_url = request.args.get("url", "").strip()
    wordlist = request.args.get("wordlist", DEFAULT_WORDLIST)
    threads = request.args.get("threads", DEFAULT_THREADS, type=int)
    timeout = request.args.get("timeout", DEFAULT_TIMEOUT, type=float)

    @stream_with_context
    def generate():
        if not raw_url:
            yield sse("error", {"message": "No target URL provided."})
            return

        target = normalize_url(raw_url)
        try:
            words = load_wordlist(wordlist)
        except FileNotFoundError:
            yield sse("error", {"message": f"Wordlist '{wordlist}' not found."})
            return
        if not words:
            yield sse("error", {"message": f"Wordlist '{wordlist}' is empty."})
            return

        total = len(words)
        yield sse("start", {"target": target, "total": total, "threads": threads})

        done = 0
        found = 0
        for result in scan(target, words, threads, timeout):
            done += 1
            if result.ok:
                found += 1
                yield sse("result", {
                    "url": result.url,
                    "status": result.status,
                    "category": category(result.status),
                })
            # Throttle progress updates so we don't flood the stream.
            if done % 10 == 0 or done == total:
                yield sse("progress", {"done": done, "total": total, "found": found})

        yield sse("done", {"done": done, "total": total, "found": found})

    return Response(generate(), mimetype="text/event-stream")


def main() -> None:
    parser = argparse.ArgumentParser(description="PythonDirBuster web front-end.")
    parser.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="port to bind (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="enable Flask debug mode")
    args = parser.parse_args()
    # threaded=True so the SSE stream doesn't block other requests.
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
