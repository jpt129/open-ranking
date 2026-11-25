"""Table schemas with the six provenance fields and vintage (DS-01, DS-02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import polars as pl

TS: Final = pl.Datetime("us", "UTC")

VINTAGES: Final = ("live", "archived_authentic", "reconstructed", "unknown")
SHA256_HEX: Final = r"^[0-9a-f]{64}$"

# DS-01: source ID, event time, first-public time, ingest time, correction version, raw hash. DS-02: vintage.
PROVENANCE: Final[dict[str, pl.DataType]] = {
    "source_id": pl.String(),
    "event_time": TS,
    "first_public_time": TS,
    "ingest_time": TS,
    "correction_version": pl.Int32(),
    "raw_hash": pl.String(),
    "vintage": pl.String(),
}


class SchemaError(ValueError):
    """A frame does not satisfy its table's schema."""


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: tuple[str, ...]
    columns: dict[str, pl.DataType]
    nullable: frozenset[str] = frozenset()
    partition_by_season: bool = True
    schema: pl.Schema = field(init=False)

    def __post_init__(self) -> None:
        overlap = set(self.columns) & set(PROVENANCE)
        if overlap:
            raise ValueError(f"{self.name}: columns shadow provenance fields: {sorted(overlap)}")
        if not set(self.key) <= set(self.columns):
            raise ValueError(f"{self.name}: key columns missing from schema")
        if set(self.key) & self.nullable:
            raise ValueError(f"{self.name}: key columns cannot be nullable")
        if not self.nullable <= set(self.columns):
            raise ValueError(f"{self.name}: nullable names unknown columns")
        if self.partition_by_season and "season" not in self.columns:
            raise ValueError(f"{self.name}: partitioned tables need a season column")
        object.__setattr__(self, "schema", pl.Schema({**self.columns, **PROVENANCE}))

    def validate(self, df: pl.DataFrame) -> pl.DataFrame:
        """Return `df` in canonical column order, or raise SchemaError."""
        if set(df.columns) != set(self.schema):
            missing = sorted(set(self.schema) - set(df.columns))
            extra = sorted(set(df.columns) - set(self.schema))
            raise SchemaError(f"{self.name}: columns differ from schema; missing={missing} extra={extra}")
        df = df.select(list(self.schema))
        for column, dtype in self.schema.items():
            if df.schema[column] != dtype:
                raise SchemaError(f"{self.name}.{column}: expected {dtype}, got {df.schema[column]}")
        required = [c for c in self.schema if c not in self.nullable]
        nulls = df.select(pl.col(required).null_count()).row(0)
        bad = [c for c, n in zip(required, nulls, strict=True) if n]
        if bad:
            raise SchemaError(f"{self.name}: null values in required columns {bad}")
        unknown = set(df["vintage"].unique()) - set(VINTAGES)
        if unknown:
            raise SchemaError(f"{self.name}: vintage must be one of {VINTAGES}; got {sorted(unknown)}")
        if df.filter(~pl.col("raw_hash").str.contains(SHA256_HEX)).height:
            raise SchemaError(f"{self.name}: raw_hash must be a lowercase SHA-256 hex digest")
        if df.filter(pl.col("correction_version") < 0).height:
            raise SchemaError(f"{self.name}: correction_version must be >= 0")
        if df.filter(pl.col("ingest_time") < pl.col("first_public_time")).height:
            raise SchemaError(
                f"{self.name}: ingest_time precedes first_public_time (ingested before it is public)"
            )
        return df


def _spec(
    name: str,
    key: tuple[str, ...],
    columns: dict[str, pl.DataType],
    nullable: tuple[str, ...] = (),
    partition_by_season: bool = True,
) -> TableSpec:
    return TableSpec(name, key, columns, frozenset(nullable), partition_by_season)


S, I32, I64, F64, B = pl.String(), pl.Int32(), pl.Int64(), pl.Float64(), pl.Boolean()

