# Deploying RCD Data Generator to a VPS

Turns the local CLI into a standing service: a `demo`-profile dataset is
generated once into Postgres, SQL Server, and every file sink (CSV, Parquet,
JSONL, XLSX), then `rcd-data stream --sink all` keeps appending fresh rows to
the file sinks continuously. Files are browsable over HTTPS; the databases
are reachable by external clients, restricted to an IP allowlist at the
firewall.

**Known limitation:** `rcd-data stream` rejects `--sink postgres` and
`--sink sqlserver` outright — it only ever writes to file sinks, even when
passed `--sink all` (`SinkDispatcher.append_all` in
[base.py](rcd_data/generators/base.py) silently skips DB sinks). So the
databases hold one fixed snapshot from the initial `generate`, while the
files keep growing. This is a limitation of the current CLI, not this
deployment.

## 1. Provision the VPS

- Ubuntu 22.04 or 24.04 LTS, minimum **4 vCPU / 8 GB RAM / 60 GB SSD**
  (SQL Server 2025 alone wants ≥2 GB headroom; Postgres + the generator
  container need modest but real overhead on top).
- Create a non-root sudo user and disable password SSH login (key-only):
  ```bash
  adduser deploy && usermod -aG sudo deploy
  # then in /etc/ssh/sshd_config: PasswordAuthentication no
  systemctl restart sshd
  ```
- Optional but recommended: `sudo apt install -y fail2ban`.

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out/in for the group change to take effect
```

## 3. Firewall (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp        # SSH — restrict to your IP if it's static, see below
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Database access — repeat for every consumer IP (BI tool, teammate, CI runner, ...)
sudo ufw allow from <ADMIN_IP> to any port 5432 proto tcp
sudo ufw allow from <ADMIN_IP> to any port 1433 proto tcp

sudo ufw enable
sudo ufw status numbered     # verify before walking away
```

To add/remove a consumer later: `sudo ufw allow from <ip> to any port 5432 proto tcp`
or `sudo ufw delete <rule-number>` (from `ufw status numbered`). Never
`ufw allow 5432` / `1433` without `from <ip>` — that opens it to the whole
internet, which is explicitly not the model here.

If your own IP is static, also restrict port 22 the same way instead of
leaving it open to `any`.

## 4. Clone the repo and configure secrets

```bash
git clone https://github.com/lorenzouriel/rcd-corp
cd rcd-corp
cp .env.example .env
```

Edit `.env`:
- Set strong `POSTGRES_PASSWORD` and `MSSQL_SA_PASSWORD` (generate with
  `openssl rand -base64 24`) — **do not deploy with the `rcd`/`Rcd!Passw0rd`
  defaults publicly.**
- Set `POSTGRES_BIND=0.0.0.0`, `SQLSERVER_BIND=0.0.0.0`, `SQLSERVER_PORT=1433`
  (the `14330` default only exists to dodge a local Windows dev conflict —
  not needed on a fresh VPS).
- Set `DOMAIN` if you have one pointed at the VPS's IP (A record). Leave
  blank to use the self-signed fallback in step 6.

## 5. Basic Auth for the file server

```bash
sudo apt install -y apache2-utils
htpasswd -c infra/nginx/.htpasswd <username>
```
(drop `-c` for additional users after the first).

## 6. TLS

**With a domain** (recommended): point its A record at the VPS IP first,
then:
```bash
cp infra/nginx/rcd-data.conf.example infra/nginx/rcd-data.conf
sed -i "s/YOUR_DOMAIN/<your-domain>/g" infra/nginx/rcd-data.conf
mkdir -p infra/certbot/www infra/certbot/conf/live/<your-domain>

# Nginx's config expects a cert to already exist at that path before it will
# start — but certbot needs Nginx running on port 80 to answer the HTTP-01
# challenge and issue the real one. Break the chicken-and-egg with a throwaway
# self-signed placeholder so Nginx can boot; certbot overwrites it below.
openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
  -keyout infra/certbot/conf/live/<your-domain>/privkey.pem \
  -out infra/certbot/conf/live/<your-domain>/fullchain.pem \
  -subj "/CN=<your-domain>"

docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile run up -d nginx

docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tls run --rm certbot \
  certonly --webroot -w /var/www/certbot -d <your-domain> \
  --email you@example.com --agree-tos --non-interactive --force-renewal

docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```
Renewal (add to root's crontab, twice daily is the certbot-recommended cadence):
```
0 3,15 * * * cd /path/to/rcd-corp && docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tls run --rm certbot renew -q && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```

**Without a domain** (self-signed, browsers will show a warning):
```bash
mkdir -p infra/certbot/conf/live/selfsigned
openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout infra/certbot/conf/live/selfsigned/privkey.pem \
  -out infra/certbot/conf/live/selfsigned/fullchain.pem \
  -subj "/CN=$(curl -s ifconfig.me)"
cp infra/nginx/rcd-data.conf.example infra/nginx/rcd-data.conf
sed -i "s/YOUR_DOMAIN/_/g" infra/nginx/rcd-data.conf
# then edit infra/nginx/rcd-data.conf: comment the Let's Encrypt
# ssl_certificate lines and uncomment the selfsigned ones (see the file's comments)
```

## 7. Bring the stack up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile run up -d --build
```

This runs, in order: `postgres` + `sqlserver` (healthy) → `sqlserver-init`
(creates the `rcd_corp` DB) → `generator` (one-shot `generate --sink all`,
populates both DBs + `./output`) → `streamer` (continuous `stream`, appends
to `./output` only) + `nginx` (serves `./output`).

## 8. Verify

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
# postgres/sqlserver: healthy · generator: exited (0) · streamer/nginx: running
```

From an **allowlisted** IP:
```bash
psql "postgresql://rcd:<pw>@<vps-ip>:5432/rcd_corp" -c '\dt'
sqlcmd -S <vps-ip>,1433 -U sa -P <pw> -C -Q "SELECT COUNT(*) FROM customers"
```

From a **non-allowlisted** IP, confirm the ports are unreachable (connection
should time out, not just auth-fail):
```bash
nc -vz -w 3 <vps-ip> 5432   # expect "Connection timed out" / refused
```

Files:
```bash
curl -u <user>:<pass> https://<domain-or-ip>/output/     # 200, directory listing
curl https://<domain-or-ip>/output/                       # 401 without credentials
```

Streaming: wait ~10 minutes (two ticks at the default 300s interval), then
confirm `./output/parquet/orders/` has a new `stream_<ts>.parquet` file and
`./output/csv/orders.csv` has grown, while Postgres/SQL Server row counts
are unchanged from step 7 (expected — see the limitation noted above).

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f streamer
```

## Ongoing operations

- **Disk growth**: `stream` writes a new Parquet file per tick per table
  and appends to CSV forever. Watch `df -h` on `./output`; there's no
  built-in pruning yet — a cron job deleting `stream_*.parquet` older than
  N days is the straightforward follow-up if this becomes a problem.
- **Rotating secrets**: edit `.env`, then
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
  to recreate the affected containers.
- **Adding/removing a DB consumer IP**: `sudo ufw allow from <ip> to any port 5432 proto tcp` /
  `sudo ufw delete <rule-number>` (see step 3).
- **Re-running a specific domain**: `docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm generator rcd-data generate --profile demo --only <domain> --sink all`.
