⚔️ DirBuster PY

A simple **DirBuster-like** tool made for **Windows**, written in **Python**.  
Inspired by the [DirBuster](https://www.kali.org/tools/dirbuster/) tool from Kali Linux.

🔍 What it does
> DirBuster is a multi-threaded Java application designed to brute force directories and filenames on web/application servers.  
> Often, a web server that looks like a default installation might actually have hidden pages and applications.  
> DirBuster attempts to discover those.

This Python version brings that same functionality in a lightweight script, easy to run on any Windows system — no Kali needed.

🚀 How to Use

1. Type the URL of the target website (with or without `https://`, both work fine).
2. Optionally, include a trailing `/` at the end — but it’s handled automatically.
3. Run the script and let it scan using the built-in wordlist.

✅ Example

```bash
Type your URL -> google.com
```

If any valid path is found, it’ll display the status code (e.g., `200 OK`).

---

💡 Notes

- Be patient — large wordlists can take time.
- You can replace the `Subdomain.txt` file with your own list of paths or directories.
- This is a **single-threaded** tool (for now), no parallel requests yet.
- Works smoothly on Windows and doesn't require Linux-specific tools.
