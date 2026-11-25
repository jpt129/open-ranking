"""Rules engine (P09; BR-2014..BR-2027, BR-SCHED, BR-CONTRACT, BR-FIX, FF-06)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cfp.rules.engine import Entry, RulesError, load_rules, select_field

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "cfp_final_orders.json").read_text()
)
ND = "cfbd-87"
POWER = ("acc", "big-ten", "big-12", "sec")
GROUP = ("american-athletic", "conference-usa", "mid-american", "mountain-west", "pac-12", "sun-belt")


def conferences(season: int) -> dict[str, str]:
    data = FIXTURES[str(season)]
    known = {row["team_id"]: row["conference_id"] for row in data["order"]}
    return known | {row["team_id"]: conf for conf, row in data["champions"].items()}


def league_of(champions: dict[str, str], n: int = 30) -> dict[str, str]:
    """Synthetic membership: each champion in its league, every other team in the SEC."""
    return {f"R{i:02d}": "sec" for i in range(1, n + 1)} | {team: conf for conf, team in champions.items()}


def real(season: int) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """(order of team ids, champions by conference, team id by name) from the official final release."""
    data = FIXTURES[str(season)]
    ids = {row["name"]: row["team_id"] for row in data["order"]}
    champions = {conf: row["team_id"] for conf, row in data["champions"].items()}
    ids |= {row["name"]: row["team_id"] for row in data["champions"].values()}
    return [row["team_id"] for row in data["order"]], champions, ids


def seeds(field: list[Entry]) -> list[str]:
    return [e.team_id for e in sorted((e for e in field if e.qualifier), key=lambda e: e.seed or 0)]


def by_team(field: list[Entry]) -> dict[str, Entry]:
    return {e.team_id: e for e in field}


def test_rules_top_four_2014_2023() -> None:
    expected = {
        2014: ["Alabama", "Oregon", "Florida State", "Ohio State"],
        2015: ["Clemson", "Alabama", "Michigan State", "Oklahoma"],
        2016: ["Alabama", "Clemson", "Ohio State", "Washington"],
        2017: ["Clemson", "Oklahoma", "Georgia", "Alabama"],
        2018: ["Alabama", "Clemson", "Notre Dame", "Oklahoma"],
        2019: ["LSU", "Ohio State", "Clemson", "Oklahoma"],
        2020: ["Alabama", "Clemson", "Ohio State", "Notre Dame"],
        2021: ["Alabama", "Michigan", "Georgia", "Cincinnati"],
        2022: ["Georgia", "Michigan", "TCU", "Ohio State"],
        2023: ["Michigan", "Washington", "Texas", "Alabama"],
    }
    for season, names in expected.items():
        order, champions, ids = real(season)
        field = select_field(load_rules(season), order, champions)
        assert seeds(field) == [ids[n] for n in names], season
        chosen = [e for e in field if e.qualifier]
        assert [(e.seed, e.route, e.bye, e.host_round) for e in chosen] == [
            (s, "top_four", False, None) for s in (1, 2, 3, 4)
        ]
        assert all(not e.qualifier and e.seed is None for e in field if e.team_id not in seeds(field))


def test_rules_2024_official_field() -> None:
    order, champions, ids = real(2024)
    field = select_field(load_rules(2024), order, champions)
    names = [
        "Oregon",
        "Georgia",
        "Boise State",
        "Arizona State",
        "Texas",
        "Penn State",
        "Notre Dame",
        "Ohio State",
    ]
    names += ["Tennessee", "Indiana", "SMU", "Clemson"]
    assert seeds(field) == [ids[n] for n in names]
    got = by_team(field)
    assert [got[ids[n]].bye for n in names] == [True] * 4 + [False] * 8  # byes to the four best champions
    assert [got[ids[n]].host_round for n in names] == [None] * 4 + [1] * 4 + [None] * 4
    assert got[ids["Boise State"]].route == "auto:mountain-west"
    assert got[ids["Clemson"]].route == "auto:acc"  # ranked 16, in as the fifth champion
    assert got[ids["Texas"]].route == "at_large"
    assert not got[ids["Alabama"]].qualifier  # ranked 11, out
    assert "at-large" in got[ids["Alabama"]].reason
    assert not got[ids["Army"]].qualifier  # a champion, but only the sixth-ranked one


def test_rules_2025_official_field() -> None:
    """FF-06: rank, eligibility and seed are three different things."""
    order, champions, ids = real(2025)
    field = select_field(load_rules(2025), order, champions)
    names = ["Indiana", "Ohio State", "Georgia", "Texas Tech", "Oregon", "Ole Miss", "Texas A&M", "Oklahoma"]
    names += ["Alabama", "Miami", "Tulane", "James Madison"]
    assert seeds(field) == [ids[n] for n in names]
    got = by_team(field)
    assert (got[ids["James Madison"]].rank, got[ids["James Madison"]].seed) == (24, 12)
    assert (got[ids["Tulane"]].rank, got[ids["Tulane"]].seed) == (20, 11)
    assert (got[ND].rank, got[ND].qualifier, got[ND].seed) == (11, False, None)
    assert not got[ids["Duke"]].qualifier  # the unranked ACC champion
    assert got[ids["Duke"]].rank is None
    assert [got[ids[n]].bye for n in names] == [True] * 4 + [False] * 8  # the top four ranked teams
    assert got[ids["Ohio State"]].route == "at_large"  # a bye without a title


def test_rules_2026_on_2025_order() -> None:
    order, champions, ids = real(2025)
    field = select_field(
        load_rules(2026), order, champions, extra_order=[ids["Duke"]], conference_of=conferences(2025)
    )
    names = ["Indiana", "Ohio State", "Georgia", "Texas Tech", "Oregon", "Ole Miss", "Texas A&M", "Oklahoma"]
    names += ["Alabama", "Notre Dame", "Tulane", "Duke"]
    assert seeds(field) == [ids[n] for n in names]
    got = by_team(field)
    assert got[ids["Duke"]].route == "auto:acc"
    assert got[ids["Tulane"]].route == "auto:group"
    assert got[ND].route == "guarantee"
    assert not got[ids["Miami"]].qualifier
    assert "Notre Dame" in got[ids["Miami"]].reason or ND in got[ids["Miami"]].reason
    assert not got[ids["James Madison"]].qualifier


def order_of(n: int = 25) -> list[str]:
    return [f"R{i:02d}" for i in range(1, n + 1)]


def champs(**over: str) -> dict[str, str]:
    """Power champions ranked 1-4 and the six-league champions ranked 15-20, unless overridden."""
    base = dict(zip(POWER, ["R01", "R02", "R03", "R04"], strict=True))
    base |= dict(zip(GROUP, ["R15", "R16", "R17", "R18", "R19", "R20"], strict=True))
    return base | over


def pick(rules: Any, order: list[str], champions: dict[str, str], **kw: Any) -> list[Entry]:
    """select_field with the synthetic membership filled in."""
    members = league_of(champions) | {ND: "fbs-independents"} | {t: "sec" for t in order}
    members |= {team: conf for conf, team in champions.items()}
    kw.setdefault("conference_of", members)
    return select_field(rules, order, champions, **kw)


def test_group_place_goes_to_the_highest_ranked_team_not_champion() -> None:
    """2026 and 2027: "the highest-ranked team from the American, Conference USA, ... or Sun Belt"."""
    champions = champs()
    members = league_of(champions) | {"R10": "mountain-west"}  # ranked 10, lost its title game to R18
    for season in (2026, 2027):
        field = by_team(select_field(load_rules(season), order_of(30), champions, conference_of=members))
        assert field["R10"].route == "auto:group"
        assert field["R15"].route == (
            "at_large" if season == 2027 else None
        )  # a champion with no automatic place
    with pytest.raises(RulesError, match="conference_of"):
        select_field(load_rules(2026), order_of(), champions)
    with pytest.raises(RulesError, match="no conference is given for R25"):
        select_field(
            load_rules(2026), order_of(), champions, conference_of={f"R{i:02d}": "sec" for i in range(1, 25)}
        )
    # 2025 rules on the same teams: only champions count, so R15 is in and R10 needs an at-large place
    field = by_team(select_field(load_rules(2025), order_of(), champions, conference_of=members))
    assert (field["R15"].route, field["R10"].route) == ("auto:american-athletic", "at_large")


def test_notre_dame_at_12_and_13() -> None:
    rules = load_rules(2026)
    at_12 = order_of()
    at_12[11] = ND
    field = by_team(pick(rules, at_12, champs()))
    assert (field[ND].qualifier, field[ND].route, field[ND].seed) == (True, "guarantee", 11)
    assert not field["R11"].qualifier  # the last at-large gives way
    assert field["R15"].seed == 12  # the six-league place
    at_13 = order_of()
    at_13[12] = ND
    field = by_team(pick(rules, at_13, champs()))
    assert not field[ND].qualifier
    assert field["R11"].qualifier
    at_5 = order_of()
    at_5[4] = ND
    field = by_team(pick(rules, at_5, champs()))
    assert (field[ND].route, field[ND].seed) == ("at_large", 5)  # in on rank alone; the guarantee is not used
    assert load_rules(2025).guarantee is None


def test_unranked_aq_ordering() -> None:
    rules = load_rules(2026)
    # the ACC champion and every six-league champion are outside the top 25
    unranked = champs(**{"acc": "U-ACC"} | {conf: f"U-{conf}" for conf in GROUP})
    with pytest.raises(RulesError, match="extra committee ordering"):
        pick(rules, order_of(), unranked)
    extra = ["U-sun-belt", "U-ACC", "U-pac-12"]
    field = by_team(pick(rules, order_of(), unranked, extra_order=extra))
    assert (field["U-sun-belt"].route, field["U-sun-belt"].seed) == ("auto:group", 11)
    assert (field["U-ACC"].route, field["U-ACC"].seed) == ("auto:acc", 12)
    assert not field["U-pac-12"].qualifier
    assert field["U-ACC"].rank is None
    assert sum(e.qualifier for e in field.values()) == 12
    with pytest.raises(RulesError, match="ranked and in the extra"):
        pick(rules, order_of(), unranked, extra_order=["R01", *extra])
    # one unranked qualifier needs no ordering
    field = by_team(pick(rules, order_of(), champs(acc="U-ACC")))
    assert field["U-ACC"].seed == 12


def test_rules_2027_byes_and_hosts() -> None:
    rules = load_rules(2027)
    assert load_rules(2031) == load_rules(2027)
    field = pick(rules, order_of(30), champs(**{"mid-american": "R29"}))
    chosen = sorted((e for e in field if e.qualifier), key=lambda e: e.seed or 0)
    assert len(chosen) == 24
    assert [e.seed for e in chosen] == list(range(1, 25))
    assert [e.bye for e in chosen] == [True] * 8 + [False] * 16
    assert [e.host_round for e in chosen] == [2] * 8 + [1] * 8 + [None] * 8
    routes = [e.route for e in chosen]
    assert routes.count("at_large") == 19
    assert sum(r.startswith("auto:") for r in routes) == 5
    assert (
        by_team(field)["R15"].route == "auto:group"
    )  # the highest-ranked of the six, not the lowest champion
    assert not by_team(field)["R29"].qualifier


def test_waiver_flag() -> None:
    rules = load_rules(2027)
    eligible = {"R05": False, "R06": False}
    field = by_team(pick(rules, order_of(30), champs(), eligible=eligible, waivers={"R06"}))
    assert not field["R05"].qualifier
    assert "not eligible" in field["R05"].reason
    assert field["R06"].qualifier
    assert field["R06"].waiver
    assert "waiver" in field["R06"].reason
    assert not field["R07"].waiver
    assert field["R07"].seed == 6  # everyone below the excluded team moves up one


def test_ten_game_count_never_excludes() -> None:
    rules = load_rules(2027)
    plain = pick(rules, order_of(30), champs())
    counted = pick(rules, order_of(30), champs(), qualifying_games={"R05": 8, "R06": 10})
    assert seeds(counted) == seeds(plain)  # a raw count alone cannot exclude a team
    field = by_team(counted)
    assert field["R05"].qualifier
    assert "8 qualifying games" in field["R05"].reason
    assert field["R05"].below_schedule_standard
    assert not field["R06"].below_schedule_standard


def test_field_output_contract() -> None:
    order, champions, _ = real(2025)
    field = pick(load_rules(2025), order, champions)
    assert {e.team_id for e in field} == set(order) | set(champions.values())  # every team it was told about
    for e in field:
        assert isinstance(e, Entry)
        assert e.reason
        assert e.qualifier == (e.seed is not None) == (e.route is not None)
        assert e.bye in (True, False)
        assert not (e.bye and not e.qualifier)
    assert len({e.seed for e in field if e.qualifier}) == 12
    again = pick(load_rules(2025), order, dict(reversed(list(champions.items()))))
    assert again == field  # the order of the champions mapping does not matter
    with pytest.raises(RulesError, match="twice"):
        pick(load_rules(2025), [*order, order[0]], champions)
    with pytest.raises(RulesError, match="champion"):
        pick(load_rules(2026), order_of(), {k: v for k, v in champs().items() if k != "sec"})
    with pytest.raises(RulesError, match="no rules"):
        load_rules(2013)


def test_seed_boundaries() -> None:
    cases: list[tuple[int, int, dict[str, Any]]] = [
        (2019, 4, {}),
        (2024, 12, {}),
        (2025, 12, {}),
        (2026, 12, {}),
    ]
    for season, size, _ in cases:
        rules = load_rules(season)
        field = by_team(pick(rules, order_of(), champs()))
        chosen = sorted((e for e in field.values() if e.qualifier), key=lambda e: e.seed or 0)
        assert len(chosen) == size == rules.field_size
        byes = [e.team_id for e in chosen if e.bye]
        hosts = [e.team_id for e in chosen if e.host_round == 1]
        if size == 4:
            assert (byes, hosts) == ([], [])
            assert [e.team_id for e in chosen] == ["R01", "R02", "R03", "R04"]
            assert not field["R05"].qualifier
        else:
            assert byes == ["R01", "R02", "R03", "R04"]
            assert hosts == [e.team_id for e in chosen[4:8]]
            # the last at-large and the first team out sit on either side of the cutoff
            assert field["R11"].qualifier
            assert not field["R12"].qualifier
            assert chosen[-1].team_id == "R15"  # the automatic bid from below the cutoff takes the last seed
    # 2024 only: a bye needs a title. Champions ranked 1, 2, 6 and 9 take seeds 1-4.
    moved = champs(**{"big-12": "R06", "sec": "R09"})
    field = by_team(pick(load_rules(2024), order_of(), moved))
    assert [field[t].seed for t in ("R01", "R02", "R06", "R09")] == [1, 2, 3, 4]
    assert [field[t].seed for t in ("R03", "R04", "R05")] == [5, 6, 7]
    assert not field["R03"].bye
    # 2025 with the same champions: straight seeding
    field = by_team(pick(load_rules(2025), order_of(), moved))
    assert [field[t].seed for t in ("R01", "R02", "R03", "R04", "R06", "R09")] == [1, 2, 3, 4, 6, 9]


def test_2027_cutoffs_and_open_items() -> None:
    rules = load_rules(2027)
    field = by_team(pick(rules, order_of(30), champs()))
    assert (field["R24"].qualifier, field["R24"].seed) == (True, 24)
    assert not field["R25"].qualifier  # the 24/25 cutoff
    assert (field["R08"].bye, field["R08"].host_round) == (True, 2)
    assert (field["R09"].bye, field["R09"].host_round) == (False, 1)
    assert (field["R16"].host_round, field["R17"].host_round) == (1, None)
    assert any("names its champion" in item for item in rules.unpublished)  # S-l: the freeze waits on this
    assert load_rules(2026).unpublished == ()
    assert rules.fcs_wins_given_weight == 1
    assert dict(rules.qualifying_games).keys() == {"power", "group"}
    assert len(load_rules(2026).sources) == 2


def test_the_engine_refuses_what_the_rules_do_not_cover() -> None:
    rules = load_rules(2026)
    with pytest.raises(RulesError, match="not eligible"):
        pick(rules, order_of(), champs(), eligible={"R01": False})  # an ineligible named champion
    with pytest.raises(RulesError, match="two conferences"):
        pick(rules, order_of(), champs(acc="R01", sec="R01"))
    with pytest.raises(RulesError, match="5 champions qualify"):
        pick(load_rules(2025), order_of(), {"sec": "R01", "acc": "R02"})
    # no group team is ranked and only one champion is known: the committee names the team, not the engine
    lone = {conf: team for conf, team in champs().items() if conf in POWER} | {"sun-belt": "U-sb"}
    with pytest.raises(RulesError, match="extra committee ordering"):
        pick(rules, order_of(), lone)
    assert by_team(pick(rules, order_of(), lone, extra_order=["U-sb"]))["U-sb"].seed == 12
    # a waiver given to a team that was eligible anyway is not flagged
    field = by_team(pick(load_rules(2027), order_of(30), champs(), waivers={"R05"}))
    assert not field["R05"].waiver
    assert "waiver" not in field["R05"].reason
    old = by_team(pick(load_rules(2019), order_of(), champs()))
    assert old["R05"].reason == "ranked 5, outside the top four"


def test_season_files_are_strict() -> None:
    from cfp.rules.engine import _parse

    good = {"seasons": {"first": 2030, "last": 2030}, "field_size": 4, "auto": [], "seeding": "rank"}
    good |= {"byes": [], "hosts": {}, "source": "https://example.test"}
    assert _parse(good).field_size == 4
    with pytest.raises(RulesError, match="unknown key"):
        _parse(good | {"guarentee": {}})
