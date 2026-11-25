"""Fitted rank-noise temperatures (SC-03): fitted on earlier seasons, saved once, read at each issue.

One temperature per baseline, issue time and kind of release: the opening release (anchored on the AP poll),
a weekly release, and the final release on Selection Day, which strays least from the order before it. The
file is written once by the `cfp` command and carries its own hash; an issue records that hash.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cfp.common.hashing import sha256_hex
from cfp.forecast.rank_noise import fit_temperature

KINDS: Final = ("opening", "weekly", "final")
BASELINES: Final = ("baseline1", "baseline2")
MODEL: Final = "orders drawn one team at a time with chance proportional to exp(-place / tau)"


class NoiseError(RuntimeError):
    """Rank-noise parameters cannot be fitted, written or read."""


@dataclass(frozen=True)
class Example:
    """One past issue: what each baseline said at its cutoff, and what the committee then published."""

    season: int
    release_no: int
    issue: str
    kind: str
    baseline1: Sequence[str]
    baseline2: Sequence[str]
    actual: Sequence[str]


def release_kind(release_no: int, of: int) -> str:
    """opening (no earlier release that season), final (Selection Day) or weekly."""
    if not 1 <= release_no <= of:
        raise ValueError(f"release {release_no} of {of} is not possible")
    return "opening" if release_no == 1 else "final" if release_no == of else "weekly"


def fit_noise(examples: Sequence[Example], season: int) -> dict[str, Any]:
    """The parameters document for `season`, fitted on the seasons before it."""
    if not examples:
        raise NoiseError(f"no earlier releases to fit {season} on")
    late = sorted({e.season for e in examples if e.season >= season})
    if late:
        raise NoiseError(f"{late[0]} is not an earlier season than {season}")
    temperatures: dict[str, Any] = {}
    for baseline in BASELINES:
        for issue in sorted({e.issue for e in examples}):
            for kind in KINDS:
                rows = [e for e in examples if e.issue == issue and e.kind == kind]
                if not rows:
                    continue
                fit = fit_temperature([(getattr(e, baseline), e.actual) for e in rows])
                temperatures.setdefault(baseline, {}).setdefault(issue, {})[kind] = {
                    "tau": fit.tau,
                    "releases": fit.releases,
                    "picks": fit.picks,
                    "log_likelihood": fit.log_likelihood,
                }
    return {
        "season": season,
        "model": MODEL,
        "trained_on": sorted({e.season for e in examples}),
        "examples": len(examples),
        "temperatures": temperatures,
    }


@dataclass(frozen=True)
class Noise:
    season: int
    sha256: str
    document: Mapping[str, Any]

    def tau(self, baseline: str, issue: str, kind: str) -> float:
        try:
            return float(self.document["temperatures"][baseline][issue][kind]["tau"])
        except KeyError as error:
            raise NoiseError(f"no temperature for {baseline}, {issue}, {kind}") from error


def _paths(root: Path | str, season: int) -> tuple[Path, Path]:
    folder = Path(root)
    return folder / f"rank_noise_{season}.json", folder / f"rank_noise_{season}.sha256"


def write_noise(root: Path | str, season: int, document: Mapping[str, Any]) -> tuple[Path, str]:
    """Write the season's rank-noise parameters once. Returns the file and its SHA-256."""
    path, side = _paths(root, season)
    if int(document["season"]) != season:
        raise NoiseError(f"the document is for {document['season']}, not {season}")
    text = json.dumps(dict(document), sort_keys=True, indent=1, ensure_ascii=True, allow_nan=False)
    body = (text + "\n").encode()
    digest = sha256_hex(body)
    already = f"{path} exists; fitted parameters are never rewritten"
    if path.exists():
        raise NoiseError(already)
    path.parent.mkdir(parents=True, exist_ok=True)
    if side.exists():  # left by a write that stopped early
        side.chmod(0o644)
    side.write_text(f"{digest}  {path.name}\n")
    try:
        with path.open("xb") as handle:
            handle.write(body)
    except FileExistsError as error:
        raise NoiseError(already) from error
    path.chmod(0o444)
    side.chmod(0o444)
    return path, digest


def load_noise(root: Path | str, season: int) -> Noise:
    path, side = _paths(root, season)
    if not path.exists() or not side.exists():
        raise NoiseError(f"no rank-noise parameters for {season} in {Path(root)}")
    body = path.read_bytes()
    digest = sha256_hex(body)
    if side.read_text().split()[0] != digest:
        raise NoiseError(f"{path} does not match its recorded hash")
    document = json.loads(body)
    if int(document["season"]) != season:
        raise NoiseError(f"{path} is for season {document['season']}")
    return Noise(season, digest, document)
