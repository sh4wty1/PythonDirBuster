"""Vercel serverless entry point for PythonDirBuster.

Unlike the local `webapp.py` (which streams via SSE and scans without limits),
this version runs on a serverless host, so the wordlist and thread count are
capped to fit inside the function timeout (there is no long-lived streaming on
serverless). Scanning is open to any domain.

  ⚠️ This deployment can probe any URL from Vercel's IPs. Anyone who can reach
  it can use it to scan third-party sites (abuse / SSRF surface). Only expose it
  if you're comfortable with that — e.g. put it behind auth, or set ALLOWED_DOMAINS
  again to re-enable the allow-list (see the git history for that variant).

Tune the caps without a redeploy via the MAX_WORDS / MAX_THREADS env vars.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# Caps keep each scan inside the function timeout; override via env on Vercel.
MAX_WORDS = int(os.environ.get("MAX_WORDS", "1000"))
MAX_THREADS = int(os.environ.get("MAX_THREADS", "50"))
REQUEST_TIMEOUT = 4.0
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
    # For redirects, surface where they point so a wall of 301s becomes readable
    # (most are trailing-slash / http->https / login redirects, not real hits).
    location = resp.headers.get("Location") if category == "redirect" else None
    return {"url": url, "status": status, "category": category, "location": location}


@app.route("/api/scan")
def scan_endpoint():
    raw_url = request.args.get("url", "").strip()
    if not raw_url:
        return jsonify(error="No target URL provided."), 400

    target = normalize_url(raw_url)
    host = urlparse(target).hostname or ""
    if not host:
        return jsonify(error="Could not parse a hostname from the target URL."), 400

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
<title>PythonDirBuster — web path scanner</title>
<meta name="description" content="A fast, multi-threaded web directory & file scanner. By Lucas Fassi.">
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
  nav{display:flex;gap:.4rem;flex-wrap:wrap}
  .ghost{font-family:var(--mono);font-size:.8rem;color:var(--text-dim);text-decoration:none;
    padding:.4rem .7rem;border:1px solid var(--line-soft);border-radius:var(--r-pill);
    transition:.15s;white-space:nowrap}
  .ghost:hover{color:var(--text);border-color:var(--line-strong);background:var(--surface)}
  .ghost .ar{color:var(--accent-deep);margin-left:.15em}

  /* hero */
  .hero{margin:0 0 1.75rem}
  h1{font-size:clamp(1.7rem,4vw,2.4rem);line-height:1.1;letter-spacing:-.02em;margin:0 0 .6rem}
  h1 .g{color:var(--accent)}
  .lead{color:var(--text-dim);margin:0;max-width:56ch;font-size:1rem}

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
    height:44px;transition:.15s;letter-spacing:-.01em}
  button:hover:not(:disabled){filter:brightness(1.06);transform:translateY(-1px)}
  button:disabled{opacity:.55;cursor:progress}

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
    border-radius:var(--r);background:var(--surface);transition:.15s;flex-wrap:wrap}
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
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="brand">
      <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#141310"/><path d="M8 10.5 13 16l-5 5.5" fill="none" stroke="#b6f09c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="15.5" y="20" width="8.5" height="2.4" rx="1.2" fill="#b6f09c"/></svg>
      <b>DirBuster</b><span class="dim">by Fassi</span>
    </span>
    <nav>
      <a class="ghost" href="https://fassi.dev" target="_blank" rel="noopener">fassi.dev<span class="ar">&#8599;</span></a>
      <a class="ghost" href="https://invest.fassi.dev" target="_blank" rel="noopener">invest<span class="ar">&#8599;</span></a>
    </nav>
  </header>

  <section class="hero">
    <h1>Find the <span class="g">hidden paths</span> on any site.</h1>
    <p class="lead">A fast, multi-threaded web directory &amp; file scanner. Enter a target and probe it against thousands of common paths &mdash; only scan what you're authorized to test.</p>
  </section>

  <div class="card">
    <form id="f">
      <label class="field">
        <span class="pre">https://</span>
        <input id="url" placeholder="example.com" autocomplete="off" autocapitalize="off" spellcheck="false" required>
      </label>
      <button id="btn" type="submit">Scan</button>
    </form>
    <p class="hint">Probes <code>TARGET/path</code> for each word in the list and reports what exists:
      <b style="color:var(--up)">2xx found</b>, <b style="color:var(--warn)">3xx redirect</b>, <b style="color:var(--down)">401/403 protected</b>.
      Redirects show where they point &mdash; a wall of <code>301</code>s usually means the server sends every unknown path to one place (login, HTTPS, or a trailing slash).</p>
  </div>

  <div class="bar">
    <div class="chips" id="chips"><span class="muted" id="status">Ready.</span></div>
    <label class="toggle" id="reWrap" hidden><input type="checkbox" id="hideRe"> hide redirects</label>
  </div>
  <ul id="results"></ul>
  <p class="error" id="error" hidden></p>

  <section class="more">
    <h2>More from Lucas Fassi</h2>
    <div class="grid">
      <a class="prod" href="https://fassi.dev" target="_blank" rel="noopener">
        <div class="top"><span class="name">fassi.dev</span><span class="ar">&#8599;</span></div>
        <p class="desc">Portfolio &amp; software &mdash; who I am and what I build.</p>
      </a>
      <a class="prod" href="https://invest.fassi.dev" target="_blank" rel="noopener">
        <div class="top"><span class="name">invest.fassi.dev</span><span class="ar">&#8599;</span></div>
        <p class="desc">Investment analysis &amp; market dashboards.</p>
      </a>
    </div>
  </section>

  <footer>
    <span>Built by <a href="https://fassi.dev" target="_blank" rel="noopener">Lucas Fassi</a></span>
    <a href="https://github.com/sh4wty1/PythonDirBuster" target="_blank" rel="noopener">Source on GitHub &#8599;</a>
  </footer>
</div>

<script>
const $=id=>document.getElementById(id);
const f=$("f"),btn=$("btn"),urlEl=$("url"),statusEl=$("status"),chips=$("chips"),
  results=$("results"),errorEl=$("error"),reWrap=$("reWrap"),hideRe=$("hideRe");
let data=null;

const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function render(){
  results.innerHTML="";
  if(!data){return;}
  const hide=hideRe.checked;
  let shown=0;
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
    li.textContent=data.results.length?"All results hidden by the filter.":"No interesting paths found.";
    results.appendChild(li);
  }
}

function summarize(){
  const c={found:0,redirect:0,protected:0};
  for(const it of data.results)c[it.category]=(c[it.category]||0)+1;
  chips.innerHTML=
    `<span class="chip">scanned <b>${data.scanned}</b></span>`+
    `<span class="chip f">found <b>${c.found}</b></span>`+
    `<span class="chip r">redirects <b>${c.redirect}</b></span>`+
    `<span class="chip p">protected <b>${c.protected}</b></span>`;
  reWrap.hidden=c.redirect===0;
}

hideRe.addEventListener("change",render);

f.addEventListener("submit",async e=>{
  e.preventDefault();
  data=null;results.innerHTML="";errorEl.hidden=true;reWrap.hidden=true;
  btn.disabled=true;btn.textContent="Scanning\\u2026";
  chips.innerHTML='<span class="muted">Scanning\\u2026 this can take a few seconds.</span>';
  try{
    const r=await fetch("/api/scan?url="+encodeURIComponent(urlEl.value));
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||"Request failed.");
    data=d;summarize();render();
  }catch(err){
    chips.innerHTML='<span class="muted">Error.</span>';
    errorEl.textContent=err.message;errorEl.hidden=false;
  }finally{
    btn.disabled=false;btn.textContent="Scan";
  }
});
</script>
</body>
</html>"""
