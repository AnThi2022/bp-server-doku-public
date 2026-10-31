"""Windows-Variante des Doku-PDF-Exports (Gegenstück zu export-pdf.py).

Markdown -> HTML, Mermaid rendert im Browser, PDF über Chrome/Edge headless (DevTools-Protokoll).
Benötigt nur Python 3 und Google Chrome oder Microsoft Edge; kein WeasyPrint, kein Firefox.

Einrichtung (PowerShell, alles temporär unter %TEMP%):

    py -m venv "$env:TEMP\\bp-pdf-venv"
    & "$env:TEMP\\bp-pdf-venv\\Scripts\\python.exe" -m pip install markdown==3.9 websocket-client==1.8.0
    Invoke-WebRequest -UseBasicParsing -OutFile "$env:TEMP\\bp-pdf-venv\\mermaid.min.js" `
        -Uri https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js

Aufruf (im Repo-Ordner):

    & "$env:TEMP\\bp-pdf-venv\\Scripts\\python.exe" scripts\\export-pdf-windows.py --repo . `
        --out ..\\pdf\\<name>.pdf --title "..." --subtitle "..." `
        --mermaid "$env:TEMP\\bp-pdf-venv\\mermaid.min.js"

Reihenfolge und Anhang wie export-pdf.py. Das PDF enthält Lesezeichen, ein verlinktes
Inhaltsverzeichnis (ohne Seitenzahlen), Seitenzahlen im Fuß und die Diagramme als Vektorgrafik.
Breite `flowchart LR`-Diagramme werden zusätzlich hochkant gerendert; die größere Variante bleibt.
"""
import argparse
import base64
import datetime
import html
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import markdown
import websocket  # websocket-client

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 18mm 17mm 18mm 17mm; }
html { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1b1b1b; }
h1 { font-size: 20pt; border-bottom: 2px solid #2b5797; padding-bottom: 4pt; margin-top: 0; }
h2 { font-size: 14pt; margin-top: 18pt; color: #2b5797; break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 14pt; break-after: avoid; }
h4 { font-size: 10.5pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1a5fb4; text-decoration: none; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 8.6pt; background: #f1f1f1; padding: 0 2pt; border-radius: 2pt; overflow-wrap: anywhere; }
pre { background: #f6f6f6; border: 1px solid #ddd; border-radius: 3pt; padding: 6pt 8pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8pt; }
pre.mermaid { background: none; border: none; padding: 0; text-align: center; white-space: normal; }
pre.mermaid svg { max-width: 100%; max-height: 215mm; height: auto; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 8.8pt; }
th, td { border: 1px solid #c9c9c9; padding: 3pt 5pt; vertical-align: top; text-align: left; overflow-wrap: anywhere; }
th { background: #eaf0f8; }
tr { break-inside: avoid; }
blockquote { margin: 8pt 0; padding: 4pt 10pt; border-left: 3pt solid #c9a227; background: #fbf7e6; }
section.doc { break-before: page; }
.cover { text-align: center; padding-top: 70mm; }
.cover h1 { font-size: 28pt; border: none; }
.cover .sub { font-size: 14pt; color: #555; }
.cover .meta { margin-top: 30mm; color: #666; font-size: 10pt; }
.toc { break-before: page; }
.toc ol { list-style: none; padding: 0; }
.toc li { margin: 5pt 0; font-size: 11pt; }
.toc .file { color: #888; font-size: 8.5pt; margin-left: 6pt; }
.appendix h3 { font-family: Consolas, monospace; font-size: 9.5pt; }
"""

FOOTER = ('<div style="font-size:8px;color:#777;width:100%;padding:0 17mm;display:flex;justify-content:space-between;">'
          '<span>{title}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')


def collect_files(repo: Path):
    files = []
    if (repo / "README.md").exists():
        files.append("README.md")
    files += sorted(p.relative_to(repo).as_posix() for p in (repo / "docs").glob("*.md"))
    files += sorted(p.relative_to(repo).as_posix() for p in (repo / "docs").glob("adr/*.md"))
    for d in ("config", "templates"):
        if (repo / d / "README.md").exists():
            files.append(f"{d}/README.md")
    return files


def doc_id(rel: str) -> str:
    return "doc-" + re.sub(r"[^a-z0-9]+", "-", rel.lower()).strip("-")


def git_info(repo: Path) -> str:
    try:
        h = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        return f"Commit {h}" + (" (mit uncommitteten Änderungen)" if dirty else "")
    except Exception:
        return "ohne Git-Stand"


def build_html(repo: Path, title: str, subtitle: str, mermaid_js: str):
    files = collect_files(repo)
    ids = {f: doc_id(f) for f in files}
    sections, toc, n = [], [], 0
    for rel in files:
        text = (repo / rel).read_text(encoding="utf-8")
        body = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"]).convert(text)

        def diagram(m):
            nonlocal n
            n += 1
            code = m.group(1)
            # Breite LR-Flowcharts zusätzlich hochkant rendern; im Browser bleibt die größere Variante
            if re.match(r"\s*flowchart LR", code):
                tb = re.sub(r"flowchart LR", "flowchart TB", code, count=1)
                return (f'<div class="mpair"><pre class="mermaid">{code}</pre>'
                        f'<pre class="mermaid">{tb}</pre></div>')
            return f'<pre class="mermaid">{code}</pre>'

        body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>', diagram, body, flags=re.S)

        def link(m):
            href, label = m.group(1), m.group(2)
            if re.match(r"^(https?:|mailto:)", href):
                return m.group(0)
            target = os.path.normpath(os.path.join(os.path.dirname(rel), href.split("#")[0])).replace("\\", "/")
            if target in ids:
                return f'<a href="#{ids[target]}">{label}</a>'
            return label

        body = re.sub(r'<a href="([^"]*)">(.*?)</a>', link, body, flags=re.S)
        tm = re.search(r"<h1>(.*?)</h1>", body, flags=re.S)
        t = re.sub(r"<[^>]+>", "", tm.group(1)) if tm else rel
        toc.append((ids[rel], html.unescape(t), rel))
        sections.append(f'<section class="doc" id="{ids[rel]}">{body}</section>')

    appendix = ""
    for d in ("config", "templates"):
        base = repo / d
        if base.is_dir():
            items = []
            for p in sorted(base.rglob("*")):
                if p.is_file() and p.name != "README.md":
                    items.append(f"<h3>{html.escape(p.relative_to(repo).as_posix())}</h3>"
                                 f"<pre><code>{html.escape(p.read_text(encoding='utf-8'))}</code></pre>")
            if items:
                appendix = ('<section class="doc appendix" id="anhang"><h1>Anhang: Konfigurationsdateien</h1>'
                            + "".join(items) + "</section>")
                toc.append(("anhang", "Anhang: Konfigurationsdateien", d + "/"))

    toc_html = ('<section class="toc"><h1>Inhaltsverzeichnis</h1><ol>'
                + "".join(f'<li><a href="#{i}">{html.escape(t)}</a><span class="file">{html.escape(f)}</span></li>'
                          for i, t, f in toc)
                + "</ol></section>")
    cover = (f'<section class="cover"><h1>{html.escape(title)}</h1><div class="sub">{html.escape(subtitle)}</div>'
             f'<div class="meta">Stand: {datetime.date.today():%d.%m.%Y}<br>{html.escape(git_info(repo))}</div></section>')
    script = ("<script src='" + mermaid_js + "'></script><script>"
              "mermaid.initialize({startOnLoad:false,theme:'default',securityLevel:'strict',"
              "flowchart:{htmlLabels:true,useMaxWidth:true},sequence:{useMaxWidth:true}});"
              "function fit(pre){const s=pre.querySelector('svg');const vb=s.viewBox.baseVal;"
              "const w=vb&&vb.width?vb.width:s.getBBox().width, h=vb&&vb.height?vb.height:s.getBBox().height;"
              "return Math.min(1, 665/w, 812/h);}"
              "mermaid.run({querySelector:'pre.mermaid'}).then(()=>{"
              "document.querySelectorAll('div.mpair').forEach(d=>{const [a,b]=d.querySelectorAll('pre.mermaid');"
              "(fit(b)>fit(a)*1.15?a:b).remove();});"
              "window.__done=true}).catch(e=>{window.__err=String(e);window.__done=true});"
              "</script>")
    doc = (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
           f"<style>{CSS}</style></head><body>{cover}{toc_html}{''.join(sections)}{appendix}{script}</body></html>")
    return doc, len(files), n


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=120)
        self.i = 0

    def call(self, method, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


def print_pdf(html_file: Path, out: Path, title: str, expected_diagrams: int):
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)
    if not chrome:
        raise SystemExit("Chrome/Edge nicht gefunden")
    port = free_port()
    profile = Path(tempfile.mkdtemp(prefix="bp-pdf-profile-"))
    proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port}",
                             "--remote-allow-origins=*", f"--user-data-dir={profile}",
                             "--no-first-run", "--no-default-browser-check", "--allow-file-access-from-files",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    pages = [t for t in json.load(r) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not ws_url:
            raise RuntimeError("Chrome-DevTools nicht erreichbar")
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Emulation.setEmulatedMedia", media="print")
        cdp.call("Page.navigate", url=html_file.as_uri())
        state = {}
        for _ in range(300):
            r = cdp.call("Runtime.evaluate", returnByValue=True, expression=(
                "JSON.stringify({done: window.__done===true, err: window.__err||null,"
                " svgs: document.querySelectorAll('pre.mermaid svg').length})"))
            state = json.loads(r["result"]["value"])
            if state["done"]:
                break
            time.sleep(0.2)
        if not state.get("done"):
            raise RuntimeError("Mermaid wurde nicht fertig")
        if state.get("err"):
            raise RuntimeError(f"Mermaid-Fehler: {state['err']}")
        if state["svgs"] != expected_diagrams:
            raise RuntimeError(f"Nur {state['svgs']} von {expected_diagrams} Diagrammen gerendert")
        res = cdp.call("Page.printToPDF", printBackground=True, preferCSSPageSize=True,
                       displayHeaderFooter=True, headerTemplate="<span></span>",
                       footerTemplate=FOOTER.format(title=html.escape(title)),
                       generateDocumentOutline=True, generateTaggedPDF=True)
        out.write_bytes(base64.b64decode(res["data"]))
        return state["svgs"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--mermaid", required=True)
    a = ap.parse_args()
    repo, out = Path(a.repo).resolve(), Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    mermaid_uri = Path(a.mermaid).resolve().as_uri()
    doc, nfiles, ndiag = build_html(repo, a.title, a.subtitle, mermaid_uri)
    html_file = Path(tempfile.gettempdir()) / "bp-pdf" / (out.stem + ".html")
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(doc, encoding="utf-8")
    try:
        rendered = print_pdf(html_file, out, a.title, ndiag)
    finally:
        html_file.unlink(missing_ok=True)
    print(f"PDF: {out} ({out.stat().st_size // 1024} KB), {nfiles} Dokumente, {rendered} Diagramme")


if __name__ == "__main__":
    main()
