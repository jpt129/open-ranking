"""The calibrated disclosure column for the weekly rank forecast (SC-05; John's ruling of 25 Nov 2026).

The raw baseline is published as the spec defines it. Beside it, labelled, goes a calibrated value for
P(top 25), P(rank <= 4) and P(rank <= 12): one monotone (isotonic) map per cutoff from the published
probability to the frequency observed on past weekly releases. It is a disclosure, not a promoted model, and
both columns are scored.

A map is published only if it is verified leave-one-season-out: each season is mapped by a fit that excludes
it (the temperature too), and the held-out log loss must fall without the Brier score rising.
"""

from __future__ import annotations

import bisect
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from cfp.common.hashing import sha256_hex
from cfp.forecast.noise_params import Example
from cfp.forecast.rank_noise import fit_temperature, published_probability, rank_frequencies, sample_orders

QUANTITIES: Final = ("top25", "rank4", "rank12")
CUT: Final = {"top25": 25, "rank4": 4, "rank12": 12}
ISSUES: Final = ("sun0200", "tminus60")
KIND: Final = "weekly"
PATHS: Final = 10_000
RANKED: Final = 25
EDGES: Final = (0.0, 0.003, 0.01, 0.05, 0.2, 0.4, 0.6, 0.8, 0.95, 0.99, 0.997, 1.0)
LABEL: Final = "Calibrated: a disclosure column, not a promoted model. Both columns are scored."
CRITERION: Final = (
    "leave-one-season-out, temperature and map both fitted without the season: "
    "log loss lower than the raw column's and Brier score no higher"
)


class CalibrationError(RuntimeError):
    """Calibration maps cannot be fitted, written or read."""


@dataclass(frozen=True)
class Map:
    """A non-decreasing step map. Block k covers published values lo[k]..hi[k] and gives value[k]."""

    lo: tuple[float, ...]
    hi: tuple[float, ...]
    value: tuple[float, ...]
    n: int


@dataclass(frozen=True)
class Row:
    season: int
    issue: str
    quantity: str
    p: float  # the published probability
    y: int  # 1 if it happened


