"""Base generator, MasterCache, ProfileConfig, and SinkDispatcher for RCD Corp."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterator

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel

from ..sinks.csv_sink import CSVSink
from ..sinks.jsonl_sink import JSONLSink
from ..sinks.parquet_sink import ParquetSink
from ..sinks.postgres_sink import PostgresSink
from ..sinks.sqlserver_sink import SQLServerSink
from ..sinks.xlsx_sink import XLSXSink

HIGH_VOLUME_TABLES = frozenset({"machine_telemetry", "api_requests", "app_logs"})
PARTITION_COL = "date"


class ProfileConfig(BaseModel):
    name: str
    n_customers: int
    n_products: int
    n_employees: int
    n_orders: int
    n_stores: int = 180
    n_warehouses: int = 10
    n_suppliers: int = 50
    date_range_days: int
    crisis_freq_per_month: int
    chunk_size: int
    start_date: str

    @property
    def start(self) -> date:
        return date.fromisoformat(self.start_date)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.date_range_days - 1)


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_profile(config_path: str, profile_name: str) -> tuple[ProfileConfig, dict]:
    cfg = load_config(config_path)
    profiles = cfg.get("profiles", {})
    if profile_name not in profiles:
        raise ValueError(
            f"Unknown profile '{profile_name}'. Available: {list(profiles.keys())}"
        )
    data = dict(profiles[profile_name])
    data["name"] = profile_name
    return ProfileConfig(**data), cfg


@dataclass
class MasterCache:
    """In-memory cache of master data PK arrays for FK sampling."""

    customer_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    customer_countries: np.ndarray = field(default_factory=lambda: np.array([], dtype="U2"))
    customer_segments: np.ndarray = field(default_factory=lambda: np.array([], dtype="U10"))
    product_skus: np.ndarray = field(default_factory=lambda: np.array([], dtype="U20"))
    product_prices: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    product_categories: np.ndarray = field(default_factory=lambda: np.array([], dtype="U50"))
    product_currencies: np.ndarray = field(default_factory=lambda: np.array([], dtype="U3"))
    employee_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    employee_departments: np.ndarray = field(default_factory=lambda: np.array([], dtype="U50"))
    supplier_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    store_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    store_countries: np.ndarray = field(default_factory=lambda: np.array([], dtype="U2"))
    warehouse_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    campaign_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    order_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype="U36"))
    fx_rates: pd.DataFrame = field(default_factory=pd.DataFrame)

    def _require(self, name: str, arr: np.ndarray) -> None:
        if len(arr) == 0:
            raise RuntimeError(
                f"MasterCache.{name} is empty — run master_data generator first"
            )

    def sample_customer_ids(self, n: int, rng: np.random.Generator) -> np.ndarray:
        self._require("customer_ids", self.customer_ids)
        return rng.choice(self.customer_ids, size=n, replace=True)

    def sample_product_skus(self, n: int, rng: np.random.Generator) -> np.ndarray:
        self._require("product_skus", self.product_skus)
        return rng.choice(self.product_skus, size=n, replace=True)

    def sample_employee_ids(self, n: int, rng: np.random.Generator) -> np.ndarray:
        self._require("employee_ids", self.employee_ids)
        return rng.choice(self.employee_ids, size=n, replace=True)

    def sample_supplier_ids(self, n: int, rng: np.random.Generator) -> np.ndarray:
        self._require("supplier_ids", self.supplier_ids)
        return rng.choice(self.supplier_ids, size=n, replace=True)

    def sample_store_ids(self, n: int, rng: np.random.Generator) -> np.ndarray:
        self._require("store_ids", self.store_ids)
        return rng.choice(self.store_ids, size=n, replace=True)

    def sample_warehouse_ids(self, n: int, rng: np.random.Generator) -> np.ndarray:
        self._require("warehouse_ids", self.warehouse_ids)
        return rng.choice(self.warehouse_ids, size=n, replace=True)

    def sample_order_ids(self, n: int, rng: np.random.Generator) -> np.ndarray:
        if len(self.order_ids) == 0:
            raise RuntimeError("order_ids cache empty — run sales generator first")
        return rng.choice(self.order_ids, size=min(n, len(self.order_ids)), replace=True)

    def populate(self, tables: dict[str, pd.DataFrame]) -> None:
        if "customers" in tables:
            df = tables["customers"]
            self.customer_ids = df["id"].to_numpy().astype("U36")
            self.customer_countries = df["country"].to_numpy().astype("U2")
            self.customer_segments = df["segment"].to_numpy().astype("U10")
        if "products" in tables:
            df = tables["products"]
            self.product_skus = df["sku"].to_numpy().astype("U20")
            self.product_prices = df["price"].to_numpy().astype(float)
            self.product_categories = df["category"].to_numpy().astype("U50")
            self.product_currencies = df["currency"].to_numpy().astype("U3")
        if "employees" in tables:
            df = tables["employees"]
            self.employee_ids = df["id"].to_numpy().astype("U36")
            self.employee_departments = df["department"].to_numpy().astype("U50")
        if "suppliers" in tables:
            df = tables["suppliers"]
            self.supplier_ids = df["id"].to_numpy().astype("U36")
        if "stores" in tables:
            df = tables["stores"]
            self.store_ids = df["id"].to_numpy().astype("U36")
            self.store_countries = df["country"].to_numpy().astype("U2")
        if "warehouses" in tables:
            df = tables["warehouses"]
            self.warehouse_ids = df["id"].to_numpy().astype("U36")
        if "campaigns" in tables:
            df = tables["campaigns"]
            self.campaign_ids = df["id"].to_numpy().astype("U36")
        if "fx_rates" in tables:
            self.fx_rates = tables["fx_rates"]
        if "orders" in tables:
            df = tables["orders"]
            self.order_ids = df["id"].to_numpy().astype("U36")


class BaseGenerator(ABC):
    """Abstract base for all RCD Corp data generators."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    @abstractmethod
    def generate(
        self,
        cache: MasterCache,
        profile: ProfileConfig,
        crisis_days: list[date],
    ) -> dict[str, pd.DataFrame]:
        """Return {table_name: DataFrame}. Called for standard-volume tables."""
        ...

    def generate_chunked(
        self,
        cache: MasterCache,
        profile: ProfileConfig,
        crisis_days: list[date],
        chunk_size: int,
    ) -> Iterator[dict[str, pd.DataFrame]]:
        """Default: yield generate() result as a single chunk.

        Override in generators for high-volume tables to keep memory bounded.
        """
        yield self.generate(cache, profile, crisis_days)

    def generate_batch(
        self,
        cache: MasterCache,
        n_rows: int,
        start: datetime,
        end: datetime,
        rng: np.random.Generator,
    ) -> dict[str, pd.DataFrame]:
        """Generate ~n_rows rows with timestamps anchored to [start, end].

        Default delegates to generate() via a narrow ProfileConfig.
        Override in individual generators for exact row counts or precise
        timestamp anchoring.

        Uses a 60-day window ending at end.date() so that generators which
        subtract a 30-day buffer from profile.end don't produce invalid ranges.
        """
        window_days = 60
        window_start = end.date() - timedelta(days=window_days - 1)
        narrow = ProfileConfig(
            name="stream",
            n_customers=max(1, len(cache.customer_ids)),
            n_products=max(1, len(cache.product_skus)),
            n_employees=max(1, len(cache.employee_ids)),
            n_orders=n_rows,
            n_stores=max(1, len(cache.store_ids)),
            n_warehouses=max(1, len(cache.warehouse_ids)),
            n_suppliers=max(1, len(cache.supplier_ids)),
            date_range_days=window_days,
            crisis_freq_per_month=0,
            chunk_size=n_rows,
            start_date=window_start.isoformat(),
        )
        return self.generate(cache, narrow, crisis_days=[])


