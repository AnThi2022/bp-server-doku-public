#!/usr/bin/env python3
"""Exportiert ein Doku-Repo (Markdown + Mermaid) als PDF.

Voraussetzungen (alles temporär, ändert das System nicht):

    python3 -m venv /tmp/bp-pdf-venv
    /tmp/bp-pdf-venv/bin/pip install markdown weasyprint pillow
    curl -sL -o /tmp/bp-pdf-venv/mermaid.min.js \
        https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js

Außerdem wird `firefox` (headless) zum Rendern der Mermaid-Diagramme benötigt.

Aufruf:

    /tmp/bp-pdf-venv/bin/python scripts/export-pdf.py \
        --repo . --out ../pdf/bp-server-doku-public.pdf \
        --title "phpBB-Server – Dokumentation" --subtitle "Öffentliche Fassung"

Reihenfolge: README.md, docs/*.md, docs/adr/*.md, config|templates/README.md,
danach als Anhang alle Dateien aus config/ bzw. templates/.
Das PDF enthält Lesezeichen, Inhaltsverzeichnis mit Seitenzahlen und die Diagramme als Bilder.
"""
import argparse
import base64
import datetime
import html
import http.server
import io
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import markdown
from PIL import Image, ImageChops
from weasyprint import HTML

VENV = Path(os.environ.get("BP_PDF_VENV", "/tmp/bp-pdf-venv"))
MERMAID_JS = VENV / "mermaid.min.js"
HOLD_SECONDS = 3.0  # so lange hält der Testserver das Laden an, bis Mermaid fertig gerendert hat

CSS = """
@page { size: A4; margin: 20mm 17mm 20mm 17mm;
  @top-right { content: string(doctitle); font-size: 8pt; color: #777; }
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 8pt; color: #777; } }
@page :first { @top-right { content: none; } @bottom-center { content: none; } }
html { font-family: 'Liberation Sans', 'Noto Sans', sans-serif; font-size: 10pt; line-height: 1.45; color: #1b1b1b; }
h1 { font-size: 20pt; border-bottom: 2px solid #2b5797; padding-bottom: 4pt; margin-top: 0; string-set: doctitle content(); }
h2 { font-size: 14pt; margin-top: 18pt; color: #2b5797; break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 14pt; break-after: avoid; }
h4 { font-size: 10.5pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1a5fb4; text-decoration: none; }
code { font-family: 'DejaVu Sans Mono', 'Liberation Mono', monospace; font-size: 8.6pt; background: #f1f1f1; padding: 0 2pt; border-radius: 2pt; overflow-wrap: anywhere; }
pre { background: #f6f6f6; border: 1px solid #ddd; border-radius: 3pt; padding: 6pt 8pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid-page; }
pre code { background: none; padding: 0; font-size: 8pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 8.8pt; }
th, td { border: 1px solid #c9c9c9; padding: 3pt 5pt; vertical-align: top; text-align: left; overflow-wrap: break-word; }
th { background: #eaf0f8; }
tr { break-inside: avoid; }
blockquote { margin: 8pt 0; padding: 4pt 10pt; border-left: 3pt solid #c9a227; background: #fbf7e6; }
img.diagram { display: block; margin: 8pt auto; max-width: 100%; max-height: 215mm; break-inside: avoid; }
section.doc { break-before: page; }
.cover { text-align: center; padding-top: 70mm; }
.cover h1 { font-size: 28pt; border: none; string-set: none; }
.cover .sub { font-size: 14pt; color: #555; }
.cover .meta { margin-top: 30mm; color: #666; font-size: 10pt; }
.toc { break-before: page; }
.toc h1 { string-set: doctitle "Inhaltsverzeichnis"; }
.toc ol { list-style: none; padding: 0; }
.toc li { margin: 4pt 0; }
.toc a::after { content: leader('.') target-counter(attr(href), page); }
.appendix h3 { font-family: 'DejaVu Sans Mono', monospace; font-size: 9.5pt; }
"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Liefert Dateien aus dem Arbeitsordner; /hold.js verzögert das Laden künstlich."""

    def do_GET(self):
        if self.path.startswith("/hold.js"):
            time.sleep(HOLD_SECONDS)
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write(b"/* hold */")
            return
        super().do_GET()

    def log_message(self, *a):
        pass


