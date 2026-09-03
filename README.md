<div align="center">
  <img src="docs/rcd-logo.png" alt="logo" width="600">
</div>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Python CLI that generates realistic, interconnected operational data for **RCD (Real Company Data) Corp**, a fictional mid-to-large enterprise, across **10 business domains**, writing to **CSV**, **Parquet**, **Postgres**, and **SQL Server**.
```
RCD Corp — founded 2008, HQ São Paulo (BR), offices in Mexico City, Lisbon, Miami
~4,200 employees · ~$1.2B annual revenue · Ticker: RCDC
```

## Quick Start
```bash
# Install
pip install -e .

# Generate demo data (~10k rows/fact table) → Parquet
rcd-data generate --profile demo --seed 42 --sink parquet

# Generate standard data (~1M orders) → all sinks
rcd-data generate --profile standard --sink all

# Generate only social media and support domains
rcd-data generate --profile demo --only social_media,support --sink csv

# Stream live batches — appends 25 rows/domain every 5 min to existing output
rcd-data stream --profile demo --seed 42 --rows-per-tick 25 --interval 300

# Validate referential integrity
RCD_OUTPUT_DIR=./output rcd-data validate

# Show profile sizes
rcd-data info
```

## Setup
### Local (Python 3.11+)
```bash
git clone https://github.com/lorenzouriel/rcd-corp
cd rcd-corp
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### With Postgres (docker-compose)
```bash
docker compose up -d postgres
export RCD_POSTGRES_URL="postgresql+psycopg2://rcd:rcd@localhost:5432/rcd_corp"
$env:RCD_POSTGRES_URL="postgresql+psycopg2://rcd:rcd@localhost:5432/rcd_corp"
rcd-data generate --profile demo --sink all
```

### With SQL Server (docker-compose)
Requires the [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) installed locally (already baked into the Docker image).
```bash
docker compose up -d sqlserver sqlserver-init
export RCD_SQLSERVER_URL="mssql+pyodbc://sa:Rcd!Passw0rd@localhost:14330/rcd_corp?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
$env:RCD_SQLSERVER_URL="mssql+pyodbc://sa:Rcd!Passw0rd@localhost:14330/rcd_corp?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
rcd-data generate --profile demo --sink sqlserver
```

### Docker (full end-to-end)
```bash
docker compose --profile run up --build
```

## CLI Reference
```
rcd-data generate [OPTIONS]
rcd-data stream   [OPTIONS]
rcd-data validate [OPTIONS]
rcd-data info     [OPTIONS]
```

### `generate` options
| Option | Default | Description |
|--------|---------|-------------|
| `--profile` | `demo` | Volume profile: `demo` · `standard` · `loadtest` |
| `--seed` | `42` | Random seed — same seed = identical output |
| `--sink` | `parquet` | Output sink: `csv` · `parquet` · `jsonl` · `xlsx` · `postgres` · `sqlserver` · `all` |
| `--only` | (all) | Comma-separated domain list to generate selectively |
| `--config` | built-in | Path to a custom `config.yaml` |

### `stream` options

Requires a prior `generate` run — reads the existing output to rebuild dimension FK tables, then continuously appends small batches to the same directory.

| Option | Default | Description |
|--------|---------|-------------|
| `--profile` | `demo` | Profile to use for FK pool sizing |
| `--seed` | `42` | Base seed; tick N uses `seed + N` to avoid duplicate PKs |
| `--sink` | `parquet` | Output sink: `csv` · `parquet` · `jsonl` (Postgres/SQL Server not supported) |
| `--rows-per-tick` | `25` | Approximate rows per domain per tick |
| `--interval` | `300` | Seconds between ticks; `0` = fire once and exit |
| `--config` | built-in | Path to a custom `config.yaml` |

```bash
# One-time setup
rcd-data generate --profile demo --seed 42 --sink parquet

# Live streaming (runs until Ctrl+C)
rcd-data stream --profile demo --seed 42 --rows-per-tick 25 --interval 300

