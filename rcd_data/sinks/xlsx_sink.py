"""XLSX output sink for RCD Corp data generator.

Best suited to the `demo` profile — Excel caps sheets at 1,048,576 rows
(including the header), so larger profiles get silently truncated with a
warning rather than failing the run.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

log = structlog.get_logger()

EXCEL_MAX_DATA_ROWS = 1_048_575


class XLSXSink:
    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        table_name: str,
        df: pd.DataFrame,
        partition_col: str | None = None,
        append: bool = False,
    ) -> None:
        if df is None or df.empty:
            log.warning("xlsx_skip_empty", table=table_name)
            return
        out_path = self.base_path / f"{table_name}.xlsx"

        if append and out_path.exists():
            existing = pd.read_excel(out_path)
            df = pd.concat([existing, df], ignore_index=True)

        if len(df) > EXCEL_MAX_DATA_ROWS:
            log.warning(
                "xlsx_row_limit_exceeded",
                table=table_name,
                rows=len(df),
                truncated_to=EXCEL_MAX_DATA_ROWS,
            )
            df = df.iloc[:EXCEL_MAX_DATA_ROWS]

        df.to_excel(out_path, index=False, sheet_name=table_name[:31])
        log.info("xlsx_written", table=table_name, rows=len(df), path=str(out_path), append=append)
