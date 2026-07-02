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
| `--no-follow` | Don't follow root redirects (scan the exact host) | off |

By default the scanner follows redirects on the root first, so pointing it at an
apex that `301`s to `www` (e.g. `example.com` -> `www.example.com`) scans `www`
instead of returning a wall of redirects. Pass `--no-follow` to scan the exact
host you typed.

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

## ☁️ Deploy to Vercel

The repo ships a serverless entry point (`api/index.py` + `vercel.json`) for public
hosting. There's no live streaming on serverless, so each scan probes a capped slice
of the (frequency-ordered) wordlist to stay inside the function timeout.

1. Import the repo on [Vercel](https://vercel.com/new).
2. Deploy. In **Settings → Domains**, add `dirbuster.fassi.dev` and create the
   `CNAME dirbuster → cname.vercel-dns.com` record at your DNS provider for
   `fassi.dev` (Vercel shows the exact value to use).
3. *(Optional)* Tune the scan under **Settings → Environment Variables** — see
   `.env.example`:

   | Name | Default | Description |
   | --- | --- | --- |
   | `MAX_WORDS` | `12000` | How many paths to probe per scan |
   | `MAX_THREADS` | `100` | Max concurrent requests |

> ⚠️ **This deployment scans any domain.** Anyone who can reach it can use your
> Vercel IPs to probe third-party sites. Keep it private, put it behind auth, or
> re-introduce a domain allow-list if that's a concern.

## 💡 Notes

- The scheme is optional — `example.com` and `https://example.com/` both work.
- Replace `wordlist.txt` with your own list of paths (one per line; `#` lines are ignored).
- Press `Ctrl+C` at any time to stop and see the paths found so far.
