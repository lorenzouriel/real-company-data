"""PostgreSQL output sink for RCD Corp data generator."""
from __future__ import annotations

import os

import pandas as pd
import structlog
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

log = structlog.get_logger()

DEFAULT_URL = "postgresql+psycopg2://rcd:rcd@localhost:5432/rcd_corp"


class PostgresSink:
    def __init__(self, connection_url: str | None = None) -> None:
        url = connection_url or os.environ.get("RCD_POSTGRES_URL", DEFAULT_URL)
        self.engine: Engine = create_engine(url, pool_pre_ping=True)

    def write(
        self,
        table_name: str,
        df: pd.DataFrame,
        partition_col: str | None = None,
        append: bool = False,
    ) -> None:
        if df is None or df.empty:
            log.warning("postgres_skip_empty", table=table_name)
            return
        df.to_sql(
            name=table_name,
            con=self.engine,
            if_exists="append" if append else "replace",
            index=False,
            chunksize=10_000,
            method="multi",
        )
        log.info("postgres_written", table=table_name, rows=len(df), append=append)
