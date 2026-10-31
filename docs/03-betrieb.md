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

Backups liegen **nicht** auf dem Server selbst, sondern auf einem separaten Volume oder extern. Das Backup-Konzept (Rhythmus, Aufbewahrung, Restore-Test) wird im privaten Betriebs-Repo geführt.

Manuelles Backup (Zugangsdaten **nicht** auf der Kommandozeile angeben, sondern über `~/.my.cnf` mit Mode 600 oder `unix_socket` als root):

```bash
# Datenbank, konsistent
mariadb-dump --single-transaction --routines bluemchen | gzip > /pfad/bluemchen_$(date +%Y%m%d).sql.gz

# Dateien
rsync -a /var/www/forum/ /pfad/forum/
```

Restore: siehe Schritt 9 in [02-bereitstellung.md](02-bereitstellung.md).

## Abnahme nach Reboot oder Neuaufbau

```bash
hostname; hostname -f                      # bp / www.bluemchenpfluecker.de
systemctl --failed                         # leer
systemctl is-active apache2 mariadb cron   # active
ss -tlnp | grep -E ":(${SSH_PORT}|80|443|3306)"   # 3306 nur auf 127.0.0.1
ufw status                                 # aktiv, 3 Regeln
curl -sI https://www.bluemchenpfluecker.de/ | head -1      # 200
curl -sI http://www.bluemchenpfluecker.de/  | head -1      # 301
curl -sI https://bluemchenpfluecker.com/    | head -3      # 301 → .de
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
