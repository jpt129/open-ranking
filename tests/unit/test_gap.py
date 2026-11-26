"""Committee Gap (CG-01 to CG-04): lift, consequence flags, reasons and aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cfp import cli
from cfp.forecast.final_field import INDEPENDENT
from cfp.gap.core import aggregate, consequences, interval80, lift, reasons, team_rows
from cfp.rules.engine import load_rules

from .store_helpers import Clock

TEAMS = [f"T{k:02d}" for k in range(1, 41)]
LEAGUES = ("sec", "big-ten", "big-12", "acc", "american-athletic", "mountain-west")
MEMBERS = {team: LEAGUES[k % len(LEAGUES)] for k, team in enumerate(TEAMS)}
RULES = load_rules(2026)


def counts(rank: int | None, paths: int = 100) -> list[int]:
    """Every path at one rank (or outside the 25)."""
    out = [0] * 26
    out[(rank - 1) if rank else 25] = paths
    return out


# --- CG-01 -------------------------------------------------------------------------


def test_lift_sign_and_example() -> None:
    """Open 13, forecast median 9, actual 8: lift 5, anticipated 4, one spot above the median."""
    assert lift(13, 8) == {"lift": 5, "bound": None}
    assert lift(8, 13)["lift"] == -5  # negative: the committee has the team lower
    spread = [0] * 26
    for rank, n in ((7, 10), (8, 20), (9, 40), (10, 20), (11, 10)):
        spread[rank - 1] = n
    open_ranks = {team: place for place, team in enumerate(TEAMS, start=1)}
    actual = [*TEAMS[:7], "T13", *TEAMS[7:12], *TEAMS[13:25]]  # T13 is eighth
    forecast = {"T13": {"median": 9, "rank_counts": spread, "paths": 100}}
    (row,) = [r for r in team_rows(open_ranks, forecast, actual) if r["team_id"] == "T13"]
    assert (row["open_rank"], row["forecast_median"], row["actual_rank"]) == (13, 9, 8)
    assert (row["lift"], row["anticipated"], row["beyond_forecast"]) == (5, 4, 1)
    assert row["forecast_interval80"] == [8, 10]  # a tenth of the paths lie beyond each end
    assert row["p_this_high_or_higher"] == pytest.approx(0.30)  # the forecast's chance of eighth or better
    assert interval80(counts(None), 100) == ["outside 25", "outside 25"]
    with pytest.raises(ValueError, match="paths"):
        interval80(spread, 99)


def test_outside_25_bound() -> None:
    assert lift(20, None) == {"lift": None, "bound": "at most -6"}  # 26th or lower: 20 - 26
    assert lift(30, None) == {"lift": None, "bound": "at most 4"}
    open_ranks = {team: place for place, team in enumerate(TEAMS, start=1)}
    actual = [*TEAMS[:24], "T30"]  # the committee left T25 out and ranked T30
    rows = {r["team_id"]: r for r in team_rows(open_ranks, {}, actual)}
    assert set(rows) == set(TEAMS[:25]) | {"T30"}  # everyone in either top 25
    assert rows["T25"]["actual_rank"] == "outside 25"
    assert (rows["T25"]["lift"], rows["T25"]["lift_bound"]) == (None, "at most -1")
    assert (rows["T30"]["open_rank"], rows["T30"]["lift"]) == (30, 5)
    assert rows["T25"]["forecast_median"] is None  # no forecast is said, not filled in


# --- CG-02 -------------------------------------------------------------------------


def run(
    committee: list[str], *, final: bool = False, champions: dict[str, str] | None = None
) -> dict[str, Any]:
    return consequences(
        RULES, TEAMS, committee, members=MEMBERS, eligible={}, champions=champions or {}, final=final
    )


def test_consequence_flags() -> None:
    assert run(TEAMS[:25])["flags"] == []
    one_apart = [*TEAMS[:3], "T05", "T04", *TEAMS[5:25]]  # fourth and fifth swap: one rank apart
    flags = run(one_apart)["flags"]
    byes = {(f["team_id"], f["open"], f["committee"]) for f in flags if f["change"] == "bye"}
    assert byes == {("T04", True, False), ("T05", False, True)}
    hosts = {(f["team_id"], f["open"], f["committee"]) for f in flags if f["change"] == "host"}
    assert hosts == {
        ("T04", False, True),
        ("T05", True, False),
    }  # fifth hosts a first-round game; fourth does not
    assert not [f for f in flags if f["change"] == "bid"]
    dropped = [*TEAMS[:4], *TEAMS[5:26]]  # the committee leaves T05 out of its 25
    bids = {(f["team_id"], f["open"], f["committee"]) for f in run(dropped)["flags"] if f["change"] == "bid"}
    assert ("T05", True, False) in bids
    assert sum(1 for _, was, now in bids if not was and now) == 1  # and exactly one team takes its place


def test_provisional_before_selection_day() -> None:
    weekly = run(TEAMS[:25])
    assert weekly["provisional"] is True
    assert weekly["scenario"]["open"]["sec"] == "T01"  # each conference's best-placed team stands in
    assert weekly["scenario"]["committee"]["big-ten"] == "T02"
    assert "stand" in weekly["scenario"]["note"]
    champions = {league: next(t for t in TEAMS if MEMBERS[t] == league) for league in LEAGUES}
    final = run(TEAMS[:25], final=True, champions=champions)
    assert final["provisional"] is False
    assert final["scenario"]["open"] == final["scenario"]["committee"] == {}
    with pytest.raises(ValueError, match="champion"):
        run(TEAMS[:25], final=True)  # Selection Day flags need the real champions


# --- CG-03, CG-04 ------------------------------------------------------------------


def open_team(team: str, total: int, rows: list[tuple[str, str, int]]) -> dict[str, Any]:
    return {
        "team_id": team,
        "total_cp": total,
        "head_to_head": None,
        "rows": [
            {
                "game_id": f"g-{team}-{opp}",
                "opponent_id": opp,
                "result": result,
                "points_cp": points,
                "week": 5,
            }
            for opp, result, points in rows
        ],
    }


def test_gap_reasons_present() -> None:
    teams = {
        "T04": open_team("T04", 21000, [("T09", "W", 8000), ("T20", "W", 3000), ("T30", "L", -9000)]),
        "T05": open_team("T05", 18000, [("T04", "L", -2000), ("T11", "W", 7000)]),
    }
    names = {t: f"School {t}" for t in TEAMS}
    remark = {"url": "https://example.test/chair", "published_utc": "2026-12-02T01:00:00+00:00"}
    got = reasons("T04", "T05", teams, names, remarks=[remark])
    assert got["ledger_difference_cp"] == 3000
    assert [g["opponent"] for g in got["decisive_games"]["T04"]][:2] == [
        "School T30",
        "School T09",
    ]  # by size
    assert got["head_to_head"]["met"] is True
    assert got["head_to_head"]["series"] == "School T04 1-0"  # only one ledger lists the meeting
    assert "display rule" in got["decisive_rule"]
    assert got["chair"] == [remark]
    assert "not delivered" in got["cross_league_sensitivity"]
    assert got["inference"] == "none added"
    none = reasons("T04", "T05", teams, names, remarks=[])
    assert none["chair"] == "no dated public explanation is on file for this release"


@pytest.mark.parametrize(
    ("mine", "theirs", "series"),
    [
        (
            [("T05", "W", 5000)],
            [("T04", "L", -5000)],
            "School T04 1-0",
        ),  # the real case: both ledgers list it
        ([("T05", "L", -5000)], [("T04", "W", 5000)], "School T05 1-0"),
        (
            [("T05", "W", 5000), ("T05", "L", -4000)],
            [("T04", "L", -5000), ("T04", "W", 4000)],
            "tied 1-1",
        ),
        (
            [("T05", "W", 5000), ("T05", "W", 4000)],
            [("T04", "L", -5000), ("T04", "L", -4000)],
            "School T04 2-0",
        ),
        ([("T09", "W", 5000)], [("T11", "W", 5000)], None),
    ],
)
def test_head_to_head_series(
    mine: list[tuple[str, str, int]], theirs: list[tuple[str, str, int]], series: str | None
) -> None:
    teams = {"T04": open_team("T04", 1, mine), "T05": open_team("T05", 1, theirs)}
    for k, team in enumerate(teams.values()):  # two meetings are two games
        for n, line in enumerate(team["rows"]):
            line["game_id"] = f"g{k}-{n}"
    names = {t: f"School {t}" for t in TEAMS}
    for a, b in (("T04", "T05"), ("T05", "T04")):
        got = reasons(a, b, teams, names, remarks=[])["head_to_head"]
        assert got["series"] == series
        assert got["met"] is (series is not None)


def test_bid_flag_one_rank_apart_and_the_guarantee() -> None:
    swapped = [*TEAMS[:11], "T13", "T12", *TEAMS[13:25]]  # twelfth and thirteenth swap
    bids = {(f["team_id"], f["open"], f["committee"]) for f in run(swapped)["flags"] if f["change"] == "bid"}
    assert bids == {("T12", True, False), ("T13", False, True)}
    # the 2026 guarantee: Notre Dame is in if ranked in the top 12
    irish = RULES.guarantee.team_id
    ours = [*TEAMS[:12], irish, *TEAMS[12:]]  # thirteenth in the Open Ranking
    theirs = [*TEAMS[:11], irish, *TEAMS[11:24]]  # twelfth for the committee
    members = MEMBERS | {irish: INDEPENDENT}
    got = consequences(RULES, ours, theirs, members=members, eligible={}, champions={}, final=False)
    assert (irish, False, True) in {(f["team_id"], f["open"], f["committee"]) for f in got["flags"]}


def test_selection_day_is_not_final_when_the_committee_field_needs_the_borrowed_tail() -> None:
    champions = {league: next(t for t in TEAMS if MEMBERS[t] == league) for league in LEAGUES}
    differing = [*TEAMS[:3], "T05", "T04", *TEAMS[5:25]]
    final = run(differing, final=True, champions=champions)
    assert final["provisional"] is False  # differing orders, every champion on file, nothing borrowed
    assert final["committee_field_from_tail"] == []
    assert {f["team_id"] for f in final["flags"]} == {"T04", "T05"}
    assert final["scenario"]["note"].startswith("Final")
    group = set(RULES.group)
    no_group = [t for t in TEAMS if MEMBERS[t] not in group][:25]  # the committee ranks no group-of-six team
    got = run(no_group, final=True, champions=champions)
    assert got["committee_field_from_tail"]  # the group place came from the Open Ranking's order
    assert set(got["committee_field_from_tail"]).isdisjoint(no_group)
    assert got["provisional"] is True
    assert "Final" not in got["scenario"]["note"]
    assert "did not rank" in got["scenario"]["note"]
    named_only = {league: team for league, team in champions.items() if league in RULES.named}
    with pytest.raises(ValueError, match="champion"):
        run(TEAMS[:25], final=True, champions={k: v for k, v in named_only.items() if k != "sec"})


def test_interval_across_the_edge_of_the_25() -> None:
    split = [0] * 26
    split[23], split[25] = 50, 50
    assert interval80(split, 100) == [24, "outside 25"]
    split[23], split[25] = 90, 10  # exactly a tenth in a tail is left outside the interval
    assert interval80(split, 100) == [24, 24]
    split[23], split[25] = 89, 11
    assert interval80(split, 100) == [24, "outside 25"]


def test_gap_aggregation_coverage() -> None:
    open_ranks = {team: place for place, team in enumerate(TEAMS, start=1)}
    actual = [*TEAMS[2:24], "T01", "T02", "T30"]  # the top two fall to 23rd and 24th; T25 out, T30 in
    got = aggregate(team_rows(open_ranks, {}, actual), MEMBERS)
    assert got["committee_only"] == ["T30"]
    assert got["open_only"] == ["T25"]
    assert got["shared"] == 24
    assert got["coverage"] == pytest.approx(24 / 25)
    # 22 teams up two places (+2 each), two down 22 (-22 each): (44 - 44) / 24
    assert got["mean_lift_shared"] == pytest.approx(0.0)
    assert got["mean_abs_lift_shared"] == pytest.approx(88 / 24)
    assert got["bounded"] == {"T25": "at most -1"}
    assert set(got["by_conference"]) <= set(LEAGUES)
    assert sum(c["shared"] for c in got["by_conference"].values()) == 24
    assert "one release" in got["variability"]


# --- the command -------------------------------------------------------------------


def test_gap_command_writes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cfp.gap import report

    reveal = datetime(2026, 12, 2, 0, 0, tzinfo=UTC)
    actual = [*TEAMS[:3], "T05", "T04", *TEAMS[5:25]]
    open_doc = {
        "edition_id": "or-2026-20261129t0700z-e1",
        "teams": [
            open_team(t, 30000 - 500 * k, [(TEAMS[(k + 7) % 40], "W", 6000)])
            | {"open_rank": k + 1, "order": k + 1}
            for k, t in enumerate(TEAMS)
        ],
    }
    forecast_doc = {
        "edition_id": "scw-2026-r05-tminus60-e1",
        "rank_noise": {"paths": 100},
        "forecasts": {
            "baseline2": {
                "rows": [
                    {"team_id": t, "median_rank": k + 1 if k < 25 else "outside 25", "cfp_eligible": True}
                    | {"rank_counts": counts(k + 1 if k < 25 else None)}
                    for k, t in enumerate(TEAMS)
                ]
            }
        },
    }
    inputs = report.Inputs(
        season=2026,
        release_id="cfp-2026-05",
        release_no=5,
        releases=6,
        reveal=reveal,
        actual=actual,
        open_edition=(open_doc, "a" * 64),
        forecast_edition=(forecast_doc, "b" * 64),
        members=MEMBERS,
        names={t: f"School {t}" for t in TEAMS},
        champions={},
        remarks=[],
    )
    monkeypatch.setattr(report, "load_inputs", lambda *a, **k: inputs)
    monkeypatch.setattr(cli, "_code_hash", lambda: "abc1234")
    argv = ["--lake", str(tmp_path / "lake"), "gap", "--release", "cfp-2026-05"]
    args = cli.build_parser().parse_args(argv)
    assert cli._gap(args, Clock(reveal.replace(hour=2))) == 0
    out = capsys.readouterr().out
    folder = tmp_path / "lake" / "gaps" / "gap-2026-r05-e1"
    doc = json.loads((folder / "gap.json").read_bytes())
    assert doc["open_edition"]["edition_id"] == "or-2026-20261129t0700z-e1"
    assert doc["open_edition"]["sha256"] == "a" * 64
    assert doc["forecast_edition"]["edition_id"] == "scw-2026-r05-tminus60-e1"
    assert doc["consequences"]["provisional"] is True
    assert (doc["mode"], doc["reference_only"]) == ("live", False)
    replayed = report.build_gap(report.Inputs(**{**inputs.__dict__, "mode": "replay"}), code_hash="x")
    assert replayed.gap_id == "gap-2026-r05-replay-e1"  # a rehearsal never takes the live report's name
    assert replayed.doc["reference_only"] is True
    flagged = {f["team_id"] for f in doc["consequences"]["flags"]}
    assert flagged == {"T04", "T05"}
    assert {r["pair"][0] for r in doc["reasons"]} <= flagged  # reasons only where a bid, bye or host changes
    assert doc["reasons"]
    assert "School T04" in out
    assert "provisional" in out
    assert not folder.stat().st_mode & 0o222
    assert cli._gap(args, Clock(reveal.replace(hour=2))) == cli.EXIT_EXISTS
    assert (
        cli._gap(args, Clock(reveal.replace(year=2026, month=12, day=1, hour=23))) == 1
    )  # before the reveal
