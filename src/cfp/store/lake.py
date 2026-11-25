"""The data lake: content-addressed raw payloads and append-only normalized Parquet.

    <root>/raw/<aa>/<sha256>                         raw bytes, addressed by SHA-256
    <root>/normalized/<table>/season=<y>/*.parquet   (or <table>/all/ for tables without a season)

Rules the lake enforces on every append:
- ingest_time is stamped by the lake's clock, never taken from the caller, so a row cannot be backdated
  into a past live view;
- every row cites a raw payload that is present and whose bytes still match its digest;
- a key's correction_version starts at 0 and rises by one: no duplicates, gaps or out-of-order versions;
- a batch lands in full or not at all, under a per-table lock; files are never rewritten.
"""

from __future__ import annotations

import fcntl
import io
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path

import polars as pl

from cfp.common.hashing import sha256_hex
from cfp.common.timeutil import require_utc, utc_now
from cfp.store.asof import as_of
from cfp.store.schemas import SHA256_HEX, TABLES, TS, TableSpec
from cfp.store.types import AsOf, Mode
from cfp.store.views import OpenRankingView, refuse_unless_allowed


class MissingRaw(LookupError):
    """A row cites a raw payload that is absent or corrupt."""


class DuplicateRow(ValueError):
    """A (key, correction_version) pair already exists."""


class CorrectionOrder(ValueError):
    """A key's correction versions are not 0, 1, 2, ... in append order."""


class Lake:
    def __init__(self, root: Path | str, clock: Callable[[], datetime] = utc_now) -> None:
        self.root = Path(root)
        self._clock = clock

    # --- raw ---------------------------------------------------------------
    def _raw_path(self, digest: str) -> Path:
        if not re.fullmatch(SHA256_HEX.strip("^$"), digest):
            raise MissingRaw(f"not a SHA-256 hex digest: {digest!r}")
        return self.root / "raw" / digest[:2] / digest

    def put_raw(self, payload: bytes) -> str:
        """Store bytes under their SHA-256 and return the digest. Idempotent; repairs a corrupt copy."""
        digest = sha256_hex(payload)
        path = self._raw_path(digest)
        if not (path.is_file() and sha256_hex(path.read_bytes()) == digest):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)
        return digest

    def get_raw(self, digest: str) -> bytes:
        """Return the payload, verifying its bytes against the digest."""
        path = self._raw_path(digest)
        if not path.is_file():
            raise MissingRaw(digest)
        payload = path.read_bytes()
        if sha256_hex(payload) != digest:
            raise MissingRaw(f"raw payload {digest} is corrupt")
        return payload

    def has_raw(self, digest: str) -> bool:
        try:
            self.get_raw(digest)
        except MissingRaw:
            return False
        return True

    # --- normalized ----------------------------------------------------------
    @staticmethod
    def spec(table: str) -> TableSpec:
        return TABLES[table]

    def _table_dir(self, table: str) -> Path:
        return self.root / "normalized" / table

    @contextmanager
    def _locked(self, table: str) -> Iterator[None]:
        directory = self._table_dir(table)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def scan(self, table: str) -> pl.LazyFrame:
        spec = self.spec(table)
        files = sorted(self._table_dir(table).rglob("*.parquet"))
        if not files:
            return pl.LazyFrame(schema=spec.schema)
        return pl.scan_parquet(files, hive_partitioning=False).select(list(spec.schema))

    def _check_versions(self, spec: TableSpec, rows: pl.DataFrame) -> None:
        key = list(spec.key)
        batch = rows.group_by(key).agg(
            lo=pl.col("correction_version").min(),
            hi=pl.col("correction_version").max(),
            n=pl.len(),
            distinct=pl.col("correction_version").n_unique(),
        )
        stored = (
            self.scan(spec.name)
            .join(batch.select(key).lazy(), on=key, how="semi")
            .group_by(key)
            .agg(prev=pl.col("correction_version").max())
            .collect()
        )
        check = batch.join(stored, on=key, how="left").with_columns(pl.col("prev").fill_null(-1))
        repeated = check.filter((pl.col("distinct") != pl.col("n")) | (pl.col("lo") <= pl.col("prev")))
        if repeated.height:
            raise DuplicateRow(
                f"{spec.name}: (key, correction_version) stored or repeated: {repeated.select(key).row(0)}"
            )
        gaps = check.filter(
            (pl.col("lo") != pl.col("prev") + 1) | (pl.col("hi") - pl.col("lo") + 1 != pl.col("n"))
        )
        if gaps.height:
            row = gaps.row(0, named=True)
            raise CorrectionOrder(
                f"{spec.name}: key {tuple(row[k] for k in key)} must continue at version {row['prev'] + 1}"
            )

    def append(self, table: str, rows: pl.DataFrame) -> list[Path]:
        """Validate and append rows, stamping ingest_time from the lake's clock. Returns the files written."""
        spec = self.spec(table)
        now = require_utc(self._clock(), "clock")
        rows = spec.validate(rows.with_columns(pl.lit(now).cast(TS).alias("ingest_time")))
        if rows.height == 0:
            return []
        for digest in rows["raw_hash"].unique().to_list():
            self.get_raw(digest)
        identity = [*spec.key, "correction_version"]
        with self._locked(table):
            self._check_versions(spec, rows)
            parts = (
                rows.partition_by("season", as_dict=True) if spec.partition_by_season else {("all",): rows}
            )
            staged: list[tuple[Path, Path]] = []
            try:
                for part_key, part in sorted(parts.items(), key=lambda kv: str(kv[0])):
                    label = f"season={part_key[0]}" if spec.partition_by_season else "all"
                    buffer = io.BytesIO()
                    part.sort(identity).write_parquet(buffer, compression="zstd", statistics=True)
                    payload = buffer.getvalue()
                    final = self._table_dir(table) / label / f"part-{sha256_hex(payload)[:24]}.parquet"
                    if final.exists():
                        raise DuplicateRow(f"{table}: batch already stored at {final.name}")
                    final.parent.mkdir(parents=True, exist_ok=True)
                    tmp = final.with_name(f"{final.name}.{uuid.uuid4().hex}.tmp")
                    staged.append((tmp, final))
                    self._write_staged(tmp, payload)
            except BaseException:
                for tmp, _ in staged:
                    with suppress(FileNotFoundError):
                        tmp.unlink()
                raise
            for tmp, final in staged:  # every file is staged before any becomes visible
                tmp.replace(final)
            return [final for _, final in staged]

    @staticmethod
    def _write_staged(tmp: Path, payload: bytes) -> None:
        tmp.write_bytes(payload)

    # --- reads -----------------------------------------------------------------
    def as_of(self, table: str, t: datetime, mode: Mode, season: int | None = None) -> AsOf:
        spec = self.spec(table)
        where = pl.col("season") == season if season is not None and "season" in spec.columns else None
        return as_of(self.scan(table), spec, t, mode, where)

    def open_ranking_view(self, t: datetime, mode: Mode = "replay") -> OpenRankingView:
        """The Open Ranking's only access to the lake: games, teams and membership."""

        def read(name: str, season: int | None) -> AsOf:
            refuse_unless_allowed(name)
            return self.as_of(name, t, mode, season=season)

        return OpenRankingView(read, t, mode)
