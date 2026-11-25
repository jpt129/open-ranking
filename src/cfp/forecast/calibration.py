"""The calibrated disclosure column for the weekly rank forecast (SC-05; John's rulings of 25 Nov 2026).

The raw baseline is published as the spec defines it. Beside it, labelled, goes a calibrated value. It is a
disclosure, not a promoted model, and both columns are scored.

- P(top 25): one monotone (isotonic) map per cutoff from the published probability to the frequency
  observed on past weekly releases, over every team.
- P(rank <= 4) and P(rank <= 12): a two-parameter logistic map on the logit of the published probability,
  fitted only on teams within ten places of that rank in the prior release, and published only for them.

A map is published only if it is verified leave-one-season-out: each season is mapped by a fit that excludes
it (the temperature too). The held-out log loss must fall without the Brier score rising, and for the
logistic maps no value for a team within five places of the rank may be below 0.01 or above 0.99.
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
from scipy.optimize import minimize

from cfp.common.hashing import sha256_hex
from cfp.forecast.noise_params import Example
from cfp.forecast.rank_noise import fit_temperature, published_probability, rank_frequencies, sample_orders

QUANTITIES: Final = ("top25", "rank4", "rank12")
CUT: Final = {"top25": 25, "rank4": 4, "rank12": 12}
LOGISTIC: Final = ("rank4", "rank12")  # fitted and published near the rank only
COHORT_WIDTH: Final = 10  # places either side of the rank that a logistic map is fitted on
NEAR_WIDTH: Final = 5  # places either side of the rank where a value must stay inside BOUNDS
BOUNDS: Final = (0.01, 0.99)
ISSUES: Final = ("sun0200", "tminus60")
KIND: Final = "weekly"
PATHS: Final = 10_000
RANKED: Final = 25
EDGES: Final = (0.0, 0.003, 0.01, 0.05, 0.2, 0.4, 0.6, 0.8, 0.95, 0.99, 0.997, 1.0)
LABEL: Final = "Calibrated: a disclosure column, not a promoted model. Both columns are scored."
CRITERION: Final = (
    "leave-one-season-out, temperature and map both fitted without the season: log loss lower than the raw "
    "column's and Brier score no higher; for rank <= 4 and rank <= 12, measured on teams within ten places "
    "of the rank in the prior release, with no value for a team within five places below 0.01 or above 0.99"
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
class Logistic:
    """calibrated = 1 / (1 + exp(-(intercept + slope * logit(published)))), slope > 0."""

    intercept: float
    slope: float
    n: int


@dataclass(frozen=True)
class Row:
    season: int
    issue: str
    quantity: str
    p: float  # the published probability
    y: int  # 1 if it happened
    place: int  # the team's place in the starting order (the prior release first), from 1


def cohort(quantity: str, width: int = COHORT_WIDTH) -> tuple[int, int] | None:
    """Starting-order places a quantity's map covers, or None for every team."""
    if quantity not in LOGISTIC:
        return None
    return max(1, CUT[quantity] - width), CUT[quantity] + width


def _inside(quantity: str, place: int, width: int = COHORT_WIDTH) -> bool:
    span = cohort(quantity, width)
    return span is None or span[0] <= place <= span[1]


