# Running RCD Data Generator on a Home Lab (Tailscale)

Turns the local CLI into a standing service on a home-lab box (e.g. an
Ubuntu server managed via Cockpit): a `demo`-profile dataset is generated
once into every sink (CSV, Parquet, JSONL, XLSX, Postgres, SQL Server), then
`rcd-data stream --sink all` keeps appending fresh rows to *all* of them
continuously.

**This is not a public-internet deployment.** A home network doesn't have
the same exposure profile as a rented VPS — no stable public IP (often
behind CGNAT), and a compromised exposed service sits on the same network
as your other home devices. So instead of opening router ports, database
access goes over **Tailscale**: an encrypted mesh network between only the
devices you approve. Nothing here opens an inbound port on your router.

There is currently no file server / public HTTP exposure in this setup —
that piece (Nginx + TLS + Basic Auth) was removed along with the VPS
approach. If you later need the output files reachable by something that
isn't on your tailnet, look at Tailscale Funnel (public HTTPS ingress for
one local service, zero domain needed) or a Cloudflare Tunnel (needs a
domain, adds Cloudflare Access/WAF) — pick that back up as a separate task
rather than assuming it's covered here.

## 1. Install Tailscale on the server

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
Authenticate via the printed browser link, then get the server's stable
tailnet IP (persists across reboots — it's tied to the device's identity,
not DHCP):
```bash
tailscale ip -4   # e.g. 100.101.102.103
```

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out/in for the group change to take effect
```

## 3. Clone the repo and configure secrets

```bash
git clone https://github.com/lorenzouriel/rcd-corp
cd rcd-corp
cp .env.example .env
```

Edit `.env`:
- Set strong `POSTGRES_PASSWORD` and `MSSQL_SA_PASSWORD` (generate with
  `openssl rand -base64 24`) — Tailscale controls *reachability*, not
  authentication, so weak DB passwords are still a real risk to anyone else
  on your tailnet.
- Set `POSTGRES_BIND` and `SQLSERVER_BIND` to the server's Tailscale IP from
  step 1 (e.g. `100.101.102.103`), and `SQLSERVER_PORT=1433` (the `14330`
  default only exists to dodge a local Windows dev conflict — irrelevant on
  a Linux host). **Do not set either `*_BIND` to `0.0.0.0`** — binding to
  the Tailscale IP specifically is what keeps the DB off the LAN and off
  the internet; there's nothing else enforcing that boundary.

## 4. Bring the stack up

```bash
docker compose --profile run up -d --build
```

This runs, in order: `postgres` + `sqlserver` (healthy) → `sqlserver-init`
(creates the `rcd_corp` DB) → `generator` (one-shot `generate --sink all`,
populates both DBs + `./output`) → `streamer` (continuous `stream --sink
all`, appends to `./output` and both databases every tick).

## 5. Connect from another device

Install Tailscale on that device too and join the same tailnet, then
connect exactly like any normal DB connection, using the server's Tailscale
IP:
```bash
psql "postgresql://rcd:<pw>@100.101.102.103:5432/rcd_corp"
sqlcmd -S 100.101.102.103,1433 -U sa -P <pw> -C
```

## 6. (Recommended) Restrict which tailnet devices can reach the DB ports

By default every device on your tailnet can reach every other device. If
you don't want that — e.g. a phone you added for something unrelated
shouldn't be able to hit Postgres — tag the server and scope access in the
tailnet policy file (admin console → Access Controls):
```json
{
  "tagOwners": { "tag:db-server": ["autogroup:admin"] },
  "acls": [
    { "action": "accept", "src": ["your-user-or-device-tag"], "dst": ["tag:db-server:5432,1433"] }
  ]
}
```
Tag the server: `sudo tailscale up --advertise-tags=tag:db-server`.

## 7. Verify

```bash
docker compose ps
# postgres/sqlserver: healthy · generator: exited (0) · streamer: running
```

From a device **on your tailnet**:
```bash
psql "postgresql://rcd:<pw>@<tailscale-ip>:5432/rcd_corp" -c '\dt'
sqlcmd -S <tailscale-ip>,1433 -U sa -P <pw> -C -Q "SELECT COUNT(*) FROM customers"
```

From a device **not on your tailnet**, confirm the ports are unreachable —
there should be nothing to connect to at all, not even a refused connection
on your public IP (Tailscale traffic doesn't touch the LAN/WAN interfaces).

Streaming: wait ~10 minutes (two ticks at the default 300s interval), then
rerun the `SELECT COUNT(*)` queries above and confirm the counts grew.

```bash
docker compose logs -f streamer
```

## Ongoing operations

- **Unbounded growth**: `stream` never stops appending — a new Parquet file
  per tick per table, CSV/JSONL grow forever, and Postgres/SQL Server rows
  accumulate with no dedup or pruning. Watch `df -h` on `./output` and the
  DB volumes; there's no retention built in yet — a cron job deleting old
  `stream_*.parquet` files and/or a periodic `DELETE ... WHERE created_at <
  now() - interval` on the DB tables is the straightforward follow-up if
  this becomes a problem.
- **Rotating secrets**: edit `.env`, then `docker compose up -d` to recreate
  the affected containers.
- **Cockpit**: if you're managing this box via Cockpit (`:9090`), keep that
  off the public internet the same way — access it over Tailscale rather
  than exposing the port directly.
- **Re-running a specific domain**: `docker compose run --rm generator rcd-data generate --profile demo --only <domain> --sink all`.