class MermaidRenderer:
    def __init__(self, workdir: Path):
        self.work = workdir
        (self.work / "mermaid.min.js").write_bytes(MERMAID_JS.read_bytes())
        handler = lambda *a, **k: _Handler(*a, directory=str(self.work), **k)  # noqa: E731
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.profile = self.work / "ffprofile"
        self.profile.mkdir()
        (self.profile / "user.js").write_text(
            'user_pref("layout.css.devPixelsPerPx", "2.0");\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
        )

    def render(self, code: str, idx: int) -> bytes:
        page = self.work / f"d{idx}.html"
        page.write_text(
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            "body{margin:0;padding:12px;background:#fff;width:820px;font-family:'Liberation Sans',sans-serif}"
            "</style></head><body><pre class='mermaid'>" + html.escape(code) + "</pre>"
            "<script src='mermaid.min.js'></script>"
            "<script>mermaid.initialize({startOnLoad:false,theme:'default',securityLevel:'loose',"
            "flowchart:{htmlLabels:true,useMaxWidth:true},sequence:{useMaxWidth:true}});"
            "mermaid.run({querySelector:'.mermaid'});</script>"
            "<script src='/hold.js'></script></body></html>",
            encoding="utf-8",
        )
        shot = self.work / f"d{idx}.png"
        subprocess.run(
            ["firefox", "--headless", "--no-remote", "--profile", str(self.profile),
             "--screenshot", str(shot), "--window-size=860,2200",
             f"http://127.0.0.1:{self.port}/d{idx}.html"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True,
        )
        img = Image.open(shot).convert("RGB")
        bbox = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255))).getbbox()
        if not bbox or (bbox[2] - bbox[0]) < 60:
            raise RuntimeError(f"Diagramm {idx} wurde nicht gerendert (leeres Bild)")
        pad = 16
        box = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
               min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height))
        if bbox[3] >= img.height - 2:
            raise RuntimeError(f"Diagramm {idx} ist höher als das Renderfenster")
        out = io.BytesIO()
        img.crop(box).save(out, "PNG", optimize=True)
        return out.getvalue()

    def close(self):
        self.server.shutdown()


def collect_files(repo: Path):
    files = []
    if (repo / "README.md").exists():
        files.append("README.md")
    files += sorted(str(p.relative_to(repo)) for p in (repo / "docs").glob("*.md"))
    files += sorted(str(p.relative_to(repo)) for p in (repo / "docs").glob("adr/*.md"))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    files = collect_files(repo)
    ids = {f: doc_id(f) for f in files}

    with tempfile.TemporaryDirectory(prefix="bp-pdf-") as tmp:
        renderer = MermaidRenderer(Path(tmp))
        sections, toc = [], []
        n = 0
        try:
            for rel in files:
                text = (repo / rel).read_text(encoding="utf-8")
                md = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"])
                body = md.convert(text)

                def fit_scale(png_bytes):
                    # Faktor, mit dem das Bild in den Satzspiegel (176 x 215 mm bei 192 dpi) passt
                    w, h = Image.open(io.BytesIO(png_bytes)).size
                    return min(1330 / w, 1625 / h)

                def diagram(m):
                    nonlocal n
                    n += 1
                    code = html.unescape(m.group(1))
                    png = renderer.render(code, n)
                    # Breite "flowchart LR"-Diagramme zusätzlich hochkant rendern, größere Variante nehmen
                    if re.match(r"\s*flowchart LR", code):
                        alt = renderer.render(re.sub(r"flowchart LR", "flowchart TB", code, count=1), 1000 + n)
                        if fit_scale(alt) > fit_scale(png) * 1.15:
                            png = alt
                    b64 = base64.b64encode(png).decode()
                    return f'<img class="diagram" alt="Diagramm {n}" src="data:image/png;base64,{b64}">'

                body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>', diagram, body, flags=re.S)

                def link(m):
                    href, label = m.group(1), m.group(2)
                    if re.match(r"^(https?:|mailto:)", href):
                        return m.group(0)
                    target = os.path.normpath(os.path.join(os.path.dirname(rel), href.split("#")[0]))
                    if target in ids:
                        return f'<a href="#{ids[target]}">{label}</a>'
                    return label

                body = re.sub(r'<a href="([^"]*)">(.*?)</a>', link, body, flags=re.S)
                title_m = re.search(r"<h1>(.*?)</h1>", body, flags=re.S)
                title = re.sub(r"<[^>]+>", "", title_m.group(1)) if title_m else rel
                toc.append((ids[rel], title, rel))
                sections.append(f'<section class="doc" id="{ids[rel]}">{body}</section>')
        finally:
            renderer.close()

        appendix = ""
        for d in ("config", "templates"):
            base = repo / d
            if base.is_dir():
                items = []
                for p in sorted(base.rglob("*")):
                    if p.is_file() and p.name != "README.md":
                        items.append(f"<h3>{html.escape(str(p.relative_to(repo)))}</h3>"
                                     f"<pre><code>{html.escape(p.read_text(encoding='utf-8'))}</code></pre>")
                if items:
                    appendix = ('<section class="doc appendix" id="anhang"><h1>Anhang: Konfigurationsdateien</h1>'
                                + "".join(items) + "</section>")
                    toc.append(("anhang", "Anhang: Konfigurationsdateien", d + "/"))

        toc_html = ('<section class="toc"><h1>Inhaltsverzeichnis</h1><ol>'
                    + "".join(f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t, _ in toc)
                    + "</ol></section>")
        cover = (f'<section class="cover"><h1>{html.escape(args.title)}</h1>'
                 f'<div class="sub">{html.escape(args.subtitle)}</div>'
                 f'<div class="meta">Stand: {datetime.date.today():%d.%m.%Y}<br>{html.escape(git_info(repo))}</div></section>')
        doc = (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{html.escape(args.title)}</title>'
               f"<style>{CSS}</style></head><body>{cover}{toc_html}{''.join(sections)}{appendix}</body></html>")
        HTML(string=doc, base_url=str(repo)).write_pdf(str(out))
    print(f"PDF: {out} ({out.stat().st_size // 1024} KB), {len(files)} Dokumente, {n} Diagramme")


if __name__ == "__main__":
    main()
