"""Output-completeness tests for RCD Corp generated data.

Unlike test_referential_integrity.py (which skips missing tables), these
tests FAIL when an expected table's output file is missing or empty — the
goal is to catch a generator silently dropping a table, or a sink failing
to write one, before it ships.

Run after generation:
    RCD_OUTPUT_DIR=./output RCD_SINK=parquet \
        python -m pytest rcd_data/tests/test_output_completeness.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

OUTPUT_DIR = Path(os.environ.get("RCD_OUTPUT_DIR", "./output"))
SINK = os.environ.get("RCD_SINK", "parquet")

# Tables produced by `rcd-data generate` for every profile except `loadtest`.
# machine_telemetry / app_logs / api_requests are only emitted via
# generate_chunked(), which main.py invokes solely when profile == "loadtest"
# — they're intentionally excluded from this default table list.
EXPECTED_TABLES = sorted([
    # master data
    "customers", "products", "employees", "suppliers", "stores", "warehouses", "fx_rates",
    # sales
    "orders", "order_items", "payments", "web_sessions", "shopping_cart_events",
    # finance
    "invoices", "transactions", "expenses", "budgets", "rcd_card_transactions",
    # marketing
    "campaigns", "campaign_events", "email_events", "leads", "ab_test_exposures",
    # social media
    "social_accounts", "social_posts", "social_metrics", "social_comments", "social_mentions",
    "social_dms", "influencer_partnerships", "influencer_posts", "community_forum_posts",
    "reviews", "social_ad_spend",
    # supply chain
    "shipments", "inventory_snapshots", "purchase_orders", "stock_movements", "returns",
    # manufacturing
    "production_runs", "quality_checks", "maintenance_events",
    # hr
    "attendance", "performance_reviews", "training_records", "recruitment_pipeline",
    "engagement_surveys",
    # support
    "tickets", "ticket_messages", "call_center_calls",
    # observability
    "errors", "deployments", "security_events",
])

LOADTEST_ONLY_TABLES = {"machine_telemetry", "app_logs", "api_requests"}

_SINK_DIRS = {"csv": "csv", "parquet": "parquet", "jsonl": "jsonl", "xlsx": "xlsx"}


def _table_path(table: str) -> Path:
    if SINK not in _SINK_DIRS:
        pytest.skip(f"No file-based completeness check for sink '{SINK}'")
    sink_dir = OUTPUT_DIR / _SINK_DIRS[SINK]
    if SINK == "parquet":
        return sink_dir / table / "data.parquet"
    return sink_dir / f"{table}.{SINK}"


def _row_count(path: Path) -> int:
    if SINK == "parquet":
        return len(pd.read_parquet(path))
    if SINK == "csv":
        return len(pd.read_csv(path))
    if SINK == "jsonl":
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    if SINK == "xlsx":
        return len(pd.read_excel(path))
    raise ValueError(f"Unsupported RCD_SINK '{SINK}'")


class TestAllDatasetsGenerated:
    @pytest.mark.parametrize("table", EXPECTED_TABLES)
    def test_table_file_exists_and_is_non_empty(self, table: str):
        path = _table_path(table)
        assert path.exists(), f"Missing output for '{table}' at {path} (sink={SINK})"
        rows = _row_count(path)
        assert rows > 0, f"'{table}' output at {path} has zero rows (sink={SINK})"

    def test_output_dir_has_no_untracked_tables(self):
        """Catches the inverse failure: a stray/renamed table this list wasn't updated for."""
        if SINK not in _SINK_DIRS:
            pytest.skip(f"No file-based completeness check for sink '{SINK}'")
        sink_dir = OUTPUT_DIR / _SINK_DIRS[SINK]
        if not sink_dir.exists():
            pytest.skip(f"Sink directory not found: {sink_dir}")

        if SINK == "parquet":
            found = {p.name for p in sink_dir.iterdir() if p.is_dir()}
        else:
            found = {p.stem for p in sink_dir.glob(f"*.{SINK}")}

        found -= LOADTEST_ONLY_TABLES
        extra = found - set(EXPECTED_TABLES)
        assert not extra, (
            f"Unexpected tables in {SINK} output not tracked in EXPECTED_TABLES: {sorted(extra)}. "
            "Update EXPECTED_TABLES in this test if this is an intentional new table."
        )
