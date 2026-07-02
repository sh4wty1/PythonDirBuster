#!/usr/bin/env python3
"""PythonDirBuster - a small, multi-threaded web directory/file brute-forcer.

Given a target URL and a wordlist, it requests every ``TARGET/word`` path and
reports the ones that look interesting (found, redirected, or protected).
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter

DEFAULT_WORDLIST = "wordlist.txt"
DEFAULT_THREADS = 20
DEFAULT_TIMEOUT = 5.0
USER_AGENT = "PythonDirBuster/2.0 (+https://github.com/)"


# --- Terminal colors ---------------------------------------------------------
# Self-contained ANSI colors so we don't depend on a third-party color library.
class Color:
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    PURPLE = "\033[35m"
    GREY = "\033[90m"

    _enabled: bool = True

    @classmethod
    def paint(cls, text: str, color: str) -> str:
        if not cls._enabled:
            return text
        return f"{color}{text}{cls.RESET}"

    @classmethod
    def setup(cls, use_color: bool) -> None:
        # Honor --no-color, non-tty output, and the NO_COLOR convention.
        cls._enabled = use_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ
        if cls._enabled and os.name == "nt":
            # Enable ANSI escape processing on legacy Windows terminals.
            os.system("")


BANNER = r"""
  _____       _   _                   _____  _      _               _
 |  __ \     | | | |                 |  __ \(_)    | |             | |
 | |__) |   _| |_| |__   ___  _ __   | |  | |_ _ __| |__  _   _ ___| |_
 |  ___/ | | | __| '_ \ / _ \| '_ \  | |  | | | '__| '_ \| | | / __| __|
 | |   | |_| | |_| | | | (_) | | | | | |__| | | |  | |_) | |_| \__ \ |_
 |_|    \__, |\__|_| |_|\___/|_| |_| |_____/|_|_|  |_.__/ \__,_|___/\__|
         __/ |
        |___/
"""


@dataclass
class Result:
    url: str
    status: int
    ok: bool  # worth showing to the user


def show_banner() -> None:
    print(Color.paint(BANNER, Color.PURPLE))
    print(Color.paint("Coded by @nglshawty1 :)", Color.PURPLE))


def normalize_url(url: str) -> str:
    """Add a scheme if missing and strip trailing slashes for clean joins."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def load_wordlist(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="ignore") as file:
        words = []
        for line in file:
            word = line.strip().lstrip("/")
            if word and not word.startswith("#"):
                words.append(word)
    return words


def resolve_base(base_url: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, dict | None]:
    """Follow redirects on the root so scanning an apex that 301s to www lands
    on www (otherwise every path just comes back as a redirect to www).

    Returns ``(scan_base, rebased)`` where ``rebased`` is ``{"from", "to"}`` when
    the host changed, else ``None``. Uses headers only, so nothing is downloaded.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    origin = urlparse(base_url)
    url = base_url + "/"
    seen: set[str] = set()
    for _ in range(5):
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=False, stream=True)
        except requests.RequestException:
            break
        try:
            status, location = resp.status_code, resp.headers.get("Location")
        finally:
            resp.close()
        if not (300 <= status < 400 and location):
            break
        nxt = urljoin(url, location)
        if nxt in seen:
            break
        seen.add(nxt)
        url = nxt
    final = urlparse(url)
    if not final.hostname:
        return base_url, None
    scan_base = f"{final.scheme}://{final.netloc}"
    if final.netloc.lower() != origin.netloc.lower():
        return scan_base, {"from": origin.netloc, "to": final.netloc}
    return base_url, None


def probe(session: requests.Session, base_url: str, word: str, timeout: float) -> Result:
    """Request a single path and classify the response."""
    url = urljoin(base_url + "/", word)
    # stream=True fetches only headers; we never read the body, so targets with
    # heavy 404 pages don't make a deep scan download hundreds of MB.
    try:
        response = session.get(url, timeout=timeout, allow_redirects=False, stream=True)
    except requests.RequestException:
        return Result(url, 0, ok=False)
    try:
        status = response.status_code
    finally:
        response.close()

    # 2xx = found, 3xx = redirect, 401/403 = exists but protected: all interesting.
    interesting = (200 <= status < 400) or status in (401, 403)
    return Result(url, status, ok=interesting)


def report(result: Result) -> None:
    if result.status == 0:
        return  # connection error, stay quiet
    if 200 <= result.status < 300:
        color = Color.GREEN
    elif 300 <= result.status < 400:
        color = Color.YELLOW
    else:  # 401 / 403
        color = Color.RED
    print(Color.paint(f"[{result.status}] {result.url}", color))


def scan(
    target_url: str,
    words: list[str],
    threads: int = DEFAULT_THREADS,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[Result]:
    """Probe every path concurrently, yielding each ``Result`` as it completes.

    This is the shared engine used by both the CLI and the web app.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    # Size the connection pool to the thread count so we reuse keep-alive
    # connections instead of churning through a new TLS handshake per request
    # (urllib3's default pool_maxsize is 10).
    adapter = HTTPAdapter(pool_connections=threads, pool_maxsize=threads)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(probe, session, target_url, word, timeout) for word in words]
        for future in as_completed(futures):
            yield future.result()


def run_dirbuster(target_url: str, words: list[str], threads: int, timeout: float) -> list[Result]:
    total = len(words)
    print(Color.paint(f"\nScanning {target_url} with {total} paths using {threads} threads...\n", Color.PURPLE))

    found: list[Result] = []
    done = 0
    try:
        for result in scan(target_url, words, threads, timeout):
            done += 1
            if result.ok:
                report(result)
                found.append(result)
            # Lightweight progress indicator on the same line.
            print(Color.paint(f"  progress: {done}/{total}", Color.GREY), end="\r", flush=True)
    except KeyboardInterrupt:
        print(Color.paint("\n\nInterrupted by user.", Color.YELLOW))

    print(" " * 40, end="\r")  # clear the progress line
    return found


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A small multi-threaded web directory/file brute-forcer.",
    )
    parser.add_argument("url", nargs="?", help="target URL (prompted if omitted)")
    parser.add_argument("-w", "--wordlist", default=DEFAULT_WORDLIST, help=f"wordlist path (default: {DEFAULT_WORDLIST})")
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS, help=f"concurrent requests (default: {DEFAULT_THREADS})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument("--no-follow", action="store_true", help="don't follow root redirects (scan the exact host, e.g. apex instead of www)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    Color.setup(use_color=not args.no_color)

    show_banner()

    target = args.url or input(Color.paint("Enter the target URL -> ", Color.PURPLE))
    target = normalize_url(target)
    if not target:
        print(Color.paint("No target URL provided.", Color.RED))
        return 1

    try:
        words = load_wordlist(args.wordlist)
    except FileNotFoundError:
        print(Color.paint(f"Wordlist '{args.wordlist}' not found.", Color.RED))
        return 1

    if not words:
        print(Color.paint(f"Wordlist '{args.wordlist}' is empty.", Color.RED))
        return 1

    # Follow root redirects so scanning an apex that 301s to www hits www.
    if not args.no_follow:
        target, rebased = resolve_base(target, args.timeout)
        if rebased:
            print(Color.paint(
                f"{rebased['from']} redirects to {rebased['to']}; scanning {rebased['to']}.",
                Color.YELLOW,
            ))

    found = run_dirbuster(target, words, args.threads, args.timeout)

    summary = f"\nDone. {len(found)} interesting path(s) found."
    print(Color.paint(summary, Color.GREEN if found else Color.YELLOW))
    return 0


if __name__ == "__main__":
    sys.exit(main())
