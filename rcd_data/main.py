"""RCD Corp synthetic data generator — CLI orchestrator."""
from __future__ import annotations

import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

import numpy as np
import pandas as pd
import structlog
import typer
from faker import Faker
from tqdm import tqdm

from .generators import (
    FinanceGenerator,
    HRGenerator,
    ManufacturingGenerator,
    MarketingGenerator,
    MasterDataGenerator,
    ObservabilityGenerator,
    SalesGenerator,
    SocialMediaGenerator,
    SupplyChainGenerator,
    SupportGenerator,
)
from .generators.base import MasterCache, SinkDispatcher, load_profile
from .utils.time_utils import generate_crisis_days

log = structlog.get_logger()

app = typer.Typer(
    name="rcd-data",
    help="RCD Corp synthetic data generator.",
    add_completion=False,
)

DEFAULT_CONFIG = str(Path(__file__).parent / "config.yaml")

DOMAIN_MAP: dict[str, type] = {
    "master_data": MasterDataGenerator,
    "sales": SalesGenerator,
    "finance": FinanceGenerator,
    "marketing": MarketingGenerator,
    "social_media": SocialMediaGenerator,
    "supply_chain": SupplyChainGenerator,
    "manufacturing": ManufacturingGenerator,
    "hr": HRGenerator,
    "support": SupportGenerator,
    "observability": ObservabilityGenerator,
}

FACT_DOMAINS = [
    "sales",
    "finance",
    "marketing",
    "social_media",
    "supply_chain",
    "manufacturing",
    "hr",
    "support",
    "observability",
]


def _seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    Faker.seed(seed)


_CACHE_TABLES = [
    "customers", "products", "employees", "suppliers",
    "stores", "warehouses", "fx_rates",
    "campaigns", "orders",
]
_REQUIRED_CACHE_TABLES = {
    "customers", "products", "employees", "suppliers", "stores", "warehouses",
}


def _load_master_cache(full_config: dict) -> MasterCache:
    out = full_config.get("output", {})
    parquet_base = Path(out.get("parquet_path", "./output/parquet"))
    csv_base = Path(out.get("csv_path", "./output/csv"))

    tables: dict[str, pd.DataFrame] = {}
    for table_name in _CACHE_TABLES:
        parquet_file = parquet_base / table_name / "data.parquet"
        csv_file = csv_base / f"{table_name}.csv"
        if parquet_file.exists():
            tables[table_name] = pd.read_parquet(parquet_file)
        elif csv_file.exists():
            tables[table_name] = pd.read_csv(csv_file)

    missing = _REQUIRED_CACHE_TABLES - set(tables.keys())
    if missing:
        typer.echo(
            f"Missing master tables: {sorted(missing)}. Run 'rcd-data generate' first.",
            err=True,
        )
        raise typer.Exit(1)

    cache = MasterCache()
    cache.populate(tables)
    return cache


def _resolve_domains(only: str | None) -> list[str]:
    if only is None:
        return FACT_DOMAINS
    requested = [d.strip() for d in only.split(",")]
    unknown = [d for d in requested if d not in DOMAIN_MAP and d != "master_data"]
    if unknown:
        typer.echo(f"Unknown domains: {unknown}. Valid: {list(DOMAIN_MAP.keys())}", err=True)
        raise typer.Exit(1)
    return requested