class SinkDispatcher:
    """Routes DataFrames to one or more active sinks."""

    def __init__(
        self,
        sinks: list[tuple[str, object]],
        profile_name: str = "demo",
    ) -> None:
        self._sinks = sinks
        self._profile = profile_name

    @classmethod
    def from_flag(cls, flag: str, cfg: ProfileConfig, full_config: dict) -> "SinkDispatcher":
        output = full_config.get("output", {})
        csv_path = output.get("csv_path", "./output/csv")
        parquet_path = output.get("parquet_path", "./output/parquet")
        jsonl_path = output.get("jsonl_path", "./output/jsonl")
        xlsx_path = output.get("xlsx_path", "./output/xlsx")
        postgres_url = output.get("postgres_url") or os.environ.get("RCD_POSTGRES_URL")
        sqlserver_url = output.get("sqlserver_url") or os.environ.get("RCD_SQLSERVER_URL")

        sinks: list[tuple[str, object]] = []

        if flag in ("csv", "all"):
            sinks.append(("csv", CSVSink(csv_path)))
        if flag in ("parquet", "all"):
            sinks.append(("parquet", ParquetSink(parquet_path)))
        if flag in ("jsonl", "all"):
            sinks.append(("jsonl", JSONLSink(jsonl_path)))
        if flag in ("xlsx", "all"):
            sinks.append(("xlsx", XLSXSink(xlsx_path)))
        if flag in ("postgres", "all"):
            sinks.append(("postgres", PostgresSink(postgres_url)))
        if flag in ("sqlserver", "all"):
            sinks.append(("sqlserver", SQLServerSink(sqlserver_url)))

        if not sinks:
            raise ValueError(
                f"Unknown --sink value '{flag}'. Use: csv | parquet | jsonl | xlsx | postgres | sqlserver | all"
            )

        return cls(sinks, cfg.name)

    def write_all(
        self,
        tables: dict[str, pd.DataFrame],
        force_parquet_for_high_vol: bool = False,
    ) -> None:
        for table_name, df in tables.items():
            if df is None or df.empty:
                continue
            is_high_vol = table_name in HIGH_VOLUME_TABLES
            part_col: str | None = PARTITION_COL if is_high_vol and "date" in df.columns else None

            for sink_type, sink in self._sinks:
                if is_high_vol and self._profile == "loadtest" and sink_type != "parquet":
                    continue
                sink.write(table_name, df, part_col)  # type: ignore[union-attr]

    def append_all(self, tables: dict[str, pd.DataFrame]) -> None:
        """Write tables in append mode across all active sinks."""
        for table_name, df in tables.items():
            if df is None or df.empty:
                continue
            is_high_vol = table_name in HIGH_VOLUME_TABLES
            part_col: str | None = PARTITION_COL if is_high_vol and "date" in df.columns else None
            for _sink_type, sink in self._sinks:
                sink.write(table_name, df, part_col, append=True)  # type: ignore[union-attr]
