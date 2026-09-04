# RCD Corp Lakehouse — Foundation Design

Medallion-architecture lakehouse plan built on top of the `rcd_data` synthetic
data generator. The generator's 55 tables (across 10 domains) are split into
three *simulated source systems* — PostgreSQL, CSV, and Parquet — mirroring
the kind of heterogeneous sources a real mid-to-large enterprise would have.
Bronze/silver/gold sits on top and unifies them.

Design-only document. No compute engine (DuckDB / dbt / Spark) has been
chosen yet — that's an open decision, see bottom.

---

## 1. Source-system split

### PostgreSQL — OLTP systems of record (27 tables)

Relational, needs referential integrity, moderate volume, point-in-time
updates.

| Group | Tables |
|---|---|
| Master/reference | `customers`, `employees`, `stores`, `warehouses`, `suppliers`, `products`, `fx_rates` |
| Sales core | `orders`, `order_items`, `payments` |
| Finance | `invoices`, `transactions`, `expenses`, `budgets`, `rcd_card_transactions` |
| Support | `tickets`, `ticket_messages`, `call_center_calls` |
| Supply chain ops | `purchase_orders`, `shipments`, `stock_movements`, `returns` |
| HR | `attendance`, `performance_reviews`, `training_records`, `recruitment_pipeline`, `engagement_surveys` |

### CSV — flat-file batch / vendor exports (19 tables)

Low-to-moderate volume, semi-structured, loosely governed — the kind of data
that arrives as exports from marketing/social tools or plant-floor MES
systems in a real company.

| Group | Tables |
|---|---|
| Marketing | `campaigns`, `campaign_events`, `email_events`, `leads`, `ab_test_exposures` |
| Social media | `social_accounts`, `social_posts`, `social_metrics`, `social_comments`, `social_mentions`, `social_dms`, `influencer_partnerships`, `influencer_posts`, `community_forum_posts`, `reviews`, `social_ad_spend` |
| Manufacturing ops | `production_runs`, `quality_checks`, `maintenance_events` |

### Parquet — high-volume columnar / event & time-series (9 tables)

Append-only, high-cardinality, benefits from columnar compression and
partitioning. The generator already writes some of these as date-partitioned
Parquet natively.

| Group | Tables |
|---|---|
| Observability | `errors`, `deployments`, `security_events`, plus `app_logs`, `api_requests` (chunked/partitioned, **loadtest profile only**) |
| Manufacturing | `machine_telemetry` (chunked/partitioned, **loadtest profile only**) |
| Sales behavioral | `web_sessions`, `shopping_cart_events` |
| Supply chain | `inventory_snapshots` |

