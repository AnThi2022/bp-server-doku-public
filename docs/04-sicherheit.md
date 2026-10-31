# 04 – Sicherheitskonzept (allgemein)

## Grundsätze

| Bereich | Maßnahme |
|---|---|
| SSH | eigener Port, nur Public-Key, kein Passwort-Login, kein Root-Login mit Passwort |
| Firewall | `ufw`: eingehend alles gesperrt außer SSH, 80, 443; ausgehend frei |
| Datenbank | nur auf `127.0.0.1`, kein Remote-Zugriff |
| TLS | Let's Encrypt, automatische Erneuerung, HTTP → HTTPS-Redirect |
| Updates | `unattended-upgrades` für Sicherheitsupdates |
| Apache | `TraceEnable Off`; Versionsangaben reduzieren (`ServerTokens Prod`, `ServerSignature Off`) |
| phpBB | `config.php` mit Mode 640, Installationsverzeichnis nach dem Setup entfernen, keine Test- oder Debug-Dateien (z. B. `phpinfo.php`) im Web-Root |
| Backup | nächtliches Gesamt-Backup des Servers durch den Hosting-Anbieter |
| Mail | externer Mailanbieter per SMTP, kein lokaler MTA |

## Geheimnisse

**Nie in ein Repository:**

- Datenbank-Passwort (liegt in phpBB `config.php`)
- private SSH-Schlüssel und TLS-Schlüssel
- Datenbank-Dumps und Backups
- SMTP-Zugangsdaten

Ablage im Passwortmanager. In Dokumenten stehen nur Platzhalter wie `<DB_PASSWORT>`.

Vor jedem Commit:

```bash
git diff --cached | grep -inE 'passw|secret|token|BEGIN .*PRIVATE'
```

Skripte dürfen keine Passwörter auf der Kommandozeile tragen (sichtbar in `ps` und Shell-History). Stattdessen `~/.my.cnf` mit Mode 600 oder `unix_socket` als root verwenden.

## Prüfliste für den Web-Root

```bash
find /var/www/forum -maxdepth 3 -type f \( -name '*.sql*' -o -name '*.tar*' -o -name '*.zip' -o -name '*.bak' -o -name 'phpinfo.php' \)
```

Funde außerhalb des Web-Roots ablegen und von außen per `curl -I` prüfen, dass sie nicht mehr erreichbar sind.
