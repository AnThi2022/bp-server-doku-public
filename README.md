# bp-server-doku-public

Öffentliche, bereinigte Dokumentation eines **phpBB-Forums auf einem Debian-Server** (Apache, PHP, MariaDB, Let's Encrypt). Sie zeigt Architektur, Aufbau und Betrieb als Muster.

Echte Betriebsdaten (IP-Adressen, SSH-Port, Befunde, Änderungsprotokoll, Backup-Konzept) stehen im privaten Schwester-Repo `bp-server-doku`.

| Dokument | Zweck |
|---|---|
| [docs/01-architektur.md](docs/01-architektur.md) | Architekturskizzen (Mermaid) |
| [docs/02-bereitstellung.md](docs/02-bereitstellung.md) | Runbook: Server aufbauen |
| [docs/03-betrieb.md](docs/03-betrieb.md) | Betrieb: Updates, Zertifikate, Cron, Abnahme |
| [docs/04-sicherheit.md](docs/04-sicherheit.md) | Allgemeines Sicherheitskonzept |
| [templates/](templates/) | Konfigurationsvorlagen |
| [scripts/](scripts/) | Hilfsskript (lesend) |

## Stack

Debian 13 · Apache 2.4 (prefork + mod_php) · PHP 8.4 · MariaDB 11.8 · phpBB 3.3.x · certbot · ufw

## PDF-Export

PDFs mit Inhaltsverzeichnis, Lesezeichen und gerenderten Diagrammen entstehen mit `scripts/export-pdf.py`. Sie landen im Ordner `../pdf/` (außerhalb der Repos, nicht versioniert).

```bash
python3 -m venv /tmp/bp-pdf-venv
/tmp/bp-pdf-venv/bin/pip install markdown weasyprint pillow
curl -sL -o /tmp/bp-pdf-venv/mermaid.min.js https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js
/tmp/bp-pdf-venv/bin/python scripts/export-pdf.py --repo . --out ../pdf/bp-server-doku-public.pdf \
  --title "phpBB-Server – Dokumentation" --subtitle "Öffentliche Fassung"
```

Benötigt wird außerdem `firefox` (headless, rendert die Mermaid-Diagramme). 

## Regeln für dieses Repo

- Nur Inhalte, die öffentlich sein dürfen: keine IP-Adressen, kein SSH-Port, keine Zugangsdaten, keine Sicherheitsbefunde zum laufenden System, keine Backups.
- Neue Inhalte zuerst im privaten Repo erfassen, dann bereinigt hierher übernehmen.
- Platzhalter statt Werte: `<DB_PASSWORT>`, `${SSH_PORT}`, `$SERVER`.