> `app_logs`, `api_requests`, and `machine_telemetry` only exist under the
> `loadtest` profile — the `demo` and `standard` profiles use each domain's
> regular (non-chunked) `generate()`, which doesn't produce them. See
> [Common pitfall](#note-on-loadtest-only-tables) below.

---

## 2. Medallion layers

### Bronze (landing, schema-on-read)

- Extract as-is from each source, tagged with `_source_system`,
  `_source_format`, `_ingested_at`. No joins, no transformation.
- Postgres → batch/incremental extract per table. CSV → raw append, columns
  read as strings (mimics real-world messiness). Parquet → pass-through
  copy/repartition.
- Layout convention: `lakehouse/bronze/<source>/<table>/dt=YYYY-MM-DD/`.

### Silver (conformed)

- Type casting, dedup, timestamp normalization to UTC, currency
  normalization via `fx_rates`.
- Referential integrity enforced against conformed dimensions — this
  generalizes the checks already in
  [`rcd_data/tests/test_referential_integrity.py`](../rcd_data/tests/test_referential_integrity.py),
  now applied post-ingestion instead of at generation time.
- Split conformed **dimensions** (customers, products, employees, stores,
  warehouses, suppliers — SCD2 if history is wanted) from conformed
  **facts** (orders, tickets, telemetry, etc.), regardless of which of the
  3 sources they came from.

### Gold (marts)

Business-facing, denormalized, one mart per domain:

- `sales_mart` — revenue/AOV/orders by day-store-region
- `customer_360` — orders + tickets + social sentiment + campaigns per customer
- `finance_mart` — P&L-style rollups, budget vs. actual
- `supply_chain_mart` — inventory turns, fulfillment SLAs, PO cycle time
- `marketing_mart` — funnel/CAC/ROI by campaign
- `ops_mart` — error rates, deploy frequency, SLIs from observability
- `hr_mart` — headcount, attrition, engagement trends
- `crisis_impact` (optional) — leverages the generator's existing crisis-day
  mechanism to show cross-domain effects (ticket spikes, sentiment drops,
  cancellations) in one view

---

## 3. How to generate each dataset

The CLI (`rcd_data/main.py`) writes per **domain**, not per table — running
a domain writes *all* of its tables to whichever `--sink` you pick. There is
no per-table sink routing built in today. Two ways to get the 3-way split
above, in increasing order of fidelity:

### Option A — one full run, all sinks (recommended for now)

Generates every table into all three sinks simultaneously, deterministically
(same `--seed` → byte-identical output). Bronze ingestion then reads each
table only from its assigned zone (per the tables above) and ignores the
copies in the other two.

```bash
# requires RCD_POSTGRES_URL to be set for the postgres leg, e.g.:
export RCD_POSTGRES_URL="postgresql+psycopg2://rcd:rcd@localhost:5432/rcd_corp"

rcd-data generate --profile demo --seed 42 --sink all
```

Output locations:
- **Postgres** → tables in the DB at `RCD_POSTGRES_URL`
- **CSV** → `./output/csv/<table>.csv`
- **Parquet** → `./output/parquet/<table>/data.parquet` (flat tables) or
  `./output/parquet/<table>/dt=YYYY-MM-DD/*.parquet` (partitioned tables)

This is the simplest, fully reproducible option and needs no CLI changes.

### Option B — per-zone runs (closer to "physically separated" sources)

Only write each domain to the sink it's meant to live in. Note the caveats:

- `master_data` is generated in phase 1 of every run, but is only **written**
  when `--only` is omitted. To write master data alone with a specific sink,
  pass `--only master_data` explicitly (it's re-run as a fact domain and
  written normally).
- `sales` and `supply_chain` straddle two zones: `sales` also produces
  `web_sessions`/`shopping_cart_events` (Parquet zone), and `supply_chain`
  also produces `inventory_snapshots` (Parquet zone). Running these domains
  with `--sink postgres` will also drop those Parquet-zone tables into
  Postgres as a side effect — for a clean split, either ignore the
  Postgres copies of those specific tables in your bronze ingestion, or
  re-run the domain a second time with `--sink parquet` and keep only the
  relevant table files.

```bash
# --- PostgreSQL zone ---
rcd-data generate --profile demo --seed 42 --sink postgres --only master_data
rcd-data generate --profile demo --seed 42 --sink postgres --only sales,finance,support,supply_chain,hr

# --- CSV zone (marketing, social_media, manufacturing map cleanly — no straddling) ---
rcd-data generate --profile demo --seed 42 --sink csv --only marketing,social_media,manufacturing

# --- Parquet zone ---
rcd-data generate --profile demo --seed 42 --sink parquet --only sales,supply_chain,observability
```

For `loadtest` profile, chunked high-volume tables (`machine_telemetry`,
`app_logs`, `api_requests`) are automatically forced to Parquet regardless of
`--sink`, so no extra step is needed for those once you run with
`--profile loadtest`.

### Validate referential integrity

After generating, sanity-check FK relationships:

```bash
rcd-data validate --output ./output --format parquet
# or, equivalently:
pytest rcd_data/tests/test_referential_integrity.py -v
```

### Profiles

| Profile | Rows | Date range | Notes |
|---|---|---|---|
| `demo` | ~200k | 30 days | fast iteration, good for building bronze/silver pipelines |
| `standard` | ~15M | 90 days | closer to production analytics scale |
| `loadtest` | ~200M+ | 730 days | stresses chunked/partitioned tables (`machine_telemetry`, `app_logs`, `api_requests`); use `generate_chunked` |

---

## 4. Open items for when you're ready to build

- Compute/orchestration engine (deferred — DuckDB / dbt / Spark are all
  viable given the demo→loadtest volume spread).
- Incremental vs. full-refresh strategy per source (Postgres lends itself to
  CDC/incremental; CSV/Parquet drops are more naturally full-batch per
  ingestion window).
- Whether bronze re-materializes everything as Parquet/Delta regardless of
  source format, or keeps native format with a catalog layer (Iceberg/Delta/
  Hive-style) on top.

### Note on loadtest-only tables

`app_logs`, `api_requests`, and `machine_telemetry` are produced by each
generator's `generate_chunked()` override, which `main.py` only invokes when
`profile == "loadtest"`. Under `demo`/`standard`, `observability` yields just
`errors`/`deployments`/`security_events`, and `manufacturing` yields just
`production_runs`/`quality_checks`/`maintenance_events`. Keep this in mind
when sizing bronze ingestion for anything but the `loadtest` profile.