TABLES: Final[dict[str, TableSpec]] = {
    spec.name: spec
    for spec in (
        _spec(
            "games",
            ("game_id",),
            {
                "game_id": S,
                "season": I32,
                "week": I32,
                "start_utc": TS,
                "home_id": S,
                "away_id": S,
                "home_pts": I32,
                "away_pts": I32,
                "neutral": B,
                "site": S,
                "season_type": S,
                "status": S,
                "title_game": B,
                "home_div": S,
                "away_div": S,
            },
            nullable=("home_pts", "away_pts", "site", "start_utc", "week"),
        ),
        _spec(
            "teams",
            ("team_id",),
            {
                "team_id": S,
                "name": S,
                "cfbd_id": I64,
                "espn_id": I64,
                "kalshi_code": S,
            },
            nullable=("cfbd_id", "espn_id", "kalshi_code"),
            partition_by_season=False,
        ),
        _spec(
            "team_aliases",
            ("source", "alias"),
            {
                "source": S,
                "alias": S,
                "team_id": S,
            },
            partition_by_season=False,
        ),
        _spec(
            "membership",
            ("team_id", "valid_from"),
            {
                "team_id": S,
                "valid_from": pl.Date(),
                "valid_to": pl.Date(),
                "conference_id": S,
                "division": S,
                "cfp_group": S,
            },
            nullable=("valid_to", "conference_id", "cfp_group"),
            partition_by_season=False,
        ),
        _spec(
            "committee_releases",
            ("release_id", "rank"),
            {
                "release_id": S,
                "rank": I32,
                "season": I32,
                "release_no": I32,
                "reveal_utc": TS,
                "team_id": S,
                "source_name": S,
                "archive_capture_utc": TS,
                "archive_raw_hash": S,
            },
            nullable=("archive_capture_utc", "archive_raw_hash"),
        ),
        _spec(
            "polls",
            ("poll", "season", "week", "team_id"),
            {
                "poll": S,
                "season": I32,
                "week": I32,
                "team_id": S,
                "rank": I32,
                "points": I32,
                "fpv": I32,
                "others_votes": B,
            },
            nullable=("rank", "points", "fpv"),
        ),
        _spec(
            "lines",
            ("provider", "game_id", "as_of_utc"),
            {
                "provider": S,
                "game_id": S,
                "as_of_utc": TS,
                "season": I32,
                "ml_home": F64,
                "ml_away": F64,
                "spread": F64,
                "total": F64,
            },
            nullable=("ml_home", "ml_away", "spread", "total"),
        ),
        _spec(
            "market_quotes",
            ("venue", "ticker", "ts_utc"),
            {
                "venue": S,
                "ticker": S,
                "ts_utc": TS,
                "season": I32,
                "bid": F64,
                "ask": F64,
                "bid_size": F64,
                "ask_size": F64,
                "last": F64,
            },
            nullable=("bid", "ask", "bid_size", "ask_size", "last"),
        ),
        _spec(
            "eligibility",
            ("season", "team_id"),
            {
                "season": I32,
                "team_id": S,
                "standard_met": B,
                "waiver": B,
            },
            nullable=("standard_met",),
        ),
        _spec(
            "champions",
            ("season", "conference_id"),
            {
                "season": I32,
                "conference_id": S,
                "team_id": S,
                "method": S,
            },
        ),
        _spec(
            "editions",
            ("edition_id",),
            {
                "edition_id": S,
                "season": I32,
                "product": S,
                "issue_utc": TS,
                "input_ids": pl.List(pl.String()),
                "seed": I64,
                "code_hash": S,
                "rule_version_id": S,
                "sha256": S,
            },
            nullable=("seed",),
        ),
        _spec(
            "chair_remarks",
            ("remark_id",),
            {
                "remark_id": S,
                "season": I32,
                "release_id": S,
                "published_utc": TS,
                "url": S,
                "text": S,
            },
            nullable=("release_id",),
        ),
    )
}