@app.command()
def generate(
    profile: Annotated[str, typer.Option("--profile", "-p", help="Profile: demo | standard | loadtest")] = "demo",
    seed: Annotated[int, typer.Option("--seed", "-s", help="Random seed for reproducibility")] = 42,
    sink: Annotated[str, typer.Option("--sink", help="Output sink: csv | parquet | jsonl | xlsx | postgres | sqlserver | all")] = "parquet",
    only: Annotated[Optional[str], typer.Option("--only", help="Comma-separated list of domains to generate")] = None,
    config: Annotated[str, typer.Option("--config", "-c", help="Path to config.yaml")] = DEFAULT_CONFIG,
) -> None:
    """Generate synthetic RCD Corp data and write to the selected sink(s)."""
    t_start = time.perf_counter()
    log.info("generation_start", profile=profile, seed=seed, sink=sink)

    # 1. Seed all RNG sources
    _seed_all(seed)

    # 2. Load profile and config
    profile_cfg, full_config = load_profile(config, profile)
    dispatcher = SinkDispatcher.from_flag(sink, profile_cfg, full_config)

    # 3. Phase 1 — Master data
    cache = MasterCache()
    typer.echo(f"[1/3] Generating master data (profile={profile}, seed={seed})")
    master_gen = MasterDataGenerator(seed=seed)
    master_tables = master_gen.generate(cache, profile_cfg, crisis_days=[])
    cache.populate(master_tables)
    if only is None:
        dispatcher.write_all(master_tables)
    log.info(
        "master_data_complete",
        tables=list(master_tables.keys()),
        rows={k: len(v) for k, v in master_tables.items()},
    )

    # 4. Pick crisis days
    crisis_days = generate_crisis_days(
        profile_cfg.start,
        profile_cfg.end,
        profile_cfg.crisis_freq_per_month,
        np.random.default_rng(seed + 1),
    )
    log.info("crisis_days", days=[str(d) for d in crisis_days])

    # 5. Phase 2 — Fact domains
    domains = _resolve_domains(only)
    typer.echo(f"[2/3] Generating {len(domains)} fact domain(s): {', '.join(domains)}")

    for domain_name in tqdm(domains, desc="Domains", unit="domain"):
        gen_cls = DOMAIN_MAP[domain_name]
        gen = gen_cls(seed=seed)
        t_domain = time.perf_counter()

        if profile_cfg.name == "loadtest" and hasattr(gen, "generate_chunked"):
            chunk_count = 0
            for chunk in gen.generate_chunked(cache, profile_cfg, crisis_days, profile_cfg.chunk_size):
                dispatcher.write_all(chunk, force_parquet_for_high_vol=True)
                # Populate order cache from sales chunks
                if "orders" in chunk:
                    cache.populate({"orders": chunk["orders"]})
                chunk_count += 1
            log.info("domain_complete_chunked", domain=domain_name, chunks=chunk_count, elapsed=round(time.perf_counter() - t_domain, 2))
        else:
            tables = gen.generate(cache, profile_cfg, crisis_days)
            # Populate FK caches from fact tables
            if "orders" in tables:
                cache.populate({"orders": tables["orders"]})
            if "campaigns" in tables:
                cache.populate({"campaigns": tables["campaigns"]})
            dispatcher.write_all(tables)
            log.info(
                "domain_complete",
                domain=domain_name,
                tables=list(tables.keys()),
                rows={k: len(v) for k, v in tables.items()},
                elapsed=round(time.perf_counter() - t_domain, 2),
            )

    # 6. Summary
    elapsed = round(time.perf_counter() - t_start, 2)
    typer.echo(f"[3/3] Done. Total elapsed: {elapsed}s")
    log.info("generation_complete", profile=profile, elapsed_s=elapsed, crisis_days=len(crisis_days))


@app.command()
def validate(
    output: Annotated[str, typer.Option("--output", "-o", help="Path to generated Parquet/CSV output")] = "./output",
    format: Annotated[str, typer.Option("--format", "-f", help="Output format to validate: parquet | csv")] = "parquet",
) -> None:
    """Run referential integrity checks on generated data."""
    import subprocess

    typer.echo(f"Running referential integrity checks on {output} ({format})...")
    env = {**os.environ, "RCD_OUTPUT_DIR": output, "RCD_OUTPUT_FORMAT": format}
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "rcd_data/tests/test_referential_integrity.py",
            "-v",
            "--tb=short",
        ],
        check=False,
        env=env,
    )
    if result.returncode == 0:
        typer.echo("All checks passed.")
    else:
        typer.echo("Some checks failed. See output above.", err=True)
    raise typer.Exit(result.returncode)


