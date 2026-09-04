"""Shared DB-sink connection helpers for the output validation tests.

Not a test module itself (leading underscore keeps pytest from collecting it).
"""
from __future__ import annotations

import os

DB_DEFAULT_URLS = {
    "postgres": "postgresql+psycopg2://rcd:rcd@localhost:5432/rcd_corp",
    "sqlserver": (
        "mssql+pyodbc://rcd:rcd@localhost:1433/rcd_corp"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    ),
}

DB_ENV_VARS = {
    "postgres": "RCD_POSTGRES_URL",
    "sqlserver": "RCD_SQLSERVER_URL",
}


def get_db_engine(sink: str):
    """Build a SQLAlchemy engine for 'postgres' or 'sqlserver' from env vars."""
    from sqlalchemy import create_engine

    url = os.environ.get(DB_ENV_VARS[sink], DB_DEFAULT_URLS[sink])
    return create_engine(url, pool_pre_ping=True)
