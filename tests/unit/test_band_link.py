"""Reference band and link (P06; OR-01a, OR-03, OR-04, OR-13)."""

from __future__ import annotations

import math

import pytest

from cfp.open_ranking.band import BandError, band_ranks, reference_band
from cfp.open_ranking.link import probability, quantize
from cfp.open_ranking.strength import Fit

THETA = {f"T{i:02d}": 40.0 - i for i in range(1, 41)}  # T01 strongest


def fold(theta: dict[str, float], excluded: str | None = None, home_adv: float = 2.5) -> Fit:
    kept = {team: value for team, value in theta.items() if team != excluded}
    return Fit(kept, {}, kept, home_adv, 100, excluded)


def test_band_excludes_team() -> None:
    plain = reference_band(fold(THETA), 12)
    assert plain.members == tuple(f"T{i:02d}" for i in range(9, 17))
    assert plain.strength == pytest.approx(sum(40.0 - i for i in range(9, 17)) / 8)
    graded = reference_band(fold(THETA, excluded="T10"), 12)  # T10's own fold: it cannot be in its own band
    assert "T10" not in graded.members
    assert graded.members == ("T09", "T11", "T12", "T13", "T14", "T15", "T16", "T17")
    above = reference_band(
        fold(THETA, excluded="T03"), 12
    )  # removing a team above the band shifts it down one
    assert above.members == tuple(f"T{i:02d}" for i in range(10, 18))
    below = reference_band(fold(THETA, excluded="T30"), 12)
    assert below.members == plain.members


def test_band_ranks_by_era() -> None:
    assert (band_ranks(2014), band_ranks(2023)) == ((1, 8), (1, 8))
    assert (band_ranks(2024), band_ranks(2026)) == ((9, 16), (9, 16))
    assert band_ranks(2027) == (21, 28)
    assert reference_band(fold(THETA), 4).members[0] == "T01"
    late = reference_band(fold(THETA), 24)
    assert (late.members[0], late.members[-1], late.ranks) == ("T21", "T28", (21, 28))
    with pytest.raises(BandError, match="field size"):
        reference_band(fold(THETA), 8)
    with pytest.raises(BandError, match="needs 28"):
        reference_band(fold({k: v for k, v in THETA.items() if k < "T21"}), 24)


def test_band_order_does_not_depend_on_input_order_and_ties_break_by_team_id() -> None:
    tied = THETA | {"T16": THETA["T17"]}  # T16 and T17 share the last place in the band
    forward = reference_band(fold(tied), 12)
    backward = reference_band(fold(dict(reversed(list(tied.items())))), 12)
    assert forward == backward
    assert forward.members[-1] == "T16"


def test_link_logistic() -> None:
    assert probability(10.0, 10.0, 2.5, "neutral", 7.0) == 0.5
    assert probability(17.0, 10.0, 2.5, "neutral", 7.0) == pytest.approx(1 / (1 + math.exp(-1.0)))
    assert probability(10.0, 17.0, 2.5, "neutral", 7.0) == pytest.approx(1 - 1 / (1 + math.exp(-1.0)))
    assert probability(10.0, 10.0, 2.5, "neutral", 3.0) == 0.5
    assert probability(1000.0, 0.0, 0.0, "neutral", 1.0) == 1.0  # no overflow at the extremes
    assert probability(0.0, 1000.0, 0.0, "neutral", 1.0) == pytest.approx(0.0, abs=1e-300)
    with pytest.raises(ValueError, match="positive"):
        probability(1.0, 0.0, 0.0, "neutral", 0.0)


def test_link_site_sign() -> None:
    home = probability(10.0, 10.0, 2.5, "home", 7.0)
    away = probability(10.0, 10.0, 2.5, "away", 7.0)
    assert home == pytest.approx(1 / (1 + math.exp(-2.5 / 7.0)))
    assert away == pytest.approx(1 / (1 + math.exp(2.5 / 7.0)))
    assert home + away == pytest.approx(1.0)
    assert home > 0.5 > away
    with pytest.raises(ValueError, match="site"):
        probability(1.0, 0.0, 0.0, "campus", 7.0)  # type: ignore[arg-type]


def test_quantize_half_even() -> None:
    assert quantize(0.20) == (2000, False)
    assert quantize(0.90) == (9000, False)
    assert quantize(0.5) == (5000, False)
    assert quantize(0.0) == (0, False)
    assert quantize(1.0) == (10000, False)
    assert quantize(0.123449) == (1234, False)
    assert quantize(0.123451) == (1235, False)
    assert quantize(0.00025)[0] == 2  # 2.5 goes to the even neighbour
    assert quantize(0.00035)[0] in (3, 4)  # 3.5 is not exactly representable; the flag below is what matters
    for bad in (-0.01, 1.01, float("nan")):
        with pytest.raises(ValueError, match="probability"):
            quantize(bad)


def test_quantize_boundary_flag() -> None:
    assert quantize(0.00025) == (2, True)
    assert quantize(0.00035)[1] is True
    assert quantize(0.12345 + 5e-11)[1] is True  # within 1e-6 of a .5 boundary in units of 1e-4
    assert quantize(0.12345 - 5e-11)[1] is True
    assert quantize(0.12345 + 2e-10)[1] is False
    assert quantize(0.1234)[1] is False


def test_stronger_reference_lowers_points() -> None:
    """OR-13: a stronger bubble expects more wins, so any fixed win is worth less and a loss costs more."""
    for site in ("home", "away", "neutral"):
        weak, _ = quantize(probability(8.0, 12.0, 2.5, site, 7.0))  # type: ignore[arg-type]
        strong, _ = quantize(probability(11.0, 12.0, 2.5, site, 7.0))  # type: ignore[arg-type]
        assert strong > weak
        assert 10000 - strong < 10000 - weak
        assert -strong < -weak
