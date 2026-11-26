"""The field section of an issue (FF-01 to FF-05): pairings, prices, paths and rules in one document."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from cfp.forecast.final_field import FieldError
from cfp.forecast.noise_params import Noise
from cfp.forecast.pairings import Pairing, Pairings
from cfp.release.field import build_field

from .test_sim_inputs import GAME_SCHEMA, LINE_SCHEMA, game, past, quote

CUT = datetime(2026, 11, 29, 7, tzinfo=UTC)
BOUNDARY = datetime(2026, 12, 2, 0, tzinfo=UTC)  # the reveal of the last weekly release
DAY = datetime(2026, 12, 5, 21, tzinfo=UTC)
FINAL = datetime(2026, 12, 6, 17, tzinfo=UTC)  # the final list is revealed
TEAMS = [f"R{k:02d}" for k in range(1, 41)]
TITLES = {"sec": ("R01", "R06"), "big-ten": ("R02", "R09"), "big-12": ("R03", "R14"), "acc": ("R05", "R16")}
NOISE = Noise(
    2026,
    "ab" * 32,
    {
        "trained_on": [2024, 2025],
        "temperatures": {"baseline2": {"sun0200": {"final": {"tau": 1.3}, "final_two_back": {"tau": 3.0}}}},
    },
)


def league() -> dict[str, str]:
    out = {team: "sec" for team in TEAMS} | {"R04": "fbs-independents", "R22": "sun-belt", "R30": "sun-belt"}
    for conference, pair in TITLES.items():
        for team in pair:
            out[team] = conference
    return out


def frames(skip: str | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    old = [past(season) for season in (2024, 2025)]
    rows, quotes = [], []
    for conference, (home, away) in TITLES.items():
        if conference == skip:
            continue
        gid = f"t-{conference}"
        rows.append(game(gid, start_utc=DAY, home_id=home, away_id=away, neutral=True, title_game=True))
        quotes.append(quote(gid, "a", 3, (-150, 130), -3.0))
    games = pl.concat(
        [f[0] for f in old] + [pl.DataFrame(rows, schema_overrides=GAME_SCHEMA)], how="diagonal_relaxed"
    )
    lines = pl.concat(
        [f[1] for f in old] + [pl.DataFrame(quotes, schema_overrides=LINE_SCHEMA)], how="diagonal_relaxed"
    )
    return games, lines


def pairings(skip: str | None = None, **more: Any) -> Pairings:
    decided = {
        conference: Pairing(conference, DAY.date(), home, away, "official", "https://example.test/x", CUT)
        for conference, (home, away) in TITLES.items()
        if conference != skip
    }
    return Pairings(decided, more.get("scenarios", {}), more.get("open", []), "cd" * 32)


def section(**over: Any) -> dict[str, Any]:
    games, lines = frames(over.pop("skip_game", None))
    rows = [
        {"team_id": t, "initial": k, "losses": 0, "cfp_eligible": True} for k, t in enumerate(TEAMS, start=1)
    ]
    args: dict[str, Any] = {
        "season": 2026,
        "issue": "sun0200",
        "cutoff": CUT,
        "target": 5,
        "total": 6,
        "boundary": BOUNDARY,
        "final_reveal": FINAL,
        "rows": rows,
        "names": {t: f"School {t}" for t in TEAMS},
        "conference_of": league(),
        "games": games,
        "lines": lines,
        "noise": NOISE,
        "pairings": pairings(),
        "estimate": None,
        "stem": "scw-2026-r05-sun0200",
        "paths": 2000,
    }
    return build_field(**(args | over))


def test_section_holds_the_whole_forecast() -> None:
    doc = section()
    assert (doc["model"], doc["kind"], doc["tau"], doc["paths"]) == ("baseline", "final_two_back", 3.0, 2000)
    run = doc["forecast"]
    assert doc["scenarios"] is None
    assert sum(t["field_paths"] for t in run["teams"]) == 12 * 2000
    assert sum(t["bye_paths"] for t in run["teams"]) == 4 * 2000
    assert all(0.0 < t["p_field"] < 1.0 for t in run["teams"])
    assert [g["title_for"] for g in run["games"]] == ["acc", "big-12", "big-ten", "sec"]
    assert all(g["source"] == "moneyline" and g["title_week"] for g in run["games"])
    by = {t["team_id"]: t for t in run["teams"]}
    assert by["R14"]["next_game"]["field_if_win"] == by["R14"]["next_game"]["win_paths"]
    # the six-conference place is filled on every path, by one of that group's teams
    group = by["R22"]["route_paths"].get("automatic", 0) + by.get("R30", {"route_paths": {}})[
        "route_paths"
    ].get("automatic", 0)
    assert group == 2000
    assert len(run["today"]["field"]) == 12
    assert isinstance(run["seeds"]["games"], int)
    assert any("five" in note or "5 places" in note for note in doc["notes"])
    assert section() == doc  # the same inputs, the same section
    # a team with two games left is conditioned on the earlier one
    games, lines = frames()
    soon = pl.DataFrame(
        [game("rival", start_utc=CUT + timedelta(hours=10), home_id="R01", away_id="R20")],
        schema_overrides=GAME_SCHEMA,
    )
    price = pl.DataFrame([quote("rival", "a", 3, (-400, 300), None)], schema_overrides=LINE_SCHEMA)
    both = section(
        games=pl.concat([games, soon], how="diagonal_relaxed"),
        lines=pl.concat([lines, price], how="diagonal_relaxed"),
    )
    first = {t["team_id"]: t for t in both["forecast"]["teams"]}["R01"]["next_game"]
    assert first["game_id"] == "rival"
    assert first["win_paths"] + first["lose_paths"] == 2000
    assert section(target=6)["kind"] == "final"
    with pytest.raises(FieldError, match="last two releases"):
        section(target=3)


def test_unknown_pairings_become_scenarios_or_stop_the_section() -> None:
    with pytest.raises(FieldError, match="no champion or title game for sec"):
        section(skip_game="sec", pairings=pairings(skip="sec", open=["sec"]))
    options = [
        Pairing(
            "sec",
            DAY.date(),
            "R01",
            "R06",
            "scenario",
            "https://example.test/s",
            CUT,
            "R06 wins the tiebreak",
        ),
        Pairing(
            "sec",
            DAY.date(),
            "R01",
            "R07",
            "scenario",
            "https://example.test/s",
            CUT,
            "R07 wins the tiebreak",
        ),
    ]
    with pytest.raises(FieldError, match="no strength estimate"):
        section(skip_game="sec", pairings=pairings(skip="sec", scenarios={"sec": options}))
    doc = section(
        skip_game="sec",
        pairings=pairings(skip="sec", scenarios={"sec": options}),
        estimate=lambda home, away, neutral: 0.6,
    )
    assert doc["forecast"] is None
    assert [run["scenario"] for run in doc["scenarios"]] == [
        "sec: R06 wins the tiebreak",
        "sec: R07 wins the tiebreak",
    ]
    assert all(sum(t["field_paths"] for t in run["teams"]) == 12 * 2000 for run in doc["scenarios"])
    sec = next(g for g in doc["scenarios"][1]["games"] if g["title_for"] == "sec")
    assert (sec["away_id"], sec["source"], sec["p_home"]) == ("R07", "strength", 0.6)


def test_a_title_game_already_played_gives_its_champion() -> None:
    games, lines = frames()
    done = games.with_columns(
        status=pl.when(pl.col("game_id") == "t-sec").then(pl.lit("final")).otherwise(pl.col("status")),
        home_pts=pl.when(pl.col("game_id") == "t-sec").then(20).otherwise(pl.col("home_pts")),
        away_pts=pl.when(pl.col("game_id") == "t-sec").then(27).otherwise(pl.col("away_pts")),
    )
    doc = section(games=done, lines=lines, pairings=pairings(), cutoff=CUT)
    run = doc["forecast"]
    assert run["champions_decided"] == {"sec": "R06"}
    assert "t-sec" not in [g["game_id"] for g in run["games"]]
    assert {t["team_id"]: t for t in run["teams"]}["R06"]["field_paths"] == 2000
    tied = done.with_columns(
        away_pts=pl.when(pl.col("game_id") == "t-sec").then(20).otherwise(pl.col("away_pts"))
    )
    with pytest.raises(FieldError, match="no winner"):
        section(games=tied, lines=lines, pairings=pairings(), cutoff=CUT)


def test_games_after_the_final_reveal_are_not_simulated() -> None:
    """Army-Navy is played a week after Selection Day: it cannot cost anyone a place."""
    games, lines = frames()
    late = pl.DataFrame(
        [game("late", start_utc=FINAL + timedelta(days=6), home_id="R08", away_id="R21")],
        schema_overrides=GAME_SCHEMA,
    )
    price = pl.DataFrame([quote("late", "a", 3, (150, -180), None)], schema_overrides=LINE_SCHEMA)
    plain = section()
    more = section(
        games=pl.concat([games, late], how="diagonal_relaxed"),
        lines=pl.concat([lines, price], how="diagonal_relaxed"),
    )
    assert "late" not in [g["game_id"] for g in more["forecast"]["games"]]
    assert more["forecast"]["teams"] == plain["forecast"]["teams"]


def test_a_pairing_from_the_wrong_conference_is_refused_and_scenarios_share_draws() -> None:
    wrong = pairings()
    wrong.decided["sec"] = Pairing("sec", DAY.date(), "R02", "R09", "official", "https://example.test/x", CUT)
    with pytest.raises(FieldError, match="another conference"):
        section(pairings=wrong)
    same = [
        Pairing("sec", DAY.date(), "R01", "R06", "scenario", "https://example.test/s", CUT, "one"),
        Pairing("sec", DAY.date(), "R01", "R06", "scenario", "https://example.test/s", CUT, "two"),
    ]
    doc = section(
        skip_game="sec", pairings=pairings(skip="sec", scenarios={"sec": same}), estimate=lambda h, a, n: 0.6
    )
    assert doc["scenarios"][0]["teams"] == doc["scenarios"][1]["teams"]  # the same pairing, the same paths


SEC_OPTIONS = [
    Pairing("sec", DAY.date(), "R01", other, "scenario", "https://example.test/s", CUT, f"{other} gets in")
    for other in ("R06", "R07")
]


def test_the_section_says_when_pairings_and_results_were_known() -> None:
    doc = section(results_through=datetime(2026, 11, 29, 6, 56, tzinfo=UTC))
    assert doc["pairings_disclosure"] == (
        "Title pairings as known at 23:45 ET Saturday; results through 01:56 ET Sunday."
    )
    assert doc["notes"][0] == doc["pairings_disclosure"]
    assert (doc["conditional_on_pairings"], doc["market_contest"]) == (False, "eligible")
    assert doc["forecast"]["scenario_pairings"] == {}
    scen = section(
        skip_game="sec",
        pairings=pairings(skip="sec", scenarios={"sec": SEC_OPTIONS}),
        estimate=lambda home, away, neutral: 0.6,
    )
    assert scen["pairings_disclosure"] == (
        "Title pairings as known at 23:45 ET Saturday; results through the cutoff. A result ingested after "
        "23:45 ET Saturday may have ruled a listed scenario out."
    )
    assert scen["conditional_on_pairings"] is True
    assert scen["market_contest"].startswith("excluded")
    assert [run["scenario_pairings"] for run in scen["scenarios"]] == [
        {"sec": ["R01", "R06"]},
        {"sec": ["R01", "R07"]},
    ]
    assert any("no headline" in note for note in scen["notes"])
    late = dict(pairings().decided)
    late["sec"] = Pairing("sec", DAY.date(), "R01", "R06", "cfbd_schedule", "cfbd:/games", None)
    fallback = section(pairings=Pairings(late, {}, [], "cd" * 32))
    assert "schedule in the store at the cutoff" in fallback["pairings_disclosure"]
    assert "sec" in fallback["pairings_disclosure"]


def test_more_than_eight_combinations_are_not_delivered() -> None:
    def three(conference: str, first: str, others: tuple[str, ...]) -> list[Pairing]:
        return [
            Pairing(conference, DAY.date(), first, o, "scenario", "https://example.test/s", CUT, f"{o} in")
            for o in others
        ]

    league_of = league() | {"R07": "sec", "R08": "sec", "R10": "big-ten", "R11": "big-ten"}
    league_of |= {"R15": "big-12", "R17": "big-12"}
    many = {
        "sec": three("sec", "R01", ("R06", "R07", "R08")),
        "big-ten": three("big-ten", "R02", ("R09", "R10", "R11")),
    }
    found = Pairings({c: p for c, p in pairings().decided.items() if c not in many}, many, [], "cd" * 32)
    with pytest.raises(FieldError, match="9 pairing scenarios are too many"):
        section(pairings=found, conference_of=league_of, estimate=lambda home, away, neutral: 0.6)


def test_an_open_league_that_takes_the_other_conferences_place_is_treated_as_named() -> None:
    # the Sun Belt's teams take the place for the best of the other conferences on every path
    with pytest.raises(FieldError, match=r"sun-belt.*other conferences' place"):
        section(pairings=pairings(open=["sun-belt"]))
    doc = section(pairings=pairings(open=["mid-american"]))  # none of its teams takes that place
    assert doc["open_pairings"] == ["mid-american"]


def test_only_the_sunday_issue_names_an_entry_time() -> None:
    import copy

    doc = copy.deepcopy(dict(NOISE.document))
    doc["temperatures"]["baseline2"]["tminus60"] = doc["temperatures"]["baseline2"]["sun0200"]
    line = section(issue="tminus60", noise=Noise(2026, "ab" * 32, doc))["pairings_disclosure"]
    assert "23:45" not in line
    assert "start of the issuing run" in line


def test_the_section_states_who_listed_the_scenarios_and_who_takes_the_shared_place() -> None:
    options = [
        Pairing(
            "sec",
            DAY.date(),
            "R01",
            o,
            "scenario",
            "https://a.test/x https://b.test/y",
            CUT,
            f"{o} in",
            "possible pairings per a.test and b.test; not published by the conference",
        )
        for o in ("R06", "R07")
    ]
    found = Pairings(
        {c: p for c, p in pairings().decided.items() if c != "sec"},
        {"sec": options},
        [],
        "cd" * 32,
        (),
        ("sec: the schedule in the store shows R01 v R08, not the file's pairing",),
    )
    doc = section(skip_game="sec", pairings=found, estimate=lambda home, away, neutral: 0.6)
    assert doc["scenario_basis"] == {
        "sec": {
            "statement": "possible pairings per a.test and b.test; not published by the conference",
            "source_urls": ["https://a.test/x", "https://b.test/y"],
        }
    }
    assert doc["pairing_warnings"] == [
        "sec: the schedule in the store shows R01 v R08, not the file's pairing"
    ]
    assert any("R01 v R08" in note for note in doc["notes"])
    from cfp.forecast.rank_noise import published_probability as shown

    for run in doc["scenarios"]:  # each run on its own: nothing is merged across scenarios
        place = run["other_conferences_place"]
        assert place["sun-belt"] == shown(2000, 2000)
        assert place["mid-american"] == shown(0, 2000)  # every one of the six leagues is listed
        assert len(place) == 6
