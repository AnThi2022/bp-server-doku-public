#!/usr/bin/env bash
# Erfasst den Ist-Zustand des Servers bp rein lesend (keine Aenderungen, keine Geheimnisse).
# Aufruf: BP_HOST=<server> BP_PORT=<port> ./scripts/collect-state.sh > state.txt
set -euo pipefail

HOST="${BP_HOST:?BP_HOST setzen (Servername)}"
PORT="${BP_PORT:?BP_PORT setzen (SSH-Port)}"

ssh -p "$PORT" -o BatchMode=yes -o ConnectTimeout=15 "root@$HOST" 'bash -s' <<'REMOTE'
section() { printf '\n=== %s\n' "$1"; }

section "Datum / Host"
date -u +%FT%TZ; hostname; hostname -f

section "OS / Kernel / Ressourcen"
. /etc/os-release; echo "$PRETTY_NAME"; uname -r; nproc; free -h | sed -n 2p
df -h / | tail -1

section "Netzwerk"
ip -br a

section "Firewall"
ufw status

section "SSH (effektiv)"
sshd -T | grep -Ei '^(port|permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication)'

section "Dienste"
systemctl is-active apache2 mariadb cron ssh ufw
systemctl --failed --no-legend

section "Ports"
ss -tlnp | awk 'NR>1 {split($6,a,"\""); print $4, a[2]}' | sort -u

section "Versionen"
apache2 -v | head -1; php -v | head -1; mariadb --version
grep -h "PHPBB_VERSION" /var/www/forum/includes/constants.php || true

section "Apache vhosts"
apache2ctl -S 2>&1 | sed -n 1,6p

section "Zertifikate"
certbot certificates 2>&1 | grep -E 'Certificate Name|Domains|Expiry'

section "Timer / Cron"
systemctl list-timers --no-legend | awk '{print $(NF-1), $NF}'
ls /etc/cron.d

section "Reboot noetig?"
[ -f /var/run/reboot-required ] && echo "ja" || echo "nein"
REMOTE