def fit_map(p: Sequence[float], y: Sequence[int]) -> Map:
    """Isotonic regression of outcomes on published probabilities (pool adjacent violators).

    The end blocks are kept off 0 and 1 by half an event (see below).
    """
    if not p or len(p) != len(y):
        raise CalibrationError("a map needs forecasts and as many outcomes")
    ps, ys = np.asarray(p, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if not (np.isfinite(ps).all() and (ps >= 0).all() and (ps <= 1).all() and np.isin(ys, (0.0, 1.0)).all()):
        raise CalibrationError("forecasts must be probabilities and outcomes 0 or 1")
    points, where = np.unique(ps, return_inverse=True)
    weight = np.bincount(where, minlength=len(points)).astype(np.float64)
    total = np.bincount(where, weights=ys, minlength=len(points))
    blocks: list[list[float]] = []  # lo, hi, sum of outcomes, weight
    for x, s, w in zip(points.tolist(), total.tolist(), weight.tolist(), strict=True):
        blocks.append([x, x, s, w])
        while len(blocks) > 1 and blocks[-2][2] * blocks[-1][3] >= blocks[-1][2] * blocks[-2][3]:
            last = blocks.pop()
            blocks[-1][1] = last[1]
            blocks[-1][2] += last[2]
            blocks[-1][3] += last[3]
    values = [b[2] / b[3] for b in blocks]
    # No block is given 0 or 1: a block in which it never (or always) happened counts as half an event
    # short, so its value depends on how many forecasts it holds. Order is then restored.
    first, last = blocks[0], blocks[-1]
    if first[2] == 0:
        values[0] = 0.5 / (first[3] + 1)
    if last[2] == last[3]:
        values[-1] = 1 - 0.5 / (last[3] + 1)
    for k in range(1, len(values)):
        values[k] = max(values[k], values[k - 1])
    values = [min(v, values[-1]) for v in values]
    return Map(tuple(b[0] for b in blocks), tuple(b[1] for b in blocks), tuple(values), len(p))


def apply_map(found: Map, p: float, floor: float) -> float:
    """The calibrated value: the block's value, a straight line across a gap, the end value outside.

    Never 0 or 1: the result is held `floor` inside the edges, like the raw column.
    """
    if not 0 <= p <= 1 or not 0 < floor < 0.5:
        raise CalibrationError("a probability and a small positive floor are needed")
    k = bisect.bisect_right(found.lo, p) - 1
    if k < 0:
        out = found.value[0]
    elif p <= found.hi[k] or k == len(found.lo) - 1:
        out = found.value[k]
    else:
        share = (p - found.hi[k]) / (found.lo[k + 1] - found.hi[k])
        out = found.value[k] + share * (found.value[k + 1] - found.value[k])
    return min(max(out, floor), 1 - floor)


def reliability(p: Sequence[float], y: Sequence[int], edges: Sequence[float] = EDGES) -> list[dict[str, Any]]:
    """Forecasts grouped by published value: how many, their mean and how often it happened."""
    table = []
    for k in range(len(edges) - 1):
        last = k == len(edges) - 2
        inside = [i for i, v in enumerate(p) if edges[k] <= v < edges[k + 1] or (last and v == edges[k + 1])]
        if not inside:
            continue
        table.append(
            {
                "from": edges[k],
                "to": edges[k + 1],
                "n": len(inside),
                "mean_forecast": round(sum(p[i] for i in inside) / len(inside), 6),
                "observed": round(sum(y[i] for i in inside) / len(inside), 6),
            }
        )
    return table


def scores(p: Sequence[float], y: Sequence[int]) -> dict[str, Any]:
    if not p:
        raise CalibrationError("nothing to score")
    brier = sum((v - o) ** 2 for v, o in zip(p, y, strict=True)) / len(p)
    loss = -sum(math.log(v if o else 1 - v) for v, o in zip(p, y, strict=True)) / len(p)
    return {"n": len(p), "brier": round(brier, 8), "log_loss": round(loss, 8)}


def _seed(example: Example) -> int:
    label = f"calibration|{example.season}|{example.release_no}|{example.issue}"
    return int(sha256_hex(label.encode())[:12], 16)


def forecast_rows(examples: Sequence[Example], taus: Mapping[str, float], paths: int = PATHS) -> list[Row]:
    """What the raw column would have published for each past weekly release, with what then happened."""
    rows: list[Row] = []
    for e in examples:
        if e.kind != KIND:
            continue
        order = list(e.baseline2)
        counts = rank_frequencies(sample_orders(len(order), taus[e.issue], paths, seed=_seed(e)), RANKED)
        rank = {team: place for place, team in enumerate(e.actual, start=1)}
        for place, team in enumerate(order):
            for quantity in QUANTITIES:
                inside = int(counts[place, : CUT[quantity]].sum())
                happened = int(rank.get(team, RANKED + 1) <= CUT[quantity])
                rows.append(Row(e.season, e.issue, quantity, published_probability(inside, paths), happened))
    return rows


def _fit_taus(examples: Sequence[Example]) -> dict[str, float]:
    out = {}
    for issue in ISSUES:
        pairs = [(e.baseline2, e.actual) for e in examples if e.kind == KIND and e.issue == issue]
        if not pairs:
            raise CalibrationError(f"no weekly releases at {issue} to fit on")
        out[issue] = fit_temperature(pairs).tau
    return out


def _maps(rows: Sequence[Row]) -> dict[str, dict[str, Map]]:
    out: dict[str, dict[str, Map]] = {}
    for issue in ISSUES:
        out[issue] = {}
        for quantity in QUANTITIES:
            cell = [r for r in rows if r.issue == issue and r.quantity == quantity]
            out[issue][quantity] = fit_map([r.p for r in cell], [r.y for r in cell])
    return out


def leave_one_season_out(examples: Sequence[Example], paths: int = PATHS) -> dict[str, Any]:
    """Each season forecast and mapped by fits that exclude it; raw against calibrated, cell by cell."""
    seasons = sorted({e.season for e in examples if e.kind == KIND})
    if len(seasons) < 3:
        raise CalibrationError("at least three seasons are needed to verify a map")
    floor = 0.5 / paths
    before: dict[tuple[str, str], list[tuple[float, int]]] = {}
    after: dict[tuple[str, str], list[tuple[float, int]]] = {}
    held_out: dict[int, list[float]] = {}
    for season in seasons:
        others = [e for e in examples if e.season != season]
        taus = _fit_taus(others)
        maps = _maps(forecast_rows(others, taus, paths))
        held_out[season] = []
        for row in forecast_rows([e for e in examples if e.season == season], taus, paths):
            mapped = apply_map(maps[row.issue][row.quantity], row.p, floor)
            before.setdefault((row.issue, row.quantity), []).append((row.p, row.y))
            after.setdefault((row.issue, row.quantity), []).append((mapped, row.y))
            held_out[season].append(mapped)
    cells: dict[str, dict[str, Any]] = {}
    for issue in ISSUES:
        cells[issue] = {}
        for quantity in QUANTITIES:
            raw, mapped_rows = before[(issue, quantity)], after[(issue, quantity)]
            b = scores([v for v, _ in raw], [o for _, o in raw])
            a = scores([v for v, _ in mapped_rows], [o for _, o in mapped_rows])
            cells[issue][quantity] = {
                "before": b,
                "after": a,
                "verified": bool(a["log_loss"] < b["log_loss"] and a["brier"] <= b["brier"]),
                "reliability_before": reliability([v for v, _ in raw], [o for _, o in raw]),
                "reliability_after": reliability([v for v, _ in mapped_rows], [o for _, o in mapped_rows]),
            }
    return {"seasons": seasons, "criterion": CRITERION, "cells": cells, "held_out": held_out}


def fit_calibration(
    examples: Sequence[Example], season: int, *, taus: Mapping[str, float], paths: int = PATHS
) -> dict[str, Any]:
    """The maps document for `season`: fitted on every earlier weekly release at the temperatures in use,
    with the leave-one-season-out check that decides which maps may be published."""
    late = sorted({e.season for e in examples if e.season >= season})
    if late:
        raise CalibrationError(f"{late[0]} is not an earlier season than {season}")
    check = leave_one_season_out(examples, paths)
    maps = _maps(forecast_rows(examples, taus, paths))
    return {
        "season": season,
        "model": "isotonic map of the raw published probability, one per cutoff and quantity",
        "label": LABEL,
        "fitted_on_kind": KIND,
        "paths": paths,
        "floor": 0.5 / paths,
        "taus": {issue: float(taus[issue]) for issue in ISSUES},
        "trained_on": check["seasons"],
        "maps": {
            issue: {
                quantity: {"lo": list(m.lo), "hi": list(m.hi), "value": list(m.value), "n": m.n}
                for quantity, m in by.items()
            }
            for issue, by in maps.items()
        },
        "verification": {"criterion": check["criterion"], "cells": check["cells"]},
    }


@dataclass(frozen=True)
class Calibration:
    season: int
    sha256: str
    document: Mapping[str, Any]

    def verified(self, issue: str, quantity: str) -> bool:
        try:
            return bool(self.document["verification"]["cells"][issue][quantity]["verified"])
        except KeyError:
            return False

    def value(self, issue: str, quantity: str, p: float) -> float:
        try:
            m = self.document["maps"][issue][quantity]
        except KeyError as error:
            raise CalibrationError(f"no map for {issue}, {quantity}") from error
        found = Map(tuple(m["lo"]), tuple(m["hi"]), tuple(m["value"]), int(m["n"]))
        return apply_map(found, p, float(self.document["floor"]))


def _paths(root: Path | str, season: int) -> tuple[Path, Path]:
    folder = Path(root)
    return folder / f"calibration_{season}.json", folder / f"calibration_{season}.sha256"


def write_calibration(root: Path | str, season: int, document: Mapping[str, Any]) -> tuple[Path, str]:
    """Write the season's maps once. Returns the file and its SHA-256."""
    if int(document["season"]) != season:
        raise CalibrationError(f"the document is for {document['season']}, not {season}")
    path, side = _paths(root, season)
    already = f"{path} exists; fitted maps are never rewritten"
    if path.exists():
        raise CalibrationError(already)
    text = json.dumps(dict(document), sort_keys=True, indent=1, ensure_ascii=True, allow_nan=False)
    body = (text + "\n").encode()
    digest = sha256_hex(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    if side.exists():  # left by a write that stopped early
        side.chmod(0o644)
    side.write_text(f"{digest}  {path.name}\n")
    try:
        with path.open("xb") as handle:
            handle.write(body)
    except FileExistsError as error:
        raise CalibrationError(already) from error
    path.chmod(0o444)
    side.chmod(0o444)
    return path, digest


def load_calibration(root: Path | str, season: int) -> Calibration:
    path, side = _paths(root, season)
    if not path.exists() or not side.exists():
        raise CalibrationError(f"no calibration maps for {season} in {Path(root)}")
    body = path.read_bytes()
    digest = sha256_hex(body)
    if side.read_text().split()[0] != digest:
        raise CalibrationError(f"{path} does not match its recorded hash")
    document = json.loads(body)
    if int(document["season"]) != season:
        raise CalibrationError(f"{path} is for season {document['season']}")
    return Calibration(season, digest, document)
