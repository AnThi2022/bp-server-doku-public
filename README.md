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

## Regeln für dieses Repo

- Nur Inhalte, die öffentlich sein dürfen: keine IP-Adressen, kein SSH-Port, keine Zugangsdaten, keine Sicherheitsbefunde zum laufenden System, keine Backups.
- Neue Inhalte zuerst im privaten Repo erfassen, dann bereinigt hierher übernehmen.
- Platzhalter statt Werte: `<DB_PASSWORT>`, `${SSH_PORT}`, `$SERVER`.
