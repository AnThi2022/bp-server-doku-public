# 03 – Betrieb

## Zugang

```bash
ssh -p "$SSH_PORT" root@"$SERVER"
```

Nur Public-Key-Login. Nach einer Hostname-Änderung zeigt eine bereits offene Sitzung den alten Prompt, erst ein neuer Login zeigt `bp`.

## Updates

- Sicherheitsupdates: automatisch über `unattended-upgrades`.
- Manuell:

```bash
apt update && apt list --upgradable
apt full-upgrade
needrestart -r l 2>/dev/null || true   # falls installiert
systemctl reboot                        # nur bei Kernel-Update oder auf Wunsch
```

- phpBB-Updates (3.3.x) nach der offiziellen Anleitung, **immer erst Backup** (Dateien + Datenbank).

## Zertifikate

```bash
certbot certificates
systemctl list-timers certbot.timer
certbot renew --dry-run
```

Erneuerung läuft über `certbot.timer`. Die Erneuerung benötigt Port 80 und den Pfad `/.well-known/acme-challenge/` (von der `.com`-Weiterleitung ausgenommen).

## Cron-Jobs

| Zeit | Job | Zweck |
|---|---|---|
| täglich 04:00 | `/usr/local/bin/forum_compress_daily.sh` | neue Forum-Uploads (Bilder) komprimieren |

## Backup und Restore

Das Backup-Konzept ist die **nächtliche Sicherung des gesamten Servers durch Hetzner** (Hetzner Cloud Backups). Sie umfasst die komplette Platte: System, Konfiguration, phpBB-Dateien und Datenbank. Es gibt keine eigenen Backup-Jobs auf dem Server.

Wiederherstellung über die Hetzner Cloud Console: Server → Backups → Backup wiederherstellen (überschreibt den Server) oder aus dem Backup einen neuen Server erstellen. Die Console-Schritte sind nicht durch einen Test belegt.

Zu beachten:

- Die Sicherung ist ein Abbild der laufenden Platte. Die Datenbank (InnoDB) ist darin „crash-konsistent“ und wird beim Start per Recovery wieder konsistent, ist aber kein logischer Dump.
- Hetzner hält nur eine begrenzte Zahl Sicherungen vor (Standard: 7, tägliches Zeitfenster). Eigene Einstellung in der Console prüfen.
- Angehängte Hetzner-Volumes sind in Server-Backups nicht enthalten. Aktuell sind keine eingehängt.
- Vor riskanten Änderungen (phpBB-Update, Paket-Upgrade) zusätzlich einen manuellen Snapshot in der Console anlegen.
- Optionaler Zusatz-Dump der Datenbank (ohne Passwort, als root über den Socket):

```bash
mariadb-dump --single-transaction --routines bluemchen | gzip > /pfad/bluemchen_$(date +%Y%m%d).sql.gz
```

Für einen Neuaufbau aus Dateien und Dump (statt Komplett-Restore): siehe Schritt 9 in [02-bereitstellung.md](02-bereitstellung.md).

## Abnahme nach Reboot oder Neuaufbau

```bash
hostname; hostname -f                      # bp / www.example.org
systemctl --failed                         # leer
systemctl is-active apache2 mariadb cron   # active
ss -tlnp | grep -E ":(${SSH_PORT}|80|443|3306)"   # 3306 nur auf 127.0.0.1
ufw status                                 # aktiv, 3 Regeln
curl -sI https://www.example.org/ | head -1      # 200
curl -sI http://www.example.org/  | head -1      # 301
curl -sI https://example.com/    | head -3      # 301 → www.example.org
journalctl -b -p err --no-pager            # nur bekannte Meldungen
df -h /                                    # Platz beobachten
```

Bekannte, harmlose Meldung nach dem Boot: `systemd-ssh-generator: Failed to query local AF_VSOCK CID` (KVM-VM ohne vsock, betrifft sshd nicht).

## Logs

| Zweck | Ort |
|---|---|
| Apache Zugriff / Fehler | `/var/log/apache2/forum_access.log`, `forum_error.log` |
| Systemjournal | `journalctl -u apache2`, `-u mariadb`, `-u ssh` |
| unattended-upgrades | `/var/log/unattended-upgrades/` |
| Zertifikate | `/var/log/letsencrypt/` |

## Zustandserfassung

`scripts/collect-state.sh` liest den Serverzustand ohne Änderungen aus (Host und Port über `BP_HOST` und `BP_PORT`):

```bash
BP_HOST="$SERVER" BP_PORT="$SSH_PORT" ./scripts/collect-state.sh > /tmp/state.txt
```
