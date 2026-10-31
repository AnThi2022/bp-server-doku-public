"""Windows-Variante des Doku-PDF-Exports (Gegenstück zu export-pdf.py).

Markdown -> HTML, Mermaid rendert im Browser, PDF über Chrome/Edge headless (DevTools-Protokoll).
Benötigt nur Python 3 und Google Chrome oder Microsoft Edge; kein WeasyPrint, kein Firefox.

Einrichtung (PowerShell, alles temporär unter %TEMP%):

    py -m venv "$env:TEMP\\bp-pdf-venv"
    & "$env:TEMP\\bp-pdf-venv\\Scripts\\python.exe" -m pip install markdown==3.9 websocket-client==1.8.0 pymupdf==1.28.2
    Invoke-WebRequest -UseBasicParsing -OutFile "$env:TEMP\\bp-pdf-venv\\mermaid.min.js" `
        -Uri https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js

Aufruf (im Repo-Ordner):

    & "$env:TEMP\\bp-pdf-venv\\Scripts\\python.exe" scripts\\export-pdf-windows.py --repo . `
        --out ..\\pdf\\<name>.pdf --title "..." --subtitle "..." `
        --mermaid "$env:TEMP\\bp-pdf-venv\\mermaid.min.js"

Reihenfolge und Anhang wie export-pdf.py. Das PDF enthält Lesezeichen, ein verlinktes
Inhaltsverzeichnis (ohne Seitenzahlen), Seitenzahlen im Fuß und die Diagramme als Vektorgrafik.
Optik: Doppelrahmen auf jeder Seite (nachträglich mit PyMuPDF gezeichnet; fehlt PyMuPDF, entsteht das PDF
ohne Rahmen), Cover mit Farbband, Tabellen mit Kopfzeile und Zebra-Zeilen, Code-Blöcke mit Akzentkante.
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
@page { size: A4; margin: 20mm 18mm 22mm 18mm; }
html { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1b1b1b; }

/* Der Seitenrahmen entsteht nach dem Druck (add_frame): Chrome beschneidet Inhalte ausserhalb des Seitenbereichs. */
h1 code { font-size: inherit; background: none; color: inherit; padding: 0; }

h1 { font-size: 20pt; color: #1f3f73; margin-top: 0; padding: 0 0 5pt 0;
     border-bottom: 1.5pt solid #2b5797; line-height: 1.2; }
/* Akzentbalken als Inline-Element: ein Rahmen (border-left) wuerde an Seitenumbruechen als Splitter auf der Vorseite landen */
h1::before { content: ""; display: inline-block; width: 5pt; height: 0.95em; margin-right: 9pt;
             background: #2b5797; vertical-align: -0.12em; }
.cover h1::before { display: none; }
h2 { font-size: 14pt; margin-top: 18pt; color: #2b5797; padding-bottom: 2pt; border-bottom: 0.6pt solid #c5d3ea; break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 14pt; color: #1f3f73; break-after: avoid; }
h4 { font-size: 10.5pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1a5fb4; text-decoration: none; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 8.6pt; background: #eef2f9; color: #1f3f73; padding: 0 2pt; border-radius: 2pt; overflow-wrap: anywhere; }
pre { background: #f5f7fb; border: 0.6pt solid #cfd9ea; border-left: 3.5pt solid #2b5797; border-radius: 3pt; padding: 6pt 9pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: none; color: #1b1b1b; padding: 0; font-size: 8pt; }
pre.mermaid { background: none; border: none; padding: 0; text-align: center; white-space: normal; }
pre.mermaid svg { max-width: 100%; max-height: 215mm; height: auto; }

table { border-collapse: separate; border-spacing: 0; width: 100%; margin: 9pt 0; font-size: 8.8pt;
        border: 0.8pt solid #9db4d8; border-radius: 4pt; }
th, td { padding: 3.5pt 6pt; vertical-align: top; text-align: left; overflow-wrap: break-word;
         border-right: 0.5pt solid #dbe4f3; border-bottom: 0.5pt solid #dbe4f3; }
th:last-child, td:last-child { border-right: none; }
tbody tr:last-child td { border-bottom: none; }
th { background: #2b5797; color: #fff; font-weight: 600; border-right-color: #4a76b8; border-bottom: none; }
th:first-child { border-top-left-radius: 3pt; }
th:last-child { border-top-right-radius: 3pt; }
tbody tr:nth-child(even) td { background: #f3f6fb; }
tbody tr:last-child td:first-child { border-bottom-left-radius: 3pt; }
tbody tr:last-child td:last-child { border-bottom-right-radius: 3pt; }
tr { break-inside: avoid; }

blockquote { margin: 8pt 0; padding: 5pt 10pt; border: 0.6pt solid #e4d28a; border-left: 4pt solid #c9a227; border-radius: 3pt; background: #fbf7e6; }
hr { border: none; border-top: 0.8pt solid #c5d3ea; margin: 12pt 0; }
section.doc { break-before: page; }

.cover { text-align: center; box-sizing: border-box; height: 250mm; padding-top: 38mm; overflow: hidden; break-after: page; }
.cover .band { height: 7mm; margin: 0 -9mm; background: linear-gradient(90deg, #1f3f73, #2b5797 60%, #6f9ad6); }
.cover .band.bottom { margin-top: 24mm; }
.cover h1 { font-size: 30pt; margin: 22mm 0 4mm; padding: 0; border: none; color: #1f3f73; }
.cover .sub { font-size: 14pt; color: #555; }
.cover .rule { width: 40mm; height: 0; margin: 10mm auto 0; border-top: 2pt solid #c9a227; }
.cover .meta { display: inline-block; margin-top: 26mm; padding: 6pt 22pt; color: #444; font-size: 10pt;
               border: 0.8pt solid #9db4d8; border-radius: 4pt; background: #f5f7fb; line-height: 1.7; }

.toc { break-before: page; }
.toc ol { list-style: none; padding: 0; counter-reset: t; }
.toc li { counter-increment: t; margin: 5pt 0; padding: 5pt 10pt; font-size: 11pt; border: 0.6pt solid #cfd9ea;
          border-left: 3.5pt solid #2b5797; border-radius: 3pt; background: #f9fbfe; break-inside: avoid; }
.toc li::before { content: counter(t) "."; display: inline-block; width: 18pt; color: #2b5797; font-weight: 600; }
.toc .file { color: #888; font-size: 8.5pt; margin-left: 6pt; }
.appendix h3 { font-family: Consolas, monospace; font-size: 9.5pt; }
"""

