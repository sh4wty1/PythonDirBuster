"""Vercel serverless entry point for PythonDirBuster (safe demo mode).

Unlike the local `webapp.py` (which streams via SSE and scans without limits),
this version is built for a public serverless host, so it is deliberately
constrained:

  * It only scans domains listed in the ALLOWED_DOMAINS env var (comma-separated).
    With none set, scanning is disabled entirely. This stops your deployment from
    being used to attack arbitrary third-party sites.
  * The wordlist and thread count are capped so a scan finishes within the
    function timeout (there is no long-lived streaming on serverless).

Set on Vercel:  ALLOWED_DOMAINS = yourdomain.com,staging.yourdomain.com
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

MAX_WORDS = 150          # keep the scan inside the function timeout
MAX_THREADS = 50
REQUEST_TIMEOUT = 4.0
USER_AGENT = "PythonDirBuster/2.0 (+https://github.com/)"
WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "wordlist.txt")


def allowed_domains() -> list[str]:
    raw = os.environ.get("ALLOWED_DOMAINS", "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def host_is_allowed(host: str, allow: list[str]) -> bool:
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in allow)


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
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        return None
    status = resp.status_code
    if 200 <= status < 300:
        category = "found"
    elif 300 <= status < 400:
        category = "redirect"
    elif status in (401, 403):
        category = "protected"
    else:
        return None  # not interesting
    return {"url": url, "status": status, "category": category}


@app.route("/api/scan")
def scan_endpoint():
    raw_url = request.args.get("url", "").strip()
    if not raw_url:
        return jsonify(error="No target URL provided."), 400

    target = normalize_url(raw_url)
    host = urlparse(target).hostname or ""

    allow = allowed_domains()
    if not allow:
        return jsonify(error="Scanning is disabled. Set the ALLOWED_DOMAINS env var on the server."), 403
    if not host_is_allowed(host, allow):
        return jsonify(error=f"Domain '{host}' is not in this deployment's allow-list."), 403

    words = load_words()
    threads = min(MAX_THREADS, max(1, len(words)))
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(probe, session, target, w) for w in words]
        for fut in as_completed(futures):
            hit = fut.result()
            if hit:
                results.append(hit)

    results.sort(key=lambda r: r["status"])
    return jsonify(target=target, scanned=len(words), found=len(results), results=results)


@app.route("/")
def index():
    return PAGE


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PythonDirBuster</title>
<style>
  :root{--bg:#0f1117;--panel:#1a1d27;--border:#2a2e3a;--text:#e6e6e6;--muted:#8a90a2;
    --accent:#a06bff;--found:#38d66b;--redirect:#f2c94c;--protected:#ff6b6b;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:ui-monospace,Menlo,Consolas,monospace;padding:2rem 1rem}
  .wrap{max-width:820px;margin:0 auto}
  h1{font-size:1.4rem;margin:0 0 .25rem}h1 .s{color:var(--accent)}
  .sub{color:var(--muted);margin:0 0 1.5rem;font-size:.85rem}
  form{display:flex;gap:.75rem;flex-wrap:wrap;background:var(--panel);
    border:1px solid var(--border);border-radius:10px;padding:1rem}
  input{background:#0d0f16;border:1px solid var(--border);color:var(--text);
    border-radius:7px;padding:.6rem .8rem;font:inherit;flex:1 1 320px}
  input:focus{outline:none;border-color:var(--accent)}
  button{background:var(--accent);color:#fff;border:0;border-radius:7px;
    padding:0 1.4rem;font:inherit;font-weight:600;cursor:pointer;height:42px}
  button:disabled{opacity:.5;cursor:not-allowed}
  .status{margin:1.25rem 0 .5rem;color:var(--muted);font-size:.82rem;min-height:1.2em}
  ul{list-style:none;padding:0;margin:1rem 0 0}
  li{display:flex;align-items:center;gap:.75rem;padding:.55rem .75rem;
    border:1px solid var(--border);border-radius:7px;margin-bottom:.5rem;
    background:var(--panel);word-break:break-all}
  .badge{font-weight:700;font-size:.78rem;padding:.15rem .5rem;border-radius:5px;
    flex-shrink:0;min-width:42px;text-align:center}
  .found .badge{background:rgba(56,214,107,.15);color:var(--found)}
  .redirect .badge{background:rgba(242,201,76,.15);color:var(--redirect)}
  .protected .badge{background:rgba(255,107,107,.15);color:var(--protected)}
  a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
  .error{color:var(--protected);font-size:.85rem;margin-top:1rem}
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="s">&#9876;&#65039;</span> PythonDirBuster</h1>
  <p class="sub">Demo mode &mdash; only allow-listed domains can be scanned.</p>
  <form id="f">
    <input id="url" placeholder="yourdomain.com" autocomplete="off" required>
    <button id="btn" type="submit">Scan</button>
  </form>
  <div class="status" id="status">Ready.</div>
  <ul id="results"></ul>
  <p class="error" id="error" hidden></p>
</div>
<script>
const f=document.getElementById("f"),btn=document.getElementById("btn"),
  statusEl=document.getElementById("status"),results=document.getElementById("results"),
  errorEl=document.getElementById("error");
f.addEventListener("submit",async(e)=>{
  e.preventDefault();
  results.innerHTML="";errorEl.hidden=true;
  btn.disabled=true;btn.textContent="Scanning\\u2026";statusEl.textContent="Scanning\\u2026";
  try{
    const url=document.getElementById("url").value;
    const r=await fetch("/api/scan?url="+encodeURIComponent(url));
    const d=await r.json();
    if(!r.ok){throw new Error(d.error||"Request failed.");}
    statusEl.textContent=`Scanned ${d.scanned} paths on ${d.target} \\u2014 ${d.found} found.`;
    for(const it of d.results){
      const li=document.createElement("li");li.className=it.category;
      li.innerHTML=`<span class="badge">${it.status}</span>`+
        `<a href="${it.url}" target="_blank" rel="noopener">${it.url}</a>`;
      results.appendChild(li);
    }
  }catch(err){
    errorEl.textContent=err.message;errorEl.hidden=false;statusEl.textContent="Error.";
  }finally{
    btn.disabled=false;btn.textContent="Scan";
  }
});
</script>
</body>
</html>"""
