# templates/

Konfigurationsvorlagen für den Server. Zielpfade:

| Datei | Pfad auf dem Server |
|---|---|
| `apache/forum.conf` | `/etc/apache2/sites-available/forum.conf` |
| `apache/forum-le-ssl.conf` | `/etc/apache2/sites-available/forum-le-ssl.conf` |
| `ssh/99-hardening.conf` | `/etc/ssh/sshd_config.d/99-hardening.conf` |
| `cloud-init/99-bluemchen-hostname.cfg` | `/etc/cloud/cloud.cfg.d/99-bluemchen-hostname.cfg` |
| `cron.d/forum-compress` | `/etc/cron.d/forum-compress` |

Domains in den Vorlagen sind die öffentlichen Domains des Forums. Nicht enthalten: phpBB `config.php`, TLS-Schlüssel, Zugangsdaten.