def _check(p: Sequence[float], y: Sequence[int]) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    if not p or len(p) != len(y):
        raise CalibrationError("a map needs forecasts and as many outcomes")
    ps, ys = np.asarray(p, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if not (np.isfinite(ps).all() and (ps >= 0).all() and (ps <= 1).all() and np.isin(ys, (0.0, 1.0)).all()):
        raise CalibrationError("forecasts must be probabilities and outcomes 0 or 1")
    return ps, ys


def fit_map(p: Sequence[float], y: Sequence[int]) -> Map:
    """Isotonic regression of outcomes on published probabilities (pool adjacent violators).

    The end blocks are kept off 0 and 1 by half an event (see below).
    """
    ps, ys = _check(p, y)
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


def _logit(p: float, floor: float) -> float:
    held = min(max(p, floor), 1 - floor)
    return math.log(held / (1 - held))


def fit_logistic(p: Sequence[float], y: Sequence[int], floor: float) -> Logistic:
    """Slope and intercept on the logit of the published value, by maximum likelihood; slope kept positive."""
    ps, ys = _check(p, y)
    if ys.min() == ys.max():
        raise CalibrationError("a logistic map needs both outcomes in its data")
    x = np.array([_logit(float(v), floor) for v in ps])

    def loss(theta: np.ndarray[Any, Any]) -> float:
        z = theta[0] + theta[1] * x
        return float(np.sum(np.logaddexp(0.0, z) - ys * z))

    found = minimize(loss, x0=np.array([0.0, 1.0]), method="L-BFGS-B", bounds=[(-30.0, 30.0), (1e-3, 30.0)])
    if not found.success:
        raise CalibrationError(f"the logistic fit did not converge: {found.message}")
    return Logistic(float(found.x[0]), float(found.x[1]), len(p))


def apply_logistic(found: Logistic, p: float, floor: float) -> float:
    if not 0 <= p <= 1 or not 0 < floor < 0.5:
        raise CalibrationError("a probability and a small positive floor are needed")
    z = found.intercept + found.slope * _logit(p, floor)
    return min(max(1 / (1 + math.exp(-z)), floor), 1 - floor)


def _apply(found: Map | Logistic, p: float, floor: float) -> float:
    return apply_map(found, p, floor) if isinstance(found, Map) else apply_logistic(found, p, floor)


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
        if sorted(e.initial) != sorted(order):
            raise CalibrationError(f"{e.season} release {e.release_no}: the starting order is not recorded")
        start = {team: place for place, team in enumerate(e.initial, start=1)}
        counts = rank_frequencies(sample_orders(len(order), taus[e.issue], paths, seed=_seed(e)), RANKED)
        rank = {team: place for place, team in enumerate(e.actual, start=1)}
        for place, team in enumerate(order):
            for quantity in QUANTITIES:
                inside = int(counts[place, : CUT[quantity]].sum())
                happened = int(rank.get(team, RANKED + 1) <= CUT[quantity])
                p = published_probability(inside, paths)
                rows.append(Row(e.season, e.issue, quantity, p, happened, start[team]))
    return rows


def _fit_taus(examples: Sequence[Example]) -> dict[str, float]:
    out = {}
    for issue in ISSUES:
        pairs = [(e.baseline2, e.actual) for e in examples if e.kind == KIND and e.issue == issue]
        if not pairs:
            raise CalibrationError(f"no weekly releases at {issue} to fit on")
        out[issue] = fit_temperature(pairs).tau
    return out


def _cell(rows: Sequence[Row], issue: str, quantity: str) -> list[Row]:
    """The forecasts a cell's map is fitted and judged on: every team, or the teams near the rank."""
    return [r for r in rows if r.issue == issue and r.quantity == quantity and _inside(quantity, r.place)]


def _maps(rows: Sequence[Row], floor: float) -> dict[str, dict[str, Map | Logistic]]:
    out: dict[str, dict[str, Map | Logistic]] = {}
    for issue in ISSUES:
        out[issue] = {}
        for quantity in QUANTITIES:
            cell = _cell(rows, issue, quantity)
            p, y = [r.p for r in cell], [r.y for r in cell]
            out[issue][quantity] = fit_logistic(p, y, floor) if quantity in LOGISTIC else fit_map(p, y)
    return out


def leave_one_season_out(examples: Sequence[Example], paths: int = PATHS) -> dict[str, Any]:
    """Each season forecast and mapped by fits that exclude it; raw against calibrated, cell by cell."""
    seasons = sorted({e.season for e in examples if e.kind == KIND})
    if len(seasons) < 3:
        raise CalibrationError("at least three seasons are needed to verify a map")
    floor = 0.5 / paths
    kept: dict[tuple[str, str], list[tuple[float, float, int, int]]] = {}  # raw, mapped, outcome, place
    held_out: dict[int, list[float]] = {}
    for season in seasons:
        others = [e for e in examples if e.season != season]
        taus = _fit_taus(others)
        maps = _maps(forecast_rows(others, taus, paths), floor)
        held_out[season] = []
        for row in forecast_rows([e for e in examples if e.season == season], taus, paths):
            if not _inside(row.quantity, row.place):
                continue
            mapped = _apply(maps[row.issue][row.quantity], row.p, floor)
            kept.setdefault((row.issue, row.quantity), []).append((row.p, mapped, row.y, row.place))
            held_out[season].append(mapped)
    cells: dict[str, dict[str, Any]] = {}
    for issue in ISSUES:
        cells[issue] = {}
        for quantity in QUANTITIES:
            got = kept[(issue, quantity)]
            raw, mapped_values, y = [g[0] for g in got], [g[1] for g in got], [g[2] for g in got]
            b, a = scores(raw, y), scores(mapped_values, y)
            cell: dict[str, Any] = {
                "before": b,
                "after": a,
                "cohort_places": list(cohort(quantity) or ()) or None,
                "reliability_before": reliability(raw, y),
                "reliability_after": reliability(mapped_values, y),
            }
            better = bool(a["log_loss"] < b["log_loss"] and a["brier"] <= b["brier"])
            if quantity in LOGISTIC:
                near = [g[1] for g in got if _inside(quantity, g[3], NEAR_WIDTH)]
                cell["near_values"] = {"n": len(near), "min": min(near), "max": max(near)}
                cell["near_in_bounds"] = bool(BOUNDS[0] <= min(near) and max(near) <= BOUNDS[1])
                better = better and cell["near_in_bounds"]
            cell["verified"] = better
            cells[issue][quantity] = cell
    return {"seasons": seasons, "criterion": CRITERION, "cells": cells, "held_out": held_out}


def _as_json(found: Map | Logistic) -> dict[str, Any]:
    if isinstance(found, Map):
        return {
            "kind": "isotonic",
            "lo": list(found.lo),
            "hi": list(found.hi),
            "value": list(found.value),
            "n": found.n,
        }
    return {"kind": "logistic", "intercept": found.intercept, "slope": found.slope, "n": found.n}


def fit_calibration(
    examples: Sequence[Example], season: int, *, taus: Mapping[str, float], paths: int = PATHS
) -> dict[str, Any]:
    """The maps document for `season`: fitted on every earlier weekly release at the temperatures in use,
    with the leave-one-season-out check that decides which maps may be published."""
    late = sorted({e.season for e in examples if e.season >= season})
    if late:
        raise CalibrationError(f"{late[0]} is not an earlier season than {season}")
    check = leave_one_season_out(examples, paths)
    floor = 0.5 / paths
    maps = _maps(forecast_rows(examples, taus, paths), floor)
    return {
        "season": season,
        "model": "top 25: isotonic map of the raw published probability over every team; rank <= 4 and "
        "rank <= 12: logistic map on its logit, for teams near the rank; one map per cutoff",
        "label": LABEL,
        "fitted_on_kind": KIND,
        "paths": paths,
        "floor": floor,
        "bounds_near_rank": list(BOUNDS),
        "near_width": NEAR_WIDTH,
        "taus": {issue: float(taus[issue]) for issue in ISSUES},
        "trained_on": check["seasons"],
        "maps": {issue: {q: _as_json(m) for q, m in by.items()} for issue, by in maps.items()},
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

    def covers(self, quantity: str, place: int) -> bool:
        """Whether the quantity's map was fitted on teams at this starting-order place."""
        return _inside(quantity, place)

    def near(self, quantity: str, place: int) -> bool:
        """Whether a value at this place must stay inside the published bounds."""
        return quantity in LOGISTIC and _inside(quantity, place, NEAR_WIDTH)

    def value(self, issue: str, quantity: str, p: float) -> float:
        try:
            m = self.document["maps"][issue][quantity]
        except KeyError as error:
            raise CalibrationError(f"no map for {issue}, {quantity}") from error
        floor = float(self.document["floor"])
        if m.get("kind", "isotonic") == "logistic":
            return apply_logistic(Logistic(float(m["intercept"]), float(m["slope"]), int(m["n"])), p, floor)
        return apply_map(Map(tuple(m["lo"]), tuple(m["hi"]), tuple(m["value"]), int(m["n"])), p, floor)


def _paths(root: Path | str, season: int, correction: int = 0) -> tuple[Path, Path]:
    folder = Path(root)
    stem = f"calibration_{season}" + (f".c{correction}" if correction else "")
    return folder / f"{stem}.json", folder / f"{stem}.sha256"


def _latest(root: Path | str, season: int) -> int:
    """The highest correction on file (0 is the first fit); -1 when there is none. The chain must be whole."""
    folder = Path(root)
    found: set[int] = set()
    for item in folder.glob(f"calibration_{season}*") if folder.is_dir() else ():
        if item.suffix not in (".json", ".sha256"):
            continue
        middle = item.name.removeprefix(f"calibration_{season}").removesuffix(item.suffix)
        if middle == "":
            found.add(0)
        elif middle.startswith(".c") and middle[2:].isdigit():
            found.add(int(middle[2:]))
        else:
            raise CalibrationError(f"{item} is not a calibration file name")
    if not found:
        return -1
    if found != set(range(max(found) + 1)):
        raise CalibrationError(f"the calibration files for {season} have a gap: {sorted(found)}")
    for n in sorted(found):
        path, side = _paths(root, season, n)
        if not path.exists() or not side.exists():
            raise CalibrationError(f"{path} or its recorded hash is missing")
        if side.read_text().split()[0] != sha256_hex(path.read_bytes()):
            raise CalibrationError(f"{path} does not match its recorded hash")
    return max(found)


def write_calibration(
    root: Path | str, season: int, document: Mapping[str, Any], *, correction_reason: str | None = None
) -> tuple[Path, str]:
    """Write the season's maps once. Returns the file and its SHA-256.

    A file is never rewritten. With `correction_reason`, a new fit is written beside the earlier one as the
    next numbered correction, naming the file it replaces and why; the loader reads the latest.
    """
    if int(document["season"]) != season:
        raise CalibrationError(f"the document is for {document['season']}, not {season}")
    path, side = _paths(root, season)
    if correction_reason is not None:
        if not correction_reason.strip():
            raise CalibrationError("a correction needs a reason")
        last = _latest(root, season)
        if last < 0:
            raise CalibrationError(f"there is nothing to correct for {season} in {Path(root)}")
        earlier = load_calibration(root, season)
        path, side = _paths(root, season, last + 1)
        document = dict(document) | {
            "correction": last + 1,
            "supersedes_sha256": earlier.sha256,
            "correction_reason": correction_reason.strip(),
        }
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
    """The season's maps: the latest correction on file, or the first fit."""
    last = _latest(root, season)
    if last < 0:
        raise CalibrationError(f"no calibration maps for {season} in {Path(root)}")
    path, _ = _paths(root, season, last)
    body = path.read_bytes()
    document = json.loads(body)
    if int(document["season"]) != season:
        raise CalibrationError(f"{path} is for season {document['season']}")
    return Calibration(season, sha256_hex(body), document)
