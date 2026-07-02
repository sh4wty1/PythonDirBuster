# ⚔️ PythonDirBuster

A small, **multi-threaded** web directory/file brute-forcer written in **Python**.
Inspired by [DirBuster](https://www.kali.org/tools/dirbuster/) from Kali Linux — but
cross-platform (Linux, macOS, Windows) and dependency-light.

> ⚠️ **Use responsibly.** Only scan systems you own or are explicitly authorized to test.

## 🔍 What it does

Given a target URL and a wordlist, it requests every `TARGET/word` path concurrently
and reports the ones that look interesting:

- `2xx` — **found** (green)
- `3xx` — **redirect** (yellow)
- `401` / `403` — **exists but protected** (red)

Everything else (404s, connection errors) is hidden so the output stays readable.

## 📦 Install

```bash
pip install -r requirements.txt
```

## 🚀 Usage

Interactive (prompts for the URL):

```bash
python pythondirbuster.py
```

With arguments:

```bash
python pythondirbuster.py https://example.com
python pythondirbuster.py example.com -w wordlist.txt -t 40 --timeout 3
```

| Option | Description | Default |
| --- | --- | --- |
| `url` | Target URL (scheme optional, prompted if omitted) | — |
| `-w`, `--wordlist` | Path to the wordlist | `wordlist.txt` |
| `-t`, `--threads` | Number of concurrent requests | `20` |
| `--timeout` | Request timeout in seconds | `5` |
| `--no-color` | Disable colored output | off |

On Windows you can also just double-click **`Run.bat`**.

## 🌐 Web UI

There's also a browser front-end (Flask) that streams results live via
Server-Sent Events, reusing the same scan engine as the CLI:

```bash
pip install -r requirements.txt
python webapp.py            # -> http://127.0.0.1:5000
python webapp.py --port 8080 --host 0.0.0.0
```

> ⚠️ **Do not expose this publicly.** A hosted brute-forcer lets anyone use your
> server/IP to hammer arbitrary sites (SSRF/abuse) and won't work well on
> serverless streaming limits (e.g. Vercel). Keep it bound to `127.0.0.1`, or if
> you must host it, put it behind auth + a domain allow-list. See `webapp.py`.

## ☁️ Deploy to Vercel (safe demo mode)

The repo ships a serverless entry point (`api/index.py` + `vercel.json`) built for
public hosting. It is deliberately locked down: no long-running streaming, a capped
wordlist, and — most importantly — it **only scans domains you explicitly allow**.

1. Import the repo on [Vercel](https://vercel.com/new).
2. In **Settings → Environment Variables**, add:

   | Name | Value |
   | --- | --- |
   | `ALLOWED_DOMAINS` | `yourdomain.com,staging.yourdomain.com` |

   Without this variable, scanning stays **disabled** — the safe default.
3. Deploy. Attach your custom domain in **Settings → Domains**.

Only domains in `ALLOWED_DOMAINS` (and their subdomains) can be scanned, so nobody
can point your deployment at third-party sites. For unrestricted local scanning,
use `webapp.py` or the CLI instead.

## 💡 Notes

- The scheme is optional — `example.com` and `https://example.com/` both work.
- Replace `wordlist.txt` with your own list of paths (one per line; `#` lines are ignored).
- Press `Ctrl+C` at any time to stop and see the paths found so far.
