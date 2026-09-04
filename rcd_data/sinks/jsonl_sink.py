"""JSON Lines output sink for RCD Corp data generator."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

log = structlog.get_logger()


class JSONLSink:
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
            log.warning("jsonl_skip_empty", table=table_name)
            return
        out_path = self.base_path / f"{table_name}.jsonl"
        mode = "a" if append and out_path.exists() else "w"
        with open(out_path, mode, encoding="utf-8") as f:
            f.write(df.to_json(orient="records", lines=True, date_format="iso"))
        log.info("jsonl_written", table=table_name, rows=len(df), path=str(out_path), append=append)