# Single tick — useful for testing
rcd-data stream --profile demo --seed 42 --interval 0
```

### `validate` options
| Option | Default | Description |
|--------|---------|-------------|
| `--output` | `./output` | Path to generated output root |
| `--format` | `parquet` | Format to validate: `parquet` · `csv` |

### Domain names for `--only`
```
master_data  sales  finance  marketing  social_media
supply_chain  manufacturing  hr  support  observability
```

## Volume Profiles
| Profile | Customers | Orders | Employees | Date Range | Approx Total Rows |
|---------|-----------|--------|-----------|------------|-------------------|
| `demo` | 1,000 | 10,000 | 200 | 30 days | ~200k |
| `standard` | 50,000 | 1,000,000 | 4,200 | 360 days | ~15M |
| `loadtest` | 500,000 | 20,000,000 | 4,200 | 730 days | ~200M+ |

> **Note:** `machine_telemetry` and `api_requests` / `app_logs` are written as date-partitioned Parquet only on the `loadtest` profile regardless of `--sink`, to prevent OOM.

## Output Structure
```
output/
├── csv/
│   ├── customers.csv
│   ├── orders.csv          ← stream appends rows, header preserved
│   └── ...
└── parquet/
    ├── customers/
    │   └── data.parquet
    ├── orders/
    │   ├── data.parquet           ← original from generate
    │   └── stream_<ts>.parquet    ← appended by stream (one file per tick)
    ├── machine_telemetry/
    │   └── date=2024-01-01/       ← date-partitioned; stream adds new partitions
    │       └── ...
    └── ...
