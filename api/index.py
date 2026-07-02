"""Vercel serverless entry point for PythonDirBuster.

Unlike the local `webapp.py` (which streams via SSE and scans without limits),
this version runs on a serverless host, so the wordlist and thread count are
capped to fit inside the function timeout (there is no long-lived streaming on
serverless). Scanning is open to any domain.

  ⚠️ This deployment can probe any URL from Vercel's IPs. Anyone who can reach
  it can use it to scan third-party sites (abuse / SSRF surface). Only expose it
  if you're comfortable with that (e.g. put it behind auth), or set ALLOWED_DOMAINS
  again to re-enable the allow-list (see the git history for that variant).

Tune the caps without a redeploy via the MAX_WORDS / MAX_THREADS env vars.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from flask import Flask, jsonify, request

app = Flask(__name__)

# Caps keep each scan inside the function timeout; override via env on Vercel.
# 12k covers admin-panel paths like /boss, /controlpanel, /adminpanel that sit
# deep in the frequency-ordered list. High thread count keeps it inside 60s.
MAX_WORDS = int(os.environ.get("MAX_WORDS", "12000"))
MAX_THREADS = int(os.environ.get("MAX_THREADS", "100"))
REQUEST_TIMEOUT = 4.0

# Depth options the UI exposes. The wordlist is frequency-ordered, so each level
# is a strict superset of the smaller ones (5000 = the 1000 essentials + 4000
# more, 10000 = those + 5000 more). Any request depth is clamped to MAX_WORDS.
DEPTHS = (1000, 5000, 10000)
DEFAULT_DEPTH = 5000

# Wall-clock budget for a scan. Vercel kills the function at maxDuration (60s)
# and returns a 504 with nothing, so we stop early and return partial results.
# Slow / rate-limiting targets simply get as far as this allows.
SCAN_BUDGET = float(os.environ.get("SCAN_BUDGET", "48"))
USER_AGENT = "PythonDirBuster/2.0 (+https://github.com/)"
WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "wordlist.txt")


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def load_words() -> list[str]:
    try:
        with open(WORDLIST_PATH, "r", encoding="utf-8", errors="ignore") as f:
            words = [ln.strip().lstrip("/") for ln in f]
    except FileNotFoundError:
        words = ["admin", "login", "robots.txt", "api", "dashboard", ".git", "config"]
    words = [w for w in words if w and not w.startswith("#")]
    return words[:MAX_WORDS]


def probe(session: requests.Session, base_url: str, word: str) -> dict | None:
    url = urljoin(base_url + "/", word)
    # stream=True fetches only the headers; we never read the body. Sites with
    # heavy 404 pages (tens of KB each) would otherwise make a deep scan download
    # hundreds of MB and blow past the function timeout.
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True)
    except requests.RequestException:
        return None
    try:
        status = resp.status_code
        if 200 <= status < 300:
            category = "found"
        elif 300 <= status < 400:
            category = "redirect"
        elif status in (401, 403):
            category = "protected"
        else:
            return None  # not interesting
        # For redirects, surface where they point so a wall of 301s becomes
        # readable (trailing-slash / http->https / login redirects, not hits).
        location = resp.headers.get("Location") if category == "redirect" else None
    finally:
        resp.close()
    return {"url": url, "status": status, "category": category, "location": location}


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    # Size the connection pool to the thread count. Otherwise urllib3's default
    # pool_maxsize=10 makes 100 threads churn through new TLS handshakes, which
    # dominates the scan time.
    adapter = HTTPAdapter(pool_connections=MAX_THREADS, pool_maxsize=MAX_THREADS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def resolve_base(session: requests.Session, base_url: str):
    """Follow redirects on the root and return (scan_base, rebased).

    Follows up to a few hops using headers only (no body download), so a site
    that 301s the apex to www gets scanned on www instead of returning a wall of
    redirects. ``rebased`` is ``{"from": host, "to": host}`` when the host
    changed, else ``None`` so the caller can tell the user.
    """
    origin = urlparse(base_url)
    url = base_url + "/"
    seen = set()
    for _ in range(5):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True)
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


@app.route("/api/scan")
def scan_endpoint():
    raw_url = request.args.get("url", "").strip()
    if not raw_url:
        return jsonify(error="No target URL provided."), 400

    target = normalize_url(raw_url)
    host = urlparse(target).hostname or ""
    if not host:
        return jsonify(error="Could not parse a hostname from the target URL."), 400

    try:
        depth = int(request.args.get("depth", DEFAULT_DEPTH))
    except ValueError:
        depth = DEFAULT_DEPTH
    if depth not in DEPTHS:
        depth = DEFAULT_DEPTH
    words = load_words()[:depth]
    threads = min(MAX_THREADS, max(1, len(words)))
    session = make_session()

    # Follow redirects on the root first. Sites that 301 the apex to www (or
    # http to https) would otherwise return a wall of 301s and hide the real
    # pages behind them, so we scan wherever the root actually lands.
    target, rebased = resolve_base(session, target)

    results: list[dict] = []
    scanned = 0
    partial = False
    deadline = time.monotonic() + SCAN_BUDGET
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(probe, session, target, w) for w in words]
        try:
            for fut in as_completed(futures):
                hit = fut.result()
                scanned += 1
                if hit:
                    results.append(hit)
                if time.monotonic() >= deadline:
                    partial = True
                    break
        finally:
            # Cancel whatever hasn't started; the pool drains running probes
            # (each bounded by REQUEST_TIMEOUT) as the `with` block exits.
            for fu in futures:
                fu.cancel()

    results.sort(key=lambda r: r["status"])
    return jsonify(target=target, rebased=rebased, scanned=scanned,
                   total=len(words), partial=partial,
                   found=len(results), results=results)


@app.route("/")
@app.route("/pt")
@app.route("/en")
def index():
    # One page; the client picks its language from the path (/pt, /en),
    # localStorage, or the browser locale. See the i18n block in PAGE.
    return PAGE


# Inline SVG mark: a green terminal-style ">_" on a dark rounded tile. Served as
# both /favicon.svg (referenced in <head>) and /favicon.ico (browsers ask for it
# by default; without this route the catch-all rewrite would 404).
FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="8" fill="#141310"/>'
    '<path d="M8 10.5 13 16l-5 5.5" fill="none" stroke="#b6f09c" '
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
    '<rect x="15.5" y="20" width="8.5" height="2.4" rx="1.2" fill="#b6f09c"/>'
    "</svg>"
)


@app.route("/favicon.svg")
@app.route("/favicon.ico")
def favicon():
    return app.response_class(FAVICON, mimetype="image/svg+xml")


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DirBuster by Fassi | web path scanner</title>
<meta name="description" content="A fast, multi-threaded scanner for web directories and files. By Lucas Fassi.">
<meta name="theme-color" content="#141310">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500;600&family=Geist:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg-deep:oklch(12% .007 74);--bg:oklch(15% .008 74);
    --surface:oklch(18.5% .008 74);--surface-2:oklch(22.5% .009 74);
    --line:oklch(32% .01 74/.9);--line-soft:oklch(32% .01 74/.5);--line-strong:oklch(45% .012 74);
    --text:oklch(94% .006 80);--text-dim:oklch(74% .008 80);--text-mute:oklch(56% .008 80);
    --accent:oklch(89% .145 139);--accent-deep:oklch(62% .13 142);--accent-soft:oklch(89% .145 139/.13);--accent-line:oklch(89% .145 139/.4);
    --up:oklch(80% .16 152);--up-soft:oklch(74% .145 152/.16);
    --warn:oklch(83% .13 85);--warn-soft:oklch(83% .13 85/.15);
    --down:oklch(68% .17 24);--down-soft:oklch(66% .17 24/.16);
    --sans:"Geist",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --r:9px;--r-lg:14px;--r-pill:999px;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--bg-deep);color:var(--text);font-family:var(--sans);
    line-height:1.5;-webkit-font-smoothing:antialiased;
    background-image:radial-gradient(120% 90% at 50% -10%,oklch(20% .02 139/.5),transparent 60%);
    background-attachment:fixed}
  a{color:inherit}
  .wrap{max-width:860px;margin:0 auto;padding:1.5rem 1.25rem 4rem}

  /* header */
  header{display:flex;align-items:center;justify-content:space-between;gap:1rem;
    padding:.4rem 0 2.5rem}
  .brand{display:flex;align-items:center;gap:.6rem;font-weight:600;letter-spacing:-.01em}
  .brand svg{width:30px;height:30px;border-radius:8px;flex-shrink:0}
  .brand b{font-weight:600}.brand .dim{color:var(--text-mute);font-weight:500}
  .navtools{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
  nav{display:flex;gap:.4rem}
  .ghost{font-family:var(--mono);font-size:.8rem;color:var(--text-dim);text-decoration:none;
    padding:.4rem .7rem;border:1px solid var(--line-soft);border-radius:var(--r-pill);
    transition:.15s;white-space:nowrap}
  .ghost:hover{color:var(--text);border-color:var(--line-strong);background:var(--surface)}
  .ghost .ar{color:var(--accent-deep);margin-left:.15em}
  /* language switch */
  .lang{display:inline-flex;background:var(--surface);border:1px solid var(--line);
    border-radius:var(--r-pill);padding:2px;font-family:var(--mono);font-size:.74rem}
  .lang button{background:none;border:0;color:var(--text-mute);cursor:pointer;
    padding:.3rem .55rem;border-radius:var(--r-pill);height:auto;font-weight:600;
    letter-spacing:.03em;transition:.15s}
  .lang button:hover{color:var(--text-dim)}
  .lang button[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent)}

  /* hero */
  .hero{margin:0 0 1.75rem}
  h1{font-size:clamp(1.7rem,4vw,2.4rem);line-height:1.1;letter-spacing:-.02em;margin:0 0 .6rem}
  h1 .g{color:var(--accent)}
  .lead{color:var(--text-dim);margin:0;max-width:58ch;font-size:1rem}

  /* scan card */
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);
    padding:1rem;box-shadow:0 1px 0 oklch(100% 0 0/.02) inset,0 12px 30px -18px #000}
  form{display:flex;gap:.6rem;flex-wrap:wrap}
  .field{flex:1 1 300px;display:flex;align-items:center;gap:.5rem;background:var(--bg);
    border:1px solid var(--line);border-radius:var(--r);padding:0 .8rem;transition:.15s}
  .field:focus-within{border-color:var(--accent-line);box-shadow:0 0 0 3px var(--accent-soft)}
  .field .pre{font-family:var(--mono);color:var(--text-mute);font-size:.9rem}
  input{flex:1;background:none;border:0;color:var(--text);font-family:var(--mono);
    font-size:.95rem;padding:.7rem 0;min-width:0}
  input:focus{outline:none}input::placeholder{color:var(--text-mute)}
  button{background:var(--accent);color:oklch(22% .03 145);border:0;border-radius:var(--r);
    padding:0 1.5rem;font-family:var(--sans);font-size:.95rem;font-weight:600;cursor:pointer;
    height:44px;transition:.12s;letter-spacing:-.01em}
  button:hover:not(:disabled){filter:brightness(1.06);transform:translateY(-1px)}
  button:active:not(:disabled){transform:translateY(1px)}
  button:disabled{opacity:.55;cursor:progress}
  /* depth selector */
  .opts{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin:.85rem 0 0}
  .opts .lbl{font-size:.78rem;color:var(--text-mute)}
  .seg{display:inline-flex;background:var(--bg);border:1px solid var(--line);
    border-radius:var(--r-pill);padding:2px}
  .seg button{background:none;border:0;color:var(--text-mute);cursor:pointer;height:auto;
    font-family:var(--mono);font-size:.78rem;font-weight:600;padding:.34rem .7rem;
    border-radius:var(--r-pill);transition:.15s;letter-spacing:.02em}
  .seg button:hover{color:var(--text-dim);transform:none;filter:none}
  .seg button[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent)}

  /* toolbar / summary */
  .bar{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;
    margin:1.5rem 0 .5rem;min-height:1.4em}
  .chips{display:flex;gap:.4rem;flex-wrap:wrap;font-family:var(--mono);font-size:.78rem}
  .chip{color:var(--text-dim)}
  .chip b{color:var(--text);font-weight:600}
  .chip.f b{color:var(--up)}.chip.r b{color:var(--warn)}.chip.p b{color:var(--down)}
  .muted{color:var(--text-mute);font-family:var(--mono);font-size:.8rem}
  .toggle{display:inline-flex;align-items:center;gap:.45rem;cursor:pointer;
    color:var(--text-dim);font-size:.8rem;user-select:none}
  .toggle input{appearance:none;width:34px;height:19px;border-radius:var(--r-pill);
    background:var(--surface-2);border:1px solid var(--line);position:relative;cursor:pointer;transition:.15s;flex-shrink:0}
  .toggle input::after{content:"";position:absolute;top:2px;left:2px;width:13px;height:13px;
    border-radius:50%;background:var(--text-mute);transition:.15s}
  .toggle input:checked{background:var(--accent-soft);border-color:var(--accent-line)}
  .toggle input:checked::after{left:16px;background:var(--accent)}

  /* results */
  ul{list-style:none;padding:0;margin:.5rem 0 0;display:flex;flex-direction:column;gap:.4rem}
  .row{display:flex;align-items:center;gap:.75rem;padding:.6rem .8rem;border:1px solid var(--line);
    border-radius:var(--r);background:var(--surface);transition:.15s;flex-wrap:wrap;
    animation:rise .25s ease both}
  @keyframes rise{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
  .row:hover{border-color:var(--line-strong);background:var(--surface-2)}
  .badge{font-family:var(--mono);font-weight:600;font-size:.78rem;padding:.2rem .5rem;
    border-radius:6px;flex-shrink:0;min-width:44px;text-align:center;letter-spacing:.02em}
  .found .badge{background:var(--up-soft);color:var(--up)}
  .redirect .badge{background:var(--warn-soft);color:var(--warn)}
  .protected .badge{background:var(--down-soft);color:var(--down)}
  .u{font-family:var(--mono);font-size:.88rem;text-decoration:none;color:var(--text);
    word-break:break-all;flex:1 1 auto}
  .u:hover{color:var(--accent)}
  .loc{font-family:var(--mono);font-size:.78rem;color:var(--text-mute);word-break:break-all}
  .empty{color:var(--text-mute);font-family:var(--mono);font-size:.85rem;padding:.5rem 0}
  .note{font-family:var(--mono);font-size:.8rem;color:var(--accent-deep);margin:.25rem 0 .75rem;
    background:var(--accent-soft);border:1px solid var(--accent-line);border-radius:var(--r);
    padding:.55rem .75rem;word-break:break-all}
  /* skeleton loader (matches result-row shape) */
  .sk{height:41px;border:1px solid var(--line);border-radius:var(--r);
    background:linear-gradient(100deg,var(--surface) 30%,var(--surface-2) 50%,var(--surface) 70%);
    background-size:220% 100%;animation:shim 1.15s linear infinite}
  @keyframes shim{from{background-position:180% 0}to{background-position:-40% 0}}
  .error{color:var(--down);font-family:var(--mono);font-size:.85rem;margin-top:1rem;
    background:var(--down-soft);border:1px solid oklch(66% .17 24/.3);border-radius:var(--r);padding:.7rem .8rem}
  .hint{color:var(--text-mute);font-size:.78rem;margin:.75rem 0 0;line-height:1.55}
  .hint code{font-family:var(--mono);color:var(--text-dim)}

  /* products */
  .more{margin-top:3.5rem;padding-top:2rem;border-top:1px solid var(--line-soft)}
  .more h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--text-mute);
    font-weight:600;margin:0 0 1rem}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
  @media(max-width:560px){.grid{grid-template-columns:1fr}}
  .prod{display:block;text-decoration:none;background:var(--surface);border:1px solid var(--line);
    border-radius:var(--r-lg);padding:1rem 1.1rem;transition:.15s}
  .prod:hover{border-color:var(--accent-line);background:var(--surface-2);transform:translateY(-2px)}
  .prod .top{display:flex;align-items:center;justify-content:space-between}
  .prod .name{font-family:var(--mono);font-weight:600;color:var(--text)}
  .prod .ar{color:var(--accent);transition:.15s}
  .prod:hover .ar{transform:translate(2px,-2px)}
  .prod .desc{color:var(--text-dim);font-size:.85rem;margin:.35rem 0 0}

  footer{margin-top:2.5rem;color:var(--text-mute);font-size:.8rem;
    display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap}
  footer a{color:var(--text-dim);text-decoration:none}footer a:hover{color:var(--accent)}

  @media(prefers-reduced-motion:reduce){
    *{animation:none!important;transition:none!important}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="brand">
      <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#141310"/><path d="M8 10.5 13 16l-5 5.5" fill="none" stroke="#b6f09c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="15.5" y="20" width="8.5" height="2.4" rx="1.2" fill="#b6f09c"/></svg>
      <b>DirBuster</b><span class="dim">by Fassi</span>
    </span>
    <div class="navtools">
      <nav>
        <a class="ghost" href="https://fassi.dev" target="_blank" rel="noopener">fassi.dev<span class="ar">&#8599;</span></a>
        <a class="ghost" href="https://invest.fassi.dev" target="_blank" rel="noopener">invest<span class="ar">&#8599;</span></a>
      </nav>
      <div class="lang" role="group" aria-label="Language">
        <button type="button" data-lang="en">EN</button>
        <button type="button" data-lang="pt">PT</button>
      </div>
    </div>
  </header>

  <section class="hero">
    <h1 data-i18n-html="h1"></h1>
    <p class="lead" data-i18n="lead"></p>
  </section>

  <div class="card">
    <form id="f">
      <label class="field">
        <span class="pre">https://</span>
        <input id="url" placeholder="example.com" autocomplete="off" autocapitalize="off" spellcheck="false" required>
      </label>
      <button id="btn" type="submit" data-i18n="scan"></button>
    </form>
    <div class="opts">
      <span class="lbl" data-i18n="depthLabel"></span>
      <div class="seg" id="depth" role="group" aria-label="Scan depth">
        <button type="button" data-depth="1000">1000</button>
        <button type="button" data-depth="5000">5000</button>
        <button type="button" data-depth="10000">10000</button>
      </div>
    </div>
    <p class="hint" data-i18n-html="hint"></p>
  </div>

  <div class="bar">
    <div class="chips" id="chips"><span class="muted" id="status" data-i18n="ready"></span></div>
    <label class="toggle" id="reWrap" hidden><input type="checkbox" id="hideRe"> <span data-i18n="hideRedirects"></span></label>
  </div>
  <p class="note" id="note" hidden></p>
  <ul id="results"></ul>
  <p class="error" id="error" hidden></p>

  <section class="more">
    <h2 data-i18n="moreTitle"></h2>
    <div class="grid">
      <a class="prod" href="https://fassi.dev" target="_blank" rel="noopener">
        <div class="top"><span class="name">fassi.dev</span><span class="ar">&#8599;</span></div>
        <p class="desc" data-i18n="prodPortfolio"></p>
      </a>
      <a class="prod" href="https://invest.fassi.dev" target="_blank" rel="noopener">
        <div class="top"><span class="name">invest.fassi.dev</span><span class="ar">&#8599;</span></div>
        <p class="desc" data-i18n="prodInvest"></p>
      </a>
    </div>
  </section>

  <footer>
    <span data-i18n-html="builtBy"></span>
    <a href="https://github.com/sh4wty1/PythonDirBuster" target="_blank" rel="noopener"><span data-i18n="source"></span> &#8599;</a>
  </footer>
</div>

<script>
const $=id=>document.getElementById(id);
const f=$("f"),btn=$("btn"),urlEl=$("url"),chips=$("chips"),note=$("note"),
  results=$("results"),errorEl=$("error"),reWrap=$("reWrap"),hideRe=$("hideRe");
let data=null,scanning=false;

const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---- i18n ---- */
const T={
  en:{
    h1:'Find the <span class="g">hidden paths</span> on any site.',
    lead:"A fast, multi-threaded scanner for web directories and files. Enter a target and probe it against thousands of common paths. Only scan what you're authorized to test.",
    scan:"Scan",scanning:"Scanning\\u2026",
    depthLabel:"Paths to probe (deeper is slower):",
    hint:'Probes <code>TARGET/path</code> for each word in the list and reports what exists: <b style="color:var(--up)">2xx found</b>, <b style="color:var(--warn)">3xx redirect</b>, <b style="color:var(--down)">401/403 protected</b>. Redirects show where they point. A wall of <code>301</code>s usually means the server sends every unknown path to the same place (login, HTTPS, or a trailing slash).',
    ready:"Ready.",busy:"Scanning\\u2026 this can take a few seconds.",errored:"Error.",
    hideRedirects:"hide redirects",
    scanned:"scanned",found:"found",redirects:"redirects",protected:"protected",
    none:"No interesting paths found.",filtered:"All results hidden by the filter.",
    moreTitle:"More from Lucas Fassi",
    prodPortfolio:"Portfolio and software. Who I am and what I build.",
    prodInvest:"Investment analysis and market dashboards.",
    builtBy:'Built by <a href="https://fassi.dev" target="_blank" rel="noopener">Lucas Fassi</a>',
    source:"Source on GitHub"
  },
  pt:{
    h1:'Encontre os <span class="g">caminhos escondidos</span> de qualquer site.',
    lead:"Um scanner rápido e multi-thread de diretórios e arquivos web. Digite um alvo e teste contra milhares de caminhos comuns. Escaneie apenas o que você tem autorização para testar.",
    scan:"Escanear",scanning:"Escaneando\\u2026",
    depthLabel:"Caminhos a testar (mais fundo, mais lento):",
    hint:'Testa <code>ALVO/caminho</code> para cada palavra da lista e reporta o que existe: <b style="color:var(--up)">2xx encontrado</b>, <b style="color:var(--warn)">3xx redireciona</b>, <b style="color:var(--down)">401/403 protegido</b>. Os redirecionamentos mostram para onde apontam. Um monte de <code>301</code> geralmente significa que o servidor manda todo caminho desconhecido para o mesmo lugar (login, HTTPS ou barra no final).',
    ready:"Pronto.",busy:"Escaneando\\u2026 pode levar alguns segundos.",errored:"Erro.",
    hideRedirects:"ocultar redirecionamentos",
    scanned:"escaneados",found:"encontrados",redirects:"redirecionam.",protected:"protegidos",
    none:"Nenhum caminho interessante encontrado.",filtered:"Todos os resultados ocultados pelo filtro.",
    moreTitle:"Mais do Lucas Fassi",
    prodPortfolio:"Portfólio e software. Quem eu sou e o que eu construo.",
    prodInvest:"Análises de investimento e painéis de mercado.",
    builtBy:'Feito por <a href="https://fassi.dev" target="_blank" rel="noopener">Lucas Fassi</a>',
    source:"Código no GitHub"
  }
};

function pickLang(){
  const p=location.pathname.replace(/\\/+$/,"");
  if(p==="/pt")return "pt";
  if(p==="/en")return "en";
  const saved=localStorage.getItem("lang");
  if(saved==="pt"||saved==="en")return saved;
  return (navigator.language||"").toLowerCase().startsWith("pt")?"pt":"en";
}
let lang=pickLang();

function t(k){return (T[lang]&&T[lang][k])||T.en[k]||k;}

function applyLang(){
  document.documentElement.lang=lang;
  for(const el of document.querySelectorAll("[data-i18n]"))el.textContent=t(el.dataset.i18n);
  for(const el of document.querySelectorAll("[data-i18n-html]"))el.innerHTML=t(el.dataset.i18nHtml);
  for(const b of document.querySelectorAll(".lang button"))
    b.setAttribute("aria-pressed",String(b.dataset.lang===lang));
  if(!scanning)btn.textContent=t("scan");
  if(data){summarize();render();}
}

function setLang(l){
  lang=l;localStorage.setItem("lang",l);
  history.replaceState(null,"",l==="pt"?"/pt":"/");
  applyLang();
}
for(const b of document.querySelectorAll(".lang button"))
  b.addEventListener("click",()=>setLang(b.dataset.lang));

/* ---- scan depth ---- */
const DEPTHS=[1000,5000,10000];
let depth=parseInt(localStorage.getItem("depth"),10);
if(!DEPTHS.includes(depth))depth=5000;
const depthBtns=document.querySelectorAll("#depth button");
function applyDepth(){
  for(const b of depthBtns)b.setAttribute("aria-pressed",String(parseInt(b.dataset.depth,10)===depth));
}
for(const b of depthBtns)b.addEventListener("click",()=>{
  depth=parseInt(b.dataset.depth,10);localStorage.setItem("depth",depth);applyDepth();
});
applyDepth();

/* ---- rendering ---- */
function render(){
  results.innerHTML="";
  if(!data)return;
  const hide=hideRe.checked;let shown=0;
  for(const it of data.results){
    if(hide&&it.category==="redirect")continue;
    shown++;
    const li=document.createElement("li");
    li.className="row "+it.category;
    const loc=it.location?`<span class="loc">&#8594; ${esc(it.location)}</span>`:"";
    li.innerHTML=`<span class="badge">${it.status}</span>`+
      `<a class="u" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.url)}</a>`+loc;
    results.appendChild(li);
  }
  if(shown===0){
    const li=document.createElement("li");li.className="empty";
    li.textContent=data.results.length?t("filtered"):t("none");
    results.appendChild(li);
  }
}

function summarize(){
  const c={found:0,redirect:0,protected:0};
  for(const it of data.results)c[it.category]=(c[it.category]||0)+1;
  chips.innerHTML=
    `<span class="chip">${t("scanned")} <b>${data.scanned}</b></span>`+
    `<span class="chip f">${t("found")} <b>${c.found}</b></span>`+
    `<span class="chip r">${t("redirects")} <b>${c.redirect}</b></span>`+
    `<span class="chip p">${t("protected")} <b>${c.protected}</b></span>`;
  reWrap.hidden=c.redirect===0;
  const msgs=[];
  if(data.rebased){
    const {from,to}=data.rebased;
    msgs.push(lang==="pt"
      ?`${from} redireciona para ${to}. Escaneando ${to}.`
      :`${from} redirects to ${to}. Scanning ${to}.`);
  }
  if(data.partial){
    msgs.push(lang==="pt"
      ?`Parou no limite de tempo: ${data.scanned} de ${data.total} caminhos. Esse alvo responde devagar. Use uma profundidade menor, ou o CLI local para um scan completo.`
      :`Stopped at the time limit: ${data.scanned} of ${data.total} paths. This target responds slowly. Pick a smaller depth, or use the local CLI for a full scan.`);
  }
  if(msgs.length){note.hidden=false;note.innerHTML=msgs.map(esc).join("<br>");}
  else note.hidden=true;
}

function skeleton(){
  results.innerHTML="";
  for(let i=0;i<6;i++){
    const li=document.createElement("li");li.className="sk";
    li.style.width=(72+((i*13)%26))+"%";
    results.appendChild(li);
  }
}

hideRe.addEventListener("change",render);

f.addEventListener("submit",async e=>{
  e.preventDefault();
  data=null;errorEl.hidden=true;reWrap.hidden=true;note.hidden=true;
  scanning=true;btn.disabled=true;btn.textContent=t("scanning");
  chips.innerHTML=`<span class="muted">${t("busy")}</span>`;
  skeleton();
  try{
    const r=await fetch("/api/scan?url="+encodeURIComponent(urlEl.value)+"&depth="+depth);
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||"Request failed.");
    data=d;summarize();render();
  }catch(err){
    results.innerHTML="";
    chips.innerHTML=`<span class="muted">${t("errored")}</span>`;
    errorEl.textContent=err.message;errorEl.hidden=false;
  }finally{
    scanning=false;btn.disabled=false;btn.textContent=t("scan");
  }
});

applyLang();
</script>
</body>
</html>"""
