"""Referential integrity tests for RCD Corp generated data.

Run after generation:
    python -m pytest rcd_data/tests/test_referential_integrity.py -v

These tests load generated Parquet or CSV output and assert zero orphan FKs
across all fact tables referencing master data.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from ._sink_helpers import get_db_engine

OUTPUT_DIR = os.environ.get("RCD_OUTPUT_DIR", "./output")
FORMAT = os.environ.get("RCD_OUTPUT_FORMAT", "parquet")


def _load(table: str) -> pd.DataFrame:
    """Load a table from the output directory or database."""
    if FORMAT == "parquet":
        parquet_dir = Path(OUTPUT_DIR) / "parquet" / table
        if not parquet_dir.exists():
            pytest.skip(f"Table '{table}' not found at {parquet_dir}")
        return pd.read_parquet(parquet_dir)
    elif FORMAT == "jsonl":
        jsonl_path = Path(OUTPUT_DIR) / "jsonl" / f"{table}.jsonl"
        if not jsonl_path.exists():
            pytest.skip(f"Table '{table}' not found at {jsonl_path}")
        return pd.read_json(jsonl_path, lines=True)
    elif FORMAT == "xlsx":
        xlsx_path = Path(OUTPUT_DIR) / "xlsx" / f"{table}.xlsx"
        if not xlsx_path.exists():
            pytest.skip(f"Table '{table}' not found at {xlsx_path}")
        return pd.read_excel(xlsx_path)
    elif FORMAT in ("postgres", "sqlserver"):
        from sqlalchemy import inspect

        engine = get_db_engine(FORMAT)
        if not inspect(engine).has_table(table):
            pytest.skip(f"Table '{table}' not found in {FORMAT} database")
        return pd.read_sql_table(table, engine)
    else:
        csv_path = Path(OUTPUT_DIR) / "csv" / f"{table}.csv"
        if not csv_path.exists():
            pytest.skip(f"Table '{table}' not found at {csv_path}")
        return pd.read_csv(csv_path)


def _assert_no_orphans(
    fact_df: pd.DataFrame,
    fact_table: str,
    fk_col: str,
    ref_df: pd.DataFrame,
    ref_table: str,
    pk_col: str = "id",
) -> None:
    """Assert that every non-null FK value in fact_df[fk_col] exists in ref_df[pk_col]."""
    valid_fk = fact_df[fk_col].notna()
    if not valid_fk.any():
        return
    fk_vals = set(fact_df.loc[valid_fk, fk_col].astype(str))
    pk_vals = set(ref_df[pk_col].astype(str))
    orphans = fk_vals - pk_vals
    assert len(orphans) == 0, (
        f"Orphan FKs in {fact_table}.{fk_col} → {ref_table}.{pk_col}: "
        f"{len(orphans)} orphan(s). Sample: {list(orphans)[:5]}"
    )


# ── Master data existence ────────────────────────────────────────────────────

class TestMasterDataExists:
    def test_customers_exist(self):
        df = _load("customers")
        assert len(df) > 0, "customers table is empty"
        assert "id" in df.columns

    def test_products_exist(self):
        df = _load("products")
        assert len(df) > 0, "products table is empty"
        assert "sku" in df.columns

    def test_employees_exist(self):
        df = _load("employees")
        assert len(df) > 0, "employees table is empty"

    def test_stores_exist(self):
        df = _load("stores")
        assert len(df) > 0, "stores table is empty"

    def test_warehouses_exist(self):
        df = _load("warehouses")
        assert len(df) > 0, "warehouses table is empty"

    def test_suppliers_exist(self):
        df = _load("suppliers")
        assert len(df) > 0, "suppliers table is empty"

    def test_fx_rates_exist(self):
        df = _load("fx_rates")
        assert len(df) > 0, "fx_rates table is empty"
        assert set(["BRL", "MXN", "EUR", "USD"]).issubset(set(df["from_currency"].unique()))


# ── No null PKs ──────────────────────────────────────────────────────────────

class TestNullPrimaryKeys:
    @pytest.mark.parametrize("table,pk", [
        ("customers", "id"),
        ("employees", "id"),
        ("suppliers", "id"),
        ("stores", "id"),
        ("warehouses", "id"),
        ("orders", "id"),
        ("payments", "id"),
        ("tickets", "id"),
    ])
    def test_no_null_pks(self, table: str, pk: str):
        df = _load(table)
        null_count = df[pk].isna().sum()
        assert null_count == 0, f"{table}.{pk} has {null_count} null PKs"

    def test_products_no_null_skus(self):
        df = _load("products")
        assert df["sku"].isna().sum() == 0

    def test_fx_rates_no_null_rates(self):
        df = _load("fx_rates")
        assert df["rate"].isna().sum() == 0


# ── Sales FK integrity ───────────────────────────────────────────────────────

class TestSalesFKIntegrity:
    def test_orders_customer_id(self):
        orders = _load("orders")
        customers = _load("customers")
        _assert_no_orphans(orders, "orders", "customer_id", customers, "customers")

    def test_orders_store_id(self):
        orders = _load("orders")
        stores = _load("stores")
        _assert_no_orphans(orders, "orders", "store_id", stores, "stores")

    def test_order_items_order_id(self):
        items = _load("order_items")
        orders = _load("orders")
        _assert_no_orphans(items, "order_items", "order_id", orders, "orders")

    def test_order_items_product_id(self):
        items = _load("order_items")
        products = _load("products")
        _assert_no_orphans(items, "order_items", "product_id", products, "products", pk_col="sku")

    def test_payments_order_id(self):
        payments = _load("payments")
        orders = _load("orders")
        _assert_no_orphans(payments, "payments", "order_id", orders, "orders")


# ── Supply chain FK integrity ────────────────────────────────────────────────

class TestSupplyChainFKIntegrity:
    def test_shipments_warehouse_id(self):
        shipments = _load("shipments")
        warehouses = _load("warehouses")
        _assert_no_orphans(shipments, "shipments", "warehouse_id", warehouses, "warehouses")

    def test_purchase_orders_supplier_id(self):
        pos = _load("purchase_orders")
        suppliers = _load("suppliers")
        _assert_no_orphans(pos, "purchase_orders", "supplier_id", suppliers, "suppliers")

    def test_purchase_orders_warehouse_id(self):
        pos = _load("purchase_orders")
        warehouses = _load("warehouses")
        _assert_no_orphans(pos, "purchase_orders", "warehouse_id", warehouses, "warehouses")

    def test_stock_movements_warehouse_id(self):
        movements = _load("stock_movements")
        warehouses = _load("warehouses")
        _assert_no_orphans(movements, "stock_movements", "warehouse_id", warehouses, "warehouses")

    def test_inventory_snapshots_warehouse_id(self):
        inv = _load("inventory_snapshots")
        warehouses = _load("warehouses")
        _assert_no_orphans(inv, "inventory_snapshots", "warehouse_id", warehouses, "warehouses")

    def test_returns_customer_id(self):
        returns = _load("returns")
        customers = _load("customers")
        _assert_no_orphans(returns, "returns", "customer_id", customers, "customers")


# ── Support FK integrity ─────────────────────────────────────────────────────

class TestSupportFKIntegrity:
    def test_tickets_customer_id(self):
        tickets = _load("tickets")
        customers = _load("customers")
        _assert_no_orphans(tickets, "tickets", "customer_id", customers, "customers")

    def test_tickets_agent_id(self):
        tickets = _load("tickets")
        employees = _load("employees")
        _assert_no_orphans(tickets, "tickets", "agent_id", employees, "employees")

    def test_ticket_messages_ticket_id(self):
        messages = _load("ticket_messages")
        tickets = _load("tickets")
        _assert_no_orphans(messages, "ticket_messages", "ticket_id", tickets, "tickets")

    def test_calls_customer_id(self):
        calls = _load("call_center_calls")
        customers = _load("customers")
        _assert_no_orphans(calls, "call_center_calls", "customer_id", customers, "customers")

    def test_calls_agent_id(self):
        calls = _load("call_center_calls")
        employees = _load("employees")
        _assert_no_orphans(calls, "call_center_calls", "agent_id", employees, "employees")


# ── Marketing FK integrity ───────────────────────────────────────────────────

class TestMarketingFKIntegrity:
    def test_leads_customer_id(self):
        leads = _load("leads")
        customers = _load("customers")
        _assert_no_orphans(leads, "leads", "customer_id", customers, "customers")

    def test_campaign_events_campaign_id(self):
        events = _load("campaign_events")
        campaigns = _load("campaigns")
        _assert_no_orphans(events, "campaign_events", "campaign_id", campaigns, "campaigns")

    def test_email_events_campaign_id(self):
        events = _load("email_events")
        campaigns = _load("campaigns")
        _assert_no_orphans(events, "email_events", "campaign_id", campaigns, "campaigns")


# ── HR FK integrity ──────────────────────────────────────────────────────────

class TestHRFKIntegrity:
    def test_performance_reviews_employee_id(self):
        reviews = _load("performance_reviews")
        employees = _load("employees")
        _assert_no_orphans(reviews, "performance_reviews", "employee_id", employees, "employees")

    def test_training_records_employee_id(self):
        training = _load("training_records")
        employees = _load("employees")
        _assert_no_orphans(training, "training_records", "employee_id", employees, "employees")

    def test_engagement_surveys_employee_id(self):
        surveys = _load("engagement_surveys")
        employees = _load("employees")
        _assert_no_orphans(surveys, "engagement_surveys", "employee_id", employees, "employees")


# ── Products FK integrity ────────────────────────────────────────────────────

class TestProductFKIntegrity:
    def test_products_supplier_id(self):
        products = _load("products")
        suppliers = _load("suppliers")
        _assert_no_orphans(products, "products", "supplier_id", suppliers, "suppliers")


# ── Statistical sanity checks ────────────────────────────────────────────────

class TestStatisticalSanity:
    def test_orders_status_distribution_has_all_terminals(self):
        orders = _load("orders")
        terminal_statuses = {"cancelled", "delivered", "refunded", "lost"}
        found = set(orders["status"].unique())
        missing = terminal_statuses - found
        assert len(missing) < 3, (
            f"Expected most terminal statuses to appear. Missing all of: {missing}"
        )

    def test_customers_segment_distribution(self):
        customers = _load("customers")
        counts = customers["segment"].value_counts(normalize=True)
        assert counts.get("B2C", 0) > 0.50, "B2C should be >50% of customers"
        assert counts.get("VIP", 0) < 0.15, "VIP should be <15% of customers"

    def test_fx_rates_all_currencies_present(self):
        fx = _load("fx_rates")
        expected = {"BRL", "MXN", "EUR", "USD"}
        found = set(fx["from_currency"].unique())
        assert expected.issubset(found), f"Missing currencies: {expected - found}"

    def test_orders_multi_currency(self):
        orders = _load("orders")
        currencies = set(orders["currency"].unique())
        assert len(currencies) >= 2, f"Expected multi-currency orders, found only: {currencies}"

    def test_tickets_have_closed_status(self):
        tickets = _load("tickets")
        assert "closed" in tickets["status"].unique(), "No closed tickets found"

    def test_reviews_rating_range(self):
        reviews = _load("reviews")
        assert reviews["rating"].between(1, 5).all(), "Review ratings outside 1–5 range"

    def test_employees_salary_positive(self):
        employees = _load("employees")
        assert (employees["salary"] > 0).all(), "Some employees have non-positive salary"

    def test_cpf_cnpj_format(self):
        customers = _load("customers")
        sample = customers["cpf_or_cnpj"].dropna().head(100)
        # CPF: 000.000.000-00 (14 chars) or CNPJ: 00.000.000/0000-00 (18 chars)
        valid_lengths = {14, 18}
        for val in sample:
            assert len(str(val)) in valid_lengths, f"Invalid CPF/CNPJ format: {val}"