```

Parquet consumers (`pd.read_parquet(dir)`, DuckDB, Spark) automatically read all files in a table directory, so historical and streamed rows are always combined.

## Schema Reference
### Master Data
| Table | Key Columns | Description |
|-------|-------------|-------------|
| `customers` | `id`, `segment`, `country`, `ltv_tier`, `cpf_or_cnpj` | 75% B2C, 20% B2B, 5% VIP; Pareto LTV |
| `products` | `sku`, `brand`, `category`, `price`, `currency` | 9 RCD branded + up to 200 third-party SKUs |
| `employees` | `id`, `department`, `level`, `salary`, `manager_id` | 7-level IC hierarchy + 5-level management |
| `suppliers` | `id`, `country`, `rating`, `lead_time_days` | |
| `stores` | `id`, `type`, `country`, `city` | flagship/standard/outlet/pop_up/online/warehouse |
| `warehouses` | `id`, `type`, `location`, `capacity_m3` | central/regional/dark_store |
| `fx_rates` | `date`, `from_currency`, `to_currency`, `rate` | BRL/MXN/EUR/USD — daily random walk |

### Sales & E-commerce
| Table | Key Columns | Description |
|-------|-------------|-------------|
| `orders` | `id`, `customer_id`, `store_id`, `status`, `total`, `currency` | State machine: pending→paid→shipped→delivered |
| `order_items` | `order_id`, `product_id`, `quantity`, `line_total` | FK: orders + products |
| `payments` | `order_id`, `method`, `gateway`, `processing_fee` | pix/credit_card/boleto/rcd_card/bnpl |
| `web_sessions` | `session_id`, `customer_id`, `device`, `utm_source` | 30% anonymous sessions |
| `shopping_cart_events` | `session_id`, `product_id`, `event_type` | view/add/remove/checkout/purchase |

### Finance
| Table | Key Columns |
|-------|-------------|
| `invoices` | `order_id`, `customer_id`, `amount`, `status` |
| `transactions` | `type`, `amount`, `currency`, `status` |
| `expenses` | `employee_id`, `category`, `amount`, `department` |
| `budgets` | `department`, `year`, `quarter`, `planned_amount`, `actual_amount` |
| `rcd_card_transactions` | `card_id`, `customer_id`, `merchant_category`, `amount` |

### Marketing
| Table | Key Columns |
|-------|-------------|
| `campaigns` | `id`, `type`, `channel`, `budget`, `status` |
| `campaign_events` | `campaign_id`, `customer_id`, `event_type` |
| `email_events` | `campaign_id`, `customer_id`, `event_type` (sent/opened/clicked/bounced) |
| `leads` | `customer_id`, `status` (state machine: new→won/lost), `score` |
| `ab_test_exposures` | `test_name`, `variant`, `customer_id`, `converted` |

### Social Media
| Table | Key Columns |
|-------|-------------|
| `social_accounts` | `handle`, `platform`, `follower_count` |
| `social_posts` | `account_id`, `platform`, `post_type`, `campaign_id` |
| `social_metrics` | `post_id`, `snapshot_ts`, `impressions`, `reach`, `likes` — hourly 72h then daily |
| `social_comments` | `post_id`, `customer_id`, `sentiment`, `language` |
| `social_mentions` | `platform`, `sentiment`, `topic` |
| `social_dms` | `account_id`, `customer_id`, `intent` |
| `influencer_partnerships` | `handle`, `tier`, `contract_value`, `campaign_id` |
| `influencer_posts` | `influencer_id`, `impressions`, `conversions`, `attributed_revenue` |
| `community_forum_posts` | `customer_id`, `category`, `upvotes`, `reply_count` |
| `reviews` | `source`, `rating`, `response_body`, `response_employee_id` |
| `social_ad_spend` | `date`, `platform`, `campaign_id`, `spend`, `conversions` |

### Supply Chain
| Table | Key Columns |
|-------|-------------|
| `shipments` | `order_id`, `warehouse_id`, `carrier`, `tracking_number`, `status` |
| `inventory_snapshots` | `product_sku`, `warehouse_id`, `date`, `quantity_on_hand` |
| `purchase_orders` | `supplier_id`, `warehouse_id`, `status`, `total_amount` |
| `stock_movements` | `product_sku`, `warehouse_id`, `movement_type`, `quantity` |
| `returns` | `order_id`, `customer_id`, `product_sku`, `reason`, `refund_amount` |

### Manufacturing
| Table | Key Columns |
|-------|-------------|
| `production_runs` | `product_sku`, `factory_location`, `status`, `planned_qty`, `actual_qty` |
| `machine_telemetry` | `machine_id`, `factory`, `timestamp`, `temperature_c`, `alert_triggered` — **partitioned Parquet** |
| `quality_checks` | `production_run_id`, `pass_rate`, `defects_found`, `result` |
| `maintenance_events` | `machine_id`, `factory`, `type`, `downtime_h`, `cost` |

### HR
| Table | Key Columns |
|-------|-------------|
| `attendance` | `employee_id`, `date`, `status`, `hours_worked`, `overtime_h` |
| `performance_reviews` | `employee_id`, `reviewer_id`, `period`, `score`, `rating` |
| `training_records` | `employee_id`, `course_name`, `provider`, `score`, `passed` |
| `recruitment_pipeline` | `position`, `department`, `status` (state machine: applied→hired/rejected) |
| `engagement_surveys` | `employee_id`, `period`, `engagement_score`, `nps` |

### Support
| Table | Key Columns |
|-------|-------------|
| `tickets` | `customer_id`, `category`, `status`, `priority`, `sentiment`, `csat_score` |
| `ticket_messages` | `ticket_id`, `sender_type`, `body` |
| `call_center_calls` | `customer_id`, `agent_id`, `duration_s`, `sentiment`, `resolution` |

### Observability
| Table | Key Columns |
|-------|-------------|
| `app_logs` | `service`, `level`, `message`, `trace_id` — **partitioned Parquet** |
| `api_requests` | `method`, `path`, `status_code`, `duration_ms` — **partitioned Parquet** |
| `errors` | `service`, `error_type`, `severity`, `resolved` |
| `deployments` | `service`, `version`, `environment`, `status` |
| `security_events` | `event_type`, `severity`, `source_ip`, `resolved` |

## Dashboard → Dataset Mapping
| Dashboard | Primary Tables |
|-----------|---------------|
| Sales / Revenue KPI | `orders`, `order_items`, `payments`, `fx_rates` |
| Funnel | `web_sessions`, `shopping_cart_events`, `orders` |
| Cohort Retention | `customers`, `orders` (signup_date + order dates) |
| Marketing Attribution & CAC/LTV | `campaigns`, `campaign_events`, `leads`, `ab_test_exposures`, `customers` |
| Social Media Performance | `social_posts`, `social_metrics`, `social_ad_spend`, `influencer_posts` |
| Brand Health & Sentiment | `social_comments`, `social_mentions`, `reviews`, `tickets` |
| Inventory Turnover | `inventory_snapshots`, `stock_movements`, `purchase_orders` |
| OEE (Overall Equipment Effectiveness) | `production_runs`, `machine_telemetry`, `maintenance_events`, `quality_checks` |
| Support CSAT & SLA | `tickets`, `ticket_messages`, `call_center_calls` |
| HR Headcount / Attrition | `employees`, `attendance`, `performance_reviews`, `recruitment_pipeline` |
| Financial P&L | `invoices`, `transactions`, `expenses`, `budgets`, `rcd_card_transactions` |
| Executive 360 | All of the above |

## Behavioral Rules Implemented
| Rule | Implementation |
|------|---------------|
| Black Friday 10x | `utils/time_utils.py:black_friday_multiplier()` |
| Brazilian payday 2x (5th/20th) | `utils/time_utils.py:payday_multiplier()` |
| December holiday surge 2x | Built into seasonal curve |
| Social engagement peaks 19–22h BRT | `utils/time_utils.py:timestamp_social_peak()` |
| Reels/Shorts 3–5x reach | `generators/social_media.py:_build_metrics()` |
| Crisis sentiment shift (55%→20% positive) | `generators/social_media.py:_build_comments()` using `SENTIMENT_WEIGHTS_CRISIS` |
| Crisis ticket spike (5x) | `generators/support.py:_build_tickets()` |
| Customer LTV Pareto (top 20% = 80%) | `utils/distributions.py:pareto_ltv()` |

## Reproducibility
Same seed → identical output:
```bash
rcd-data generate --profile demo --seed 42 --sink csv
rcd-data generate --profile demo --seed 42 --sink csv  # byte-identical
```

All RNG sources are seeded at startup: `random.seed(N)`, `np.random.seed(N)`, `Faker.seed(N)`.

## Tuning Guide
Edit `rcd_data/config.yaml` to tune output volumes without code changes.
| Knob | Where | Effect |
|------|-------|--------|
| `profiles.*.n_orders` | config.yaml | Controls orders + all downstream fact table row counts |
| `profiles.*.n_customers` | config.yaml | Master data size; affects FK cardinality |
| `profiles.*.date_range_days` | config.yaml | Temporal spread; affects seasonal patterns |
| `profiles.*.crisis_freq_per_month` | config.yaml | Number of crisis events per month |
| `profiles.*.chunk_size` | config.yaml | Rows per chunk for high-volume generators (tune for RAM) |
| `profiles.*.start_date` | config.yaml | Shifts entire date range |
| `crisis.ticket_multiplier` | config.yaml | Ticket volume on crisis days |
| `crisis.social_negative_multiplier` | config.yaml | Negative comment spike on crisis days |
| `crisis.sentiment_shift.*` | config.yaml | Positive/negative % baseline and crisis values |

### Custom profile example
```yaml
profiles:
  my_profile:
    n_customers: 10000
    n_products: 250
    n_employees: 500
    n_orders: 200000
    n_stores: 50
    n_warehouses: 5
    n_suppliers: 30
    date_range_days: 60
    crisis_freq_per_month: 1
    chunk_size: 20000
    start_date: "2024-06-01"