FOOTER = ('<div style="font-size:8px;color:#1f3f73;width:100%;padding:0 18mm;display:flex;justify-content:space-between;">'
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
    cover = (f'<section class="cover"><div class="band"></div><h1>{html.escape(title)}</h1>'
             f'<div class="sub">{html.escape(subtitle)}</div><div class="rule"></div>'
             f'<div class="meta">Stand: {datetime.date.today():%d.%m.%Y}<br>{html.escape(git_info(repo))}</div>'
             f'<div class="band bottom"></div></section>')
    script = ("<script src='" + mermaid_js + "'></script><script>"
              "mermaid.initialize({startOnLoad:false,theme:'default',securityLevel:'strict',"
              "flowchart:{htmlLabels:true,useMaxWidth:true},sequence:{useMaxWidth:true}});"
              "function fit(pre){const s=pre.querySelector('svg');const vb=s.viewBox.baseVal;"
              "const w=vb&&vb.width?vb.width:s.getBBox().width, h=vb&&vb.height?vb.height:s.getBBox().height;"
              "return Math.min(1, 650/w, 812/h);}"
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


def add_frame(pdf: Path) -> bool:
    """Zeichnet auf jede Seite einen Doppelrahmen (aussen kraeftig, innen fein).

    Geschieht nach dem Druck mit PyMuPDF, weil Chrome Inhalte in den Seitenraendern nicht ausgibt.
    Fehlt PyMuPDF, bleibt das PDF ohne Rahmen (sonst unveraendert).
    """
    try:
        import pymupdf
    except ImportError:
        print("Hinweis: pymupdf fehlt, PDF entsteht ohne Seitenrahmen (pip install pymupdf)")
        return False
    doc = pymupdf.open(str(pdf))
    for page in doc:
        r = page.rect
        outer = pymupdf.Rect(r.x0 + 30, r.y0 + 30, r.x1 - 30, r.y1 - 38)
        inner = pymupdf.Rect(outer.x0 + 4, outer.y0 + 4, outer.x1 - 4, outer.y1 - 4)
        page.draw_rect(outer, color=(0.122, 0.247, 0.451), width=1.4, radius=0.012)
        page.draw_rect(inner, color=(0.616, 0.706, 0.847), width=0.4, radius=0.01)
    tmp = pdf.with_suffix(".tmp.pdf")
    doc.save(str(tmp), garbage=3, deflate=True)
    doc.close()
    tmp.replace(pdf)
    return True


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
    add_frame(out)
    print(f"PDF: {out} ({out.stat().st_size // 1024} KB), {nfiles} Dokumente, {rendered} Diagramme")


if __name__ == "__main__":
    main()
