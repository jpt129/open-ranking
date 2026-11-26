"""Field and bye outcome scoring in the scorecard (VT-12): a published field section against Selection Day."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from cfp.common.hashing import sha256_hex
from cfp.forecast.rank_noise import published_probability
from cfp.rules.engine import load_rules
from cfp.scoring import scorecard
from cfp.scoring.scorecard import ScoreRefused, actual_field, build_scorecard, score_field_section
from cfp.store.lake import Lake

from .store_helpers import Clock, frame
from .test_issue import CUTOFF, REVEAL, TEAMS, release_rows, run_live, world

PATHS = 100
POPULATION = TEAMS[:20]
LEAGUES = ("sec", "big-ten", "big-12", "acc", "american-athletic", "mountain-west")
MEMBERS = {team: LEAGUES[k % len(LEAGUES)] for k, team in enumerate(TEAMS)}
CHAMPIONS = {league: next(t for t in TEAMS if MEMBERS[t] == league) for league in LEAGUES}
AFTER = REVEAL + timedelta(hours=1)
LATER = "2026,2026-12-06,2026-12-06,12:00,primary,https://example.test/s,,\n"


def team(name: str, field: int, bye: int, routes: dict[str, int]) -> dict[str, Any]:
    return {"team_id": name, "field_paths": field, "bye_paths": bye, "route_paths": routes}


RUN = [
    team("T01", 100, 100, {"automatic": 100}),
    team("T02", 80, 40, {"automatic": 20, "at_large": 60}),
    team("T03", 20, 0, {"at_large": 20}),
]


def edition(section: dict[str, Any] | None, bubble: list[str] | None = None) -> dict[str, Any]:
    return {
        "season": 2026,
        "issue": "tminus60",
        "target_release_no": 6,
        "rank_noise": {"paths": PATHS, "pairwise": {"teams": bubble} if bubble else None},
        "forecasts": {"baseline2": {"rows": [{"team_id": t} for t in POPULATION]}},
        "final_field": section,
    }


class Entry:
    def __init__(self, bye: bool, route: str) -> None:
        self.bye, self.route, self.qualifier = bye, route, True


ACTUAL = {"T01": Entry(True, "auto:sec"), "T03": Entry(False, "at_large")}


def test_field_section_is_scored_against_the_actual_field() -> None:
    doc = edition(
        {"paths": PATHS, "forecast": {"scenario": None, "teams": RUN}}, bubble=["T02", "T03", "T04"]
    )
    got = score_field_section(doc, ACTUAL)
    assert (got["teams"], got["bubble"], got["lead"]) == (20, ["T02", "T03", "T04"], "r06-tminus60")
    (run,) = got["runs"]
    assert run["scenario"] is None
    assert (got["basis"], got["market_contest"]) == ("unconditional", "eligible")
    low, high = published_probability(0, PATHS), published_probability(PATHS, PATHS)
    assert 0 < low < high < 1  # a team with no paths is still scored, half a path from zero
    field = ((1 - high) ** 2 + 0.8**2 + (1 - 0.2) ** 2 + 17 * low**2) / 20
    assert run["scores"]["overall"]["field"]["n"] == 20
    assert run["scores"]["overall"]["field"]["brier"] == pytest.approx(field)
    bye = ((1 - high) ** 2 + 0.4**2 + 18 * low**2) / 20  # only T01 has a bye
    assert run["scores"]["overall"]["bye"]["brier"] == pytest.approx(bye)
    bubble = run["scores"]["by"]["bubble"]["bubble"]["field"]
    assert bubble["n"] == 3
    assert bubble["brier"] == pytest.approx((0.8**2 + 0.8**2 + low**2) / 3)
    auto = run["scores"]["by"]["route"]["automatic"]
    assert auto["brier"] == pytest.approx(((1 - high) ** 2 + 0.2**2 + 18 * low**2) / 20)
    at_large = run["scores"]["by"]["route"]["at_large"]  # T02 0.6 and did not; T03 0.2 and did
    assert at_large["brier"] == pytest.approx((0.6**2 + 0.8**2 + 18 * low**2) / 20)
    assert run["scores"]["overall"]["field"]["log_loss"] > 0


def test_only_the_scenario_that_matches_the_actual_pairings_is_scored() -> None:
    other = [team("T01", 100, 100, {"automatic": 100}), team("T03", 100, 0, {"at_large": 100})]
    runs = [
        {"scenario": "sec: A v B", "scenario_pairings": {"sec": ["T01", "T02"]}, "teams": RUN},
        {"scenario": "sec: A v C", "scenario_pairings": {"sec": ["T01", "T03"]}, "teams": other},
    ]
    doc = edition({"paths": PATHS, "forecast": None, "scenarios": runs})
    played = {"sec": frozenset({"T03", "T01"}), "acc": frozenset({"T05", "T06"})}
    got = score_field_section(doc, ACTUAL, played)
    (run,) = got["runs"]  # no merged or averaged score, and no headline scenario
    assert run["scenario"] == "sec: A v C"
    assert got["basis"] == "conditional on pairings"
    assert got["not_scored"] == ["sec: A v B"]
    assert got["market_contest"].startswith("excluded")
    assert "never combined" in got["note"]
    assert got["bubble"] == []  # no bubble was fixed at the issue: none is made up afterwards
    assert run["scores"]["by"]["bubble"].keys() == {"other"}
    alone = score_field_section(edition({"paths": PATHS, "forecast": {"teams": other}}), ACTUAL)
    assert run["scores"] == alone["runs"][0]["scores"]

    nobody = score_field_section(doc, ACTUAL, {"sec": frozenset({"T08", "T09"})})
    assert nobody["runs"] == []
    assert nobody["not_scored"] == ["sec: A v B", "sec: A v C"]
    assert nobody["note"].startswith("not scored: pairing not listed")
    assert nobody["miss"] is True  # logged as a miss, not left out; the scorecard lists it under "misses"
    assert "miss" not in got
    assert nobody["basis"] == "conditional on pairings"
    with pytest.raises(ScoreRefused, match="actual pairings"):
        score_field_section(doc, ACTUAL)
    with pytest.raises(ScoreRefused, match="actual pairings"):
        score_field_section(doc, ACTUAL, {"acc": frozenset({"T05", "T06"})})  # the SEC game is not on file


def test_a_field_team_the_edition_never_listed_refuses() -> None:
    doc = edition({"paths": PATHS, "forecast": {"scenario": None, "teams": RUN}})
    with pytest.raises(ScoreRefused, match="T30"):
        score_field_section(doc, ACTUAL | {"T30": Entry(False, "at_large")})


def test_actual_field_is_the_rules_applied_to_the_final_list() -> None:
    rules = load_rules(2026)
    got = actual_field(2026, TEAMS[:25], CHAMPIONS, eligible={}, conference_of=MEMBERS)
    assert len(got) == rules.field_size
    assert sum(1 for e in got.values() if e.bye) == len(rules.byes)
    assert set(CHAMPIONS[c] for c in rules.named) <= set(got)
    named = {c: t for c, t in CHAMPIONS.items() if c != "sec"}
    with pytest.raises(ScoreRefused, match="sec"):
        actual_field(2026, TEAMS[:25], named, eligible={}, conference_of=MEMBERS)
    group = set(rules.group)
    ranked = [t for t in TEAMS if MEMBERS[t] not in group]  # twenty teams, none from the six conferences
    more = [f"X{k:02d}" for k in range(5)]
    members = MEMBERS | {t: "sec" for t in more}
    with pytest.raises(ScoreRefused, match="did not rank"):  # the six-conference team is outside the 25
        actual_field(2026, [*ranked, *more], CHAMPIONS, eligible={}, conference_of=members)


def reveal(tmp_path: Path) -> Lake:
    lake = Lake(tmp_path / "lake", clock=Clock(REVEAL + timedelta(minutes=10)))
    lake.append("committee_releases", frame("committee_releases", release_rows(lake, 2, REVEAL, TEAMS[:25])))
    return lake


def build(tmp_path: Path) -> dict[str, Any]:
    lake = Lake(tmp_path / "lake", clock=Clock(AFTER))
    return build_scorecard(lake, "cfp-2026-02", now=AFTER, code_hash="abc1234", data=tmp_path / "data").doc


def with_field(tmp_path: Path) -> None:
    """A second live edition for the same reveal that carries a field section, recorded before the reveal."""
    lake = Lake(tmp_path / "lake", clock=Clock(CUTOFF + timedelta(hours=1)))
    first = "scw-2026-r02-sun0200-e1"
    row = lake.scan("editions").collect().row(0, named=True)
    doc = json.loads((tmp_path / "lake" / "editions" / first / "edition.json").read_bytes())
    order = [r["team_id"] for r in doc["forecasts"]["baseline2"]["rows"]]
    teams = [team(t, 100, 100 if k < 4 else 0, {"at_large": 100}) for k, t in enumerate(order[:12])]
    name = "scw-2026-r02-tminus60-e1"
    doc |= {"edition_id": name, "issue": "tminus60", "final_field_error": None}
    doc["final_field"] = {"kind": "final", "paths": PATHS, "forecast": {"scenario": None, "teams": teams}}
    body = json.dumps(doc, sort_keys=True).encode()
    folder = tmp_path / "lake" / "editions" / name
    folder.mkdir()
    (folder / "edition.json").write_bytes(body)
    new = row | {"edition_id": name, "sha256": sha256_hex(body), "ingest_time": None}
    new |= {"raw_hash": lake.put_raw(body), "correction_version": 0}
    lake.append("editions", frame("editions", [new]))


def test_scorecard_scores_the_field_only_on_selection_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world(tmp_path, leagues=MEMBERS)
    assert run_live(tmp_path, CUTOFF + timedelta(minutes=5), monkeypatch) == 0
    reveal(tmp_path)
    card = build(tmp_path)  # release 2 is the last on the calendar, but no edition carries a field forecast
    assert card["field_outcome"]["scored"] is False
    assert card["field_outcome"]["reason"] == "no edition this season carries a field forecast"
    with_field(tmp_path)
    champions = {c: t for c, t in CHAMPIONS.items()}
    monkeypatch.setattr(scorecard, "past_champions", lambda *a, **k: ({2026: champions}, {}, []))
    card = build(tmp_path)
    outcome = card["field_outcome"]
    assert outcome["scored"] is True
    assert "rules applied" in outcome["source"]
    assert len(outcome["field"]) == 12
    assert len(outcome["byes"]) == 4
    assert outcome["champions"] == champions
    (scored,) = outcome["editions"]
    assert scored["edition_id"] == "scw-2026-r02-tminus60-e1"
    assert scored["prospective"] is True
    assert scored["runs"][0]["scores"]["overall"]["field"]["n"] == 30
    by_id = {e["edition_id"]: e for e in card["editions"]}
    assert by_id["scw-2026-r02-tminus60-e1"]["field"]["outcome"] == "scored: see field_outcome"
    monkeypatch.setattr(scorecard, "past_champions", lambda *a, **k: ({2026: {}}, {}, ["sec: no final game"]))
    refused = build(tmp_path)["field_outcome"]  # the weekly scores stand; the field is not guessed
    assert refused["scored"] is False
    assert "sec: no final game" in refused["reason"]
    with (tmp_path / "data" / "cfp_reveals.csv").open("a") as out:
        out.write(LATER)
    assert build(tmp_path)["field_outcome"] is None  # not Selection Day: nothing to score yet


def test_score_command_prints_the_field_scores_or_says_why_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cfp import cli

    world(tmp_path, leagues=MEMBERS)
    assert run_live(tmp_path, CUTOFF + timedelta(minutes=5), monkeypatch) == 0
    reveal(tmp_path)
    with_field(tmp_path)
    argv = [
        "--lake",
        str(tmp_path / "lake"),
        "--data",
        str(tmp_path / "data"),
        "score",
        "--release",
        "cfp-2026-02",
    ]
    monkeypatch.setattr(scorecard, "past_champions", lambda *a, **k: ({2026: {}}, {}, ["sec: no final game"]))
    assert cli._score(cli.build_parser().parse_args(argv), Clock(AFTER)) == 0  # the weekly scores are written
    assert "the field is not scored: champions" in capsys.readouterr().err
    monkeypatch.setattr(scorecard, "past_champions", lambda *a, **k: ({2026: dict(CHAMPIONS)}, {}, []))
    assert cli._score(cli.build_parser().parse_args([*argv, "--revision", "2"]), Clock(AFTER)) == 0
    out = capsys.readouterr().out
    assert "scw-2026-r02-tminus60-e1 (prospective): field Brier" in out
    assert "bye Brier" in out
    assert "bubble Brier" in out


def earlier_edition(tmp_path: Path, name: str, *, reveal_utc: str | None = None, teams: Any = None) -> Path:
    """A title-week edition issued for release 1 (revealed a week before), carrying a field section."""
    from .test_issue import PRIOR

    recorded = PRIOR - timedelta(days=2)
    lake = Lake(tmp_path / "lake", clock=Clock(recorded))
    row = lake.scan("editions").collect().row(0, named=True)
    doc = json.loads(
        (tmp_path / "lake" / "editions" / "scw-2026-r02-sun0200-e1" / "edition.json").read_bytes()
    )
    order = [r["team_id"] for r in doc["forecasts"]["baseline2"]["rows"]]
    if teams is None:
        teams = [team(t, 60, 0, {"at_large": 60}) for t in order[:12]]
    doc |= {
        "edition_id": name,
        "target_release_no": 1,
        "cutoff_utc": (recorded - timedelta(hours=1)).isoformat(),
    }
    doc |= {"reveal_utc": reveal_utc or PRIOR.isoformat(), "final_field_error": None}
    doc["issue"] = name.split("-")[3]
    doc["final_field"] = {
        "kind": "final_two_back",
        "paths": PATHS,
        "forecast": {"scenario": None, "teams": teams},
    }
    body = json.dumps(doc, sort_keys=True).encode()
    folder = tmp_path / "lake" / "editions" / name
    folder.mkdir()
    (folder / "edition.json").write_bytes(body)
    new = row | {"edition_id": name, "sha256": sha256_hex(body), "ingest_time": None, "issue_utc": recorded}
    new |= {"raw_hash": lake.put_raw(body), "correction_version": 0}
    new |= {"first_public_time": recorded, "event_time": recorded}
    lake.append("editions", frame("editions", [new]))
    return folder / "edition.json"


def test_every_field_edition_of_the_season_is_scored_and_a_bad_one_never_stops_the_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_issue import REVEAL as SELECTION

    world(tmp_path, leagues=MEMBERS)
    assert run_live(tmp_path, CUTOFF + timedelta(minutes=5), monkeypatch) == 0
    reveal(tmp_path)
    with_field(tmp_path)
    earlier_edition(tmp_path, "scw-2026-r01-tminus60-e1")
    earlier_edition(
        tmp_path, "scw-2026-r01-sun0200-e1", reveal_utc=SELECTION.isoformat()
    )  # claims a later reveal
    earlier_edition(tmp_path, "scw-2026-r01-sun0200-e2", teams=[{"team_id": "T01"}, {"oops": 1}])
    broken = earlier_edition(tmp_path, "scw-2026-r01-sun0200-e3")
    broken.write_bytes(broken.read_bytes() + b" ")  # its bytes no longer match the store
    monkeypatch.setattr(scorecard, "past_champions", lambda *a, **k: ({2026: dict(CHAMPIONS)}, {}, []))
    card = build(tmp_path)
    outcome = card["field_outcome"]
    assert outcome["scored"] is True
    assert list(outcome["unreadable"]) == ["scw-2026-r01-sun0200-e3"]
    assert {e["route"] for e in outcome["field"]} >= {"at_large"}
    assert all(e["seed"] for e in outcome["field"])
    by_id = {e["edition_id"]: e for e in outcome["editions"]}
    title_week = by_id["scw-2026-r01-tminus60-e1"]  # issued for the release before: scored here, once
    assert title_week["prospective"] is True
    assert title_week["lead"] == "r01-tminus60"
    assert (
        title_week["integrity"]["passed"] is False
    )  # the hand-made section has no seeds: flagged, not hidden
    low = published_probability(0, PATHS)
    field = set(e["team_id"] for e in outcome["field"])
    order = [
        r["team_id"]
        for r in json.loads(
            (tmp_path / "lake" / "editions" / "scw-2026-r02-sun0200-e1" / "edition.json").read_bytes()
        )["forecasts"]["baseline2"]["rows"]
    ]
    said = set(order[:12])
    expected = sum(((0.6 if t in said else low) - (1.0 if t in field else 0.0)) ** 2 for t in order) / len(
        order
    )
    assert title_week["runs"][0]["scores"]["overall"]["field"]["brier"] == pytest.approx(expected)
    lying = by_id["scw-2026-r01-sun0200-e1"]
    assert lying["prospective"] is False
    assert "differs from the store's release" in " ".join(lying["not_prospective_because"])
    assert by_id["scw-2026-r01-sun0200-e2"]["runs"] is None
    assert by_id["scw-2026-r01-sun0200-e2"]["error"]
    weekly = {e["edition_id"]: e for e in card["editions"]}
    assert weekly["scw-2026-r02-tminus60-e1"]["field"]["outcome"] == "scored: see field_outcome"
    (tmp_path / "data" / "cfp_reveals.csv").unlink()
    with pytest.raises(ScoreRefused, match="schedule"):
        build(tmp_path)


def test_real_routes_count_as_automatic_or_at_large() -> None:
    assert [scorecard._automatic(r) for r in ("auto:sec", "auto:group", "automatic")] == [True] * 3
    assert [scorecard._automatic(r) for r in ("at_large", "top_four", "guarantee", None)] == [False] * 4


def test_eras_without_named_conferences_need_every_champion() -> None:
    leagues = sorted(set(MEMBERS.values()))
    short = {league: CHAMPIONS[league] for league in leagues[:-1]}
    with pytest.raises(ScoreRefused, match=leagues[-1]):
        actual_field(2024, TEAMS[:25], short, eligible={}, conference_of=MEMBERS)
    assert len(actual_field(2024, TEAMS[:25], CHAMPIONS, eligible={}, conference_of=MEMBERS)) == 12
