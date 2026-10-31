# 01 – Architektur

Alle Diagramme sind Mermaid. Sie beschreiben die Architektur eines phpBB-Forums auf einem einzelnen Debian-Server. Konkrete Adressen und der SSH-Port sind bewusst weggelassen.

## 1. Systemkontext

```mermaid
flowchart LR
    U["Besucher / Browser"]
    A["Admin<br/>(SSH-Key)"]
    LE["Let's Encrypt<br/>(ACME)"]
    DNS["DNS<br/>Haupt- und Weiterleitungsdomain"]
    MAIL["Externer<br/>Mailserver (SMTP)"]

    subgraph HZ["Hetzner Cloud (fsn1)"]
        S["Server bp<br/>Debian 13"]
    end

    U -- "HTTPS 443 / HTTP 80" --> S
    A -- "SSH SSH-PORT" --> S
    S -- "Zertifikat erneuern" --> LE
    S -- "Forum-Mails (SMTP, ausgehend)" --> MAIL
    LE -. "HTTP-01 Challenge (80)" .-> S
    U -. "Namensauflösung" .-> DNS
    DNS -. "A / AAAA" .-> S
```

## 2. Komponenten auf dem Server

```mermaid
flowchart TB
    subgraph NET["Netzwerk eth0"]
        FW["ufw / nftables<br/>erlaubt: SSH-PORT, 80, 443"]
    end

    subgraph SRV["Server bp"]
        direction TB
        SSHD["sshd :SSH-PORT<br/>nur Public-Key"]
        APA["Apache 2.4<br/>prefork + mod_php<br/>:80 / :443"]
        PHP["PHP 8.4<br/>(mod_php, OPcache)"]
        PHPBB["phpBB 3.3.19<br/>/var/www/forum"]
        DB[("MariaDB 11.8<br/>127.0.0.1:3306<br/>DB: forum")]
        CB["certbot.timer<br/>Let's Encrypt"]
        CRON["cron<br/>04:00 Bildkompression"]
        MX["Externer SMTP<br/>(Mailanbieter)"]
        UU["unattended-upgrades<br/>apt-daily timer"]
    end

    FW --> SSHD
    FW --> APA
    APA --> PHP --> PHPBB
    PHPBB -- "mysqli, nur localhost" --> DB
    PHPBB -- "SMTP ausgehend" --> MX
    CB -- "Zertifikat in /etc/letsencrypt" --> APA
    CRON -- "forum_compress_daily.sh" --> PHPBB
```

## 3. Request-Fluss

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as Apache :80
    participant S as Apache :443
    participant P as PHP / phpBB
    participant D as MariaDB

    B->>A: GET http://example.org/...
    A-->>B: 301 → https://www.example.org/...
    B->>S: GET https://www.example.org/...
    S->>P: mod_php führt index.php aus
    P->>D: SQL (localhost)
    D-->>P: Daten
    P-->>S: HTML
    S-->>B: 200
```

`example.com` / `www.example.com` werden per 301 auf `https://www.example.org` umgeleitet (ACME-Pfad `/.well-known/acme-challenge/` bleibt ausgenommen).

## 4. Netzwerk und Ports

```mermaid
flowchart LR
    I(("Internet"))
    subgraph H["bp"]
        PSSH["SSH-Port<br/>SSH"]
        P80["80/tcp<br/>HTTP → Redirect"]
        P443["443/tcp<br/>HTTPS"]
        P3306["3306/tcp<br/>MariaDB<br/>nur 127.0.0.1"]
    end
    I -->|erlaubt| PSSH
    I -->|erlaubt| P80
    I -->|erlaubt| P443
    I -. "blockiert (ufw default deny)" .-> P3306
```

| Port | Dienst | Erreichbar von |
|---|---|---|
| SSH-Port (frei gewählt) | sshd | überall (IPv4 + IPv6), nur Key-Login |
| 80/tcp | Apache | überall, leitet auf HTTPS um |
| 443/tcp | Apache | überall |
| 3306/tcp | MariaDB | nur `127.0.0.1` |


## 5. Zertifikate (TLS)

```mermaid
flowchart LR
    T["certbot.timer<br/>(systemd)"] --> C["certbot renew"]
    C -- "ACME HTTP-01" --> LE["Let's Encrypt"]
    LE -- "GET /.well-known/acme-challenge/" --> A["Apache :80"]
    C --> F["/etc/letsencrypt/live/<br/>www.example.org/"]
    F --> A2["Apache :443<br/>fullchain.pem + privkey.pem"]
```

Ein SAN-Zertifikat (ECDSA) für vier Namen: `www.example.org`, `example.org`, `www.example.com`, `example.com`.

## 6. Verzeichnis- und Datenlayout

```mermaid
flowchart TB
    ROOT["/ (ext4)"]
    ROOT --> WWW["/var/www/forum<br/>phpBB<br/>Owner www-data"]
    ROOT --> DBD["/var/lib/mysql"]
    ROOT --> LEC["/etc/letsencrypt"]
    ROOT --> APC["/etc/apache2/sites-enabled<br/>forum.conf, forum-le-ssl.conf"]
    ROOT --> LOG["/var/log/apache2<br/>forum_access.log, forum_error.log"]
    ROOT --> RT["/root<br/>Skripte, alte Backups"]
    WWW --> FILES["files/ (Anhänge)"]
    WWW --> EXT["ext/ eigene Erweiterungen, phpbb"]
    WWW --> CFG["config.php (640, Geheimnis)"]
```