@app.command()
def info(
    config: Annotated[str, typer.Option("--config", "-c")] = DEFAULT_CONFIG,
) -> None:
    """Show profile sizes and output schema summary."""
    from .generators.base import load_config
    cfg = load_config(config)
    typer.echo("RCD Corp Data Generator\n")
    typer.echo("Profiles:")
    for name, p in cfg.get("profiles", {}).items():
        typer.echo(
            f"  {name:12s}  customers={p['n_customers']:>8,}  orders={p['n_orders']:>12,}  days={p['date_range_days']}"
        )
    typer.echo(f"\nDomains: {', '.join(DOMAIN_MAP.keys())}")
    typer.echo("Sinks:   csv | parquet | jsonl | xlsx | postgres | sqlserver | all")


@app.command()
def stream(
    profile: Annotated[str, typer.Option("--profile", "-p", help="Profile name for FK pool sizing")] = "demo",
    seed: Annotated[int, typer.Option("--seed", "-s", help="Base random seed")] = 42,
    sink: Annotated[str, typer.Option("--sink", help="Output sink: csv | parquet | jsonl | xlsx | postgres | sqlserver | all")] = "parquet",
    rows_per_tick: Annotated[int, typer.Option("--rows-per-tick", "-r", help="Rows per domain per tick")] = 25,
    interval: Annotated[int, typer.Option("--interval", "-i", help="Seconds between ticks; 0=fire once and exit")] = 300,
    config: Annotated[str, typer.Option("--config", "-c", help="Path to config.yaml")] = DEFAULT_CONFIG,
) -> None:
    """Stream synthetic rows to existing output every --interval seconds."""
    _seed_all(seed)
    profile_cfg, full_config = load_profile(config, profile)
    dispatcher = SinkDispatcher.from_flag(sink, profile_cfg, full_config)

    typer.echo("Loading master cache from existing output...")
    cache = _load_master_cache(full_config)
    typer.echo(
        f"Streaming {rows_per_tick} rows/domain every {interval}s across "
        f"{len(FACT_DOMAINS)} domains. Ctrl+C to stop."
    )

    tick = 0
    try:
        while True:
            t0 = time.perf_counter()
            now_end = datetime.now()
            now_start = now_end - timedelta(seconds=max(interval, 60))
            tick_rng = np.random.default_rng(seed + tick)

            all_tables: dict[str, pd.DataFrame] = {}
            for domain_name in FACT_DOMAINS:
                gen = DOMAIN_MAP[domain_name](seed=seed + tick)
                # Snapshot FK arrays that generators may overwrite during generate()
                saved_order_ids = cache.order_ids.copy()
                saved_campaign_ids = cache.campaign_ids.copy()
                tables = gen.generate_batch(cache, rows_per_tick, now_start, now_end, tick_rng)
                # Restore snapshot + extend with any new IDs generated this tick
                if "orders" in tables and not tables["orders"].empty:
                    new_ids = tables["orders"]["id"].to_numpy().astype("U36")
                    cache.order_ids = np.concatenate([saved_order_ids, new_ids])
                else:
                    cache.order_ids = saved_order_ids
                if "campaigns" in tables and not tables["campaigns"].empty:
                    new_cids = tables["campaigns"]["id"].to_numpy().astype("U36")
                    cache.campaign_ids = np.concatenate([saved_campaign_ids, new_cids])
                else:
                    cache.campaign_ids = saved_campaign_ids
                all_tables.update(tables)

            dispatcher.append_all(all_tables)
            elapsed = round(time.perf_counter() - t0, 2)
            log.info("tick_complete", tick=tick, rows_per_domain=rows_per_tick, elapsed_s=elapsed)
            typer.echo(f"  tick={tick}  elapsed={elapsed}s")
            tick += 1

            if interval == 0:
                break
            remaining = interval - (time.perf_counter() - t0)
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        typer.echo(f"\nStopped after {tick} tick(s).")


if __name__ == "__main__":
    app()