```

```bash
rcd-data generate --profile my_profile --sink parquet
```

## Project Structure
```
rcd_data/
├── config.yaml              # Volume profiles and company config
├── main.py                  # CLI entry point (typer) — generate, stream, validate, info
├── generators/
│   ├── base.py              # BaseGenerator (+ generate_batch), MasterCache, ProfileConfig, SinkDispatcher (+ append_all)
│   ├── master_data.py       # customers, products, employees, suppliers, stores, warehouses, fx_rates
│   ├── sales.py             # orders, order_items, payments, web_sessions, cart_events
│   ├── finance.py           # invoices, transactions, expenses, budgets, rcd_card
│   ├── marketing.py         # campaigns, events, email, leads, ab_tests
│   ├── social_media.py      # 11 social tables
│   ├── supply_chain.py      # shipments, inventory, POs, movements, returns
│   ├── manufacturing.py     # production_runs, machine_telemetry (chunked), quality, maintenance
│   ├── hr.py                # attendance, reviews, training, recruitment, surveys
│   ├── support.py           # tickets, messages, calls
│   └── observability.py     # logs (chunked), requests (chunked), errors, deployments, security
├── utils/
│   ├── distributions.py     # pareto_ltv, weighted_choice, normal_clipped
│   ├── state_machines.py    # 6 lifecycle state machines
│   ├── time_utils.py        # seasonal multipliers, crisis days, business hours
│   ├── identifiers.py       # CPF/CNPJ check digits, SKU, tracking numbers
│   └── fx.py                # daily FX rate random walk
├── sinks/
│   ├── csv_sink.py          # supports append mode (stream command)
│   ├── parquet_sink.py      # date-partitioned via PyArrow; stream_{ts}.parquet for append
│   ├── postgres_sink.py     # SQLAlchemy + psycopg2
│   └── sqlserver_sink.py    # SQLAlchemy + pyodbc (ODBC Driver 18)
└── tests/
    └── test_referential_integrity.py
```
