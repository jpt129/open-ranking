"""The data lake: content-addressed raw payloads and append-only normalized Parquet.

    <root>/raw/<aa>/<sha256>                         raw bytes, addressed by SHA-256
    <root>/normalized/<table>/season=<y>/*.parquet   (or <table>/all/ for tables without a season)

Normalized files are never rewritten. A correction is a new row with a higher correction_version.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import polars as pl

from cfp.common.hashing import sha256_hex
from cfp.store.asof import AsOf, Mode, as_of
from cfp.store.schemas import TABLES, TableSpec


class MissingRaw(LookupError):
    """A row cites a raw_hash that is not in the raw store."""


class DuplicateRow(ValueError):
    """A (key, correction_version) pair already exists."""


class Lake:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # --- raw ---------------------------------------------------------------
    def _raw_path(self, digest: str) -> Path:
        return self.root / "raw" / digest[:2] / digest

    def put_raw(self, payload: bytes) -> str:
        """Store bytes under their SHA-256 and return the digest. Idempotent."""
        digest = sha256_hex(payload)
        path = self._raw_path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)
        return digest

    def has_raw(self, digest: str) -> bool:
        return self._raw_path(digest).is_file()

    def get_raw(self, digest: str) -> bytes:
        path = self._raw_path(digest)
        if not path.is_file():
            raise MissingRaw(digest)
        payload = path.read_bytes()
        if sha256_hex(payload) != digest:
            raise MissingRaw(f"raw payload {digest} is corrupt")
        return payload

    # --- normalized ----------------------------------------------------------
    @staticmethod
    def spec(table: str) -> TableSpec:
        return TABLES[table]

    def _table_dir(self, table: str) -> Path:
        return self.root / "normalized" / table

    def scan(self, table: str) -> pl.LazyFrame:
        spec = self.spec(table)
        files = sorted(self._table_dir(table).rglob("*.parquet"))
        if not files:
            return pl.LazyFrame(schema=spec.schema)
        return pl.scan_parquet(files, hive_partitioning=False).select(list(spec.schema))

    def append(self, table: str, rows: pl.DataFrame) -> list[Path]:
        """Validate and append rows. Returns the files written."""
        spec = self.spec(table)
        rows = spec.validate(rows)
        if rows.height == 0:
            return []
        missing = [h for h in rows["raw_hash"].unique().to_list() if not self.has_raw(h)]
        if missing:
            raise MissingRaw(f"{table}: raw payloads not in the lake: {sorted(missing)[:3]}")
        identity = [*spec.key, "correction_version"]
        if rows.select(identity).is_duplicated().any():
            raise DuplicateRow(f"{table}: duplicate (key, correction_version) inside the batch")
        existing = self.scan(table).select(identity).collect()
        clash = rows.select(identity).join(existing, on=identity, how="inner", nulls_equal=True)
        if clash.height:
            raise DuplicateRow(f"{table}: (key, correction_version) already stored: {clash.row(0)}")

        written: list[Path] = []
        parts = rows.partition_by("season", as_dict=True) if spec.partition_by_season else {("all",): rows}
        for part_key, part in sorted(parts.items(), key=lambda kv: str(kv[0])):
            label = f"season={part_key[0]}" if spec.partition_by_season else "all"
            buffer = io.BytesIO()
            part.sort(identity).write_parquet(buffer, compression="zstd", statistics=True)
            payload = buffer.getvalue()
            path = self._table_dir(table) / label / f"part-{sha256_hex(payload)[:24]}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise DuplicateRow(f"{table}: batch already stored at {path.name}")
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)
            written.append(path)
        return written

    def as_of(self, table: str, t: datetime, mode: Mode) -> AsOf:
        return as_of(self.scan(table), self.spec(table), t, mode)
