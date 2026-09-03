# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**RCD Corp Synthetic Data Generator** — a CLI tool that produces reproducible, realistic synthetic operational data for a fictional mid-to-large enterprise. Outputs 40+ interconnected tables across 10 business domains (sales, finance, marketing, social media, supply chain, manufacturing, HR, support, observability) to CSV, Parquet, and/or PostgreSQL.

## Commands

```bash
# Install
pip install -e .

# Generate data
rcd-data generate --profile demo --seed 42 --sink parquet
rcd-data generate --profile demo --seed 42 --sink csv
rcd-data generate --profile standard --seed 42 --sink all
rcd-data generate --profile demo --only sales,finance  # single domain

# Validate referential integrity
rcd-data validate --output ./output --format parquet
pytest rcd_data/tests/test_referential_integrity.py -v  # same checks

# Show profile info
rcd-data info

# Lint
ruff check rcd_data/
```

**Profiles:** `demo` (~200k rows, 30 days), `standard` (~15M rows, 90 days), `loadtest` (~200M+ rows, 730 days).

**Sinks:** `csv`, `parquet`, `jsonl`, `xlsx`, `postgres`, `sqlserver`, `all`. PostgreSQL requires `RCD_POSTGRES_URL` env var; SQL Server requires `RCD_SQLSERVER_URL` env var (and ODBC Driver 18 for SQL Server installed locally). XLSX is capped at Excel's 1,048,576-row sheet limit — rows beyond that are truncated with a warning, so it's realistically usable only with the `demo` profile.

## Architecture

### Execution Flow

`main.py` (Typer CLI) orchestrates three phases:

1. **Master data** — `MasterDataGenerator` builds dimension tables (customers, products, employees, stores, warehouses, suppliers, fx_rates). PKs are stored in `MasterCache` as numpy arrays for fast FK sampling in phase 3.
2. **Crisis days** — `generate_crisis_days()` deterministically picks "crisis" dates that alter sentiment, ticket volume, and cancellation rates across multiple domains.
3. **Fact domains** — 9 domain generators run sequentially; each receives the `MasterCache` and samples FKs from it. High-volume generators (`manufacturing`, `observability`) implement `generate_chunked()` which is activated for the `loadtest` profile to stay memory-bounded.

### Generator Pattern

Every generator inherits `BaseGenerator` (in `generators/base.py`):

```python
class BaseGenerator(ABC):
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)

    @abstractmethod
    def generate(cache, profile, crisis_days) -> dict[str, pd.DataFrame]: ...

    def generate_chunked(...) -> Iterator[dict]: ...  # optional override
```

`generate()` returns `{table_name: DataFrame}` — the dispatcher handles writing. The `MasterCache` is the shared FK source; never hardcode IDs.

### Key Supporting Modules

- **`utils/state_machines.py`** — `OrderLifecycle`, `TicketLifecycle`, `LeadPipeline`, `ShipmentTracking`, `RecruitmentFunnel`, `ProductionRunStatus`. Each has a `_crisis_overrides()` hook.
- **`utils/time_utils.py`** — `black_friday_multiplier()`, `payday_multiplier()` (Brazilian 5th/20th), `timestamp_in_business_hours()`, `timestamp_social_peak()`, `random_datetime()`, `random_date()`.
- **`utils/distributions.py`** — `pareto_ltv()`, `weighted_choice()`, `normal_clipped()`, `seasonal_multipliers()`.
- **`utils/identifiers.py`** — valid CPF/CNPJ check-digit generation, SKU, UUID, tracking numbers.
- **`generators/base.py`** — also houses `MasterCache`, `ProfileConfig` (Pydantic), and `SinkDispatcher`.

### Reproducibility

Seed is applied at startup to `random`, `numpy`, and `Faker`. Same `--seed` → byte-identical output. Do not call `random` or `np.random` directly in generators — always use `self.rng` (the instance-level `np.random.default_rng`).

### Config

`rcd_data/config.yaml` is the single source of truth for volume scaling, date ranges, crisis parameters, company metadata (currencies, countries, departments), and Postgres connection defaults. `load_profile()` in `main.py` returns a typed `ProfileConfig` from it.

### Parquet Partitioning

High-volume tables (`machine_telemetry`, `app_logs`, `api_requests`) are always written as date-partitioned Parquet (via PyArrow `write_to_dataset`). Regular tables get a flat `data.parquet` file inside a per-table directory.

## Common Pitfalls

- **`random_datetime(start, end, rng)`** requires `end > start`. When subtracting a buffer (e.g., `profile.end - timedelta(days=30)`), clamp with `max(profile.start, ...)` to avoid `ValueError: high <= 0`.
- **FK sampling** must go through `MasterCache` methods (`cache.sample_customer_ids(n, rng)`, etc.) — do not re-read Parquet files inside generators.
- **Crisis behavior** is opt-in per generator. Check if `d in crisis_days_set` when generating per-row timestamps or state transitions.
