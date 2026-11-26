"""Committee Gap arithmetic (CG-01 to CG-04). Pure functions: no store, no clock.

Lift = open rank - actual committee rank. Positive means the committee ranked the team higher.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from cfp.forecast.final_field import FieldError, Setup, field_today
from cfp.rules.engine import SeasonRules

RANKED: Final = 25
OUTSIDE: Final = "outside 25"
DECISIVE: Final = 3


def lift(open_rank: int, actual_rank: int | None) -> dict[str, Any]:
    """Lift, or a bound on it when the committee left the team out (it is 26th or lower)."""
    if actual_rank is None:
        return {"lift": None, "bound": f"at most {open_rank - (RANKED + 1)}"}
    return {"lift": open_rank - actual_rank, "bound": None}


def interval80(counts: Sequence[int], paths: int) -> list[Any]:
    """The forecast's central 80% rank interval: at most a tenth of the paths lie beyond each end."""
    if len(counts) != RANKED + 1 or sum(counts) != paths or paths < 1:
        raise ValueError(f"the rank counts do not cover {paths} paths over {RANKED} ranks and outside")
    below, low = 0, RANKED + 1
    for rank in range(1, RANKED + 2):  # the largest rank with at most a tenth of the paths better than it
        if 10 * below <= paths:
            low = rank
        below += counts[rank - 1]
    above, high = 0, 1
    for rank in range(RANKED + 1, 0, -1):  # the smallest rank with at most a tenth of the paths worse
        if 10 * above <= paths:
            high = rank
        above += counts[rank - 1]
    return [OUTSIDE if end > RANKED else end for end in (low, high)]


def team_rows(
    open_ranks: Mapping[str, int], forecast: Mapping[str, Mapping[str, Any]], actual: Sequence[str]
) -> list[dict[str, Any]]:
    """One row for every team in either top 25, in the committee's order and then the Open Ranking's."""
    place = {team: rank for rank, team in enumerate(actual, start=1)}
    for team in actual:
        if team not in open_ranks:
            raise ValueError(f"{team} is ranked by the committee but is not in the Open Ranking edition")
    teams = sorted(
        {t for t, rank in open_ranks.items() if rank <= RANKED} | set(actual),
        key=lambda t: (place.get(t, RANKED + 1), open_ranks[t], t),
    )
    rows = []
    for team in teams:
        mine = lift(open_ranks[team], place.get(team))
        said = forecast.get(team)
        median = said["median"] if said else None
        row: dict[str, Any] = {
            "team_id": team,
            "open_rank": open_ranks[team],
            "forecast_median": median,
            "forecast_interval80": None,
            "actual_rank": place.get(team, OUTSIDE),
            "lift": mine["lift"],
            "lift_bound": mine["bound"],
            "anticipated": None,
            "beyond_forecast": None,
            "p_this_high_or_higher": None,
        }
        if said and said.get("rank_counts") is not None:
            row["forecast_interval80"] = interval80(said["rank_counts"], said["paths"])
            if team in place:
                row["p_this_high_or_higher"] = sum(said["rank_counts"][: place[team]]) / said["paths"]
        if isinstance(median, int) and not isinstance(median, bool):
            row["anticipated"] = open_ranks[team] - median  # the part of the lift the forecast expected
            if team in place:
                row["beyond_forecast"] = median - place[team]  # places above the forecast's median
        rows.append(row)
    return rows


def consequences(
    rules: SeasonRules,
    open_order: Sequence[str],
    committee: Sequence[str],
    *,
    members: Mapping[str, str],
    eligible: Mapping[str, bool],
    champions: Mapping[str, str],
    final: bool,
) -> dict[str, Any]:
    """Every change to a bid, a bye or a home game between the two orders under the same rules (CG-02).

    Before Selection Day the result is provisional: a conference with no champion yet is represented by its
    best-placed team in each order. Teams the committee did not rank follow its 25 in Open Ranking order,
    because the committee publishes no order below 25. If a team from that borrowed tail reaches the
    committee's field (an unranked champion, or the group place), the result is not final and says so: that
    place is the same team in both orders by construction and can never be flagged.
    """
    if final:
        missing = [c for c in rules.named if c not in champions]
        if missing:
            raise ValueError(
                f"Selection Day flags need every champion; none on file for {', '.join(missing)}"
            )
    ranked = set(committee)
    orders = {
        "open": list(open_order),
        "committee": [*committee, *[t for t in open_order if t not in ranked]],
    }
    fields: dict[str, dict[str, Any]] = {}
    stand_ins: dict[str, dict[str, str]] = {}
    for name, order in orders.items():
        setup = Setup(rules.first_season, order, members, eligible, {}, {}, dict(champions), {}, frozenset())
        try:
            today = field_today(setup, rules)
        except FieldError as error:
            raise ValueError(f"the {name} order cannot be run through the rules: {error}") from error
        fields[name] = {e.team_id: e for e in today.entries if e.qualifier}
        stand_ins[name] = dict(sorted(today.stand_ins.items()))
    flags = []
    place = {team: k for k, team in enumerate(open_order)}
    for team in sorted(
        set(fields["open"]) | set(fields["committee"]), key=lambda t: place.get(t, len(place))
    ):
        ours, theirs = fields["open"].get(team), fields["committee"].get(team)
        states = {
            "bid": (ours is not None, theirs is not None),
            "bye": (bool(ours and ours.bye), bool(theirs and theirs.bye)),
            "host": (
                bool(ours and ours.host_round is not None),
                bool(theirs and theirs.host_round is not None),
            ),
        }
        for change, (was, now) in states.items():
            if was != now:
                flags.append(
                    {
                        "team_id": team,
                        "change": change,
                        "open": was,
                        "committee": now,
                        "open_seed": ours.seed if ours else None,
                        "committee_seed": theirs.seed if theirs else None,
                    }
                )
    borrowed = sorted(t for t in fields["committee"] if t not in ranked)
    standing = bool(stand_ins["open"] or stand_ins["committee"])
    notes = []
    if final and not standing and not borrowed:
        notes.append("Final: both orders are run with the conference champions on file.")
    if not final or standing:
        notes.append(
            "Provisional: where a title is not decided, the conference's best-placed team in each order "
            "stands in for its champion. That is an assumption, not a forecast."
        )
    if borrowed:
        notes.append(
            "Not final: the committee's field includes a team it did not rank. The committee publishes no "
            "order below 25, so that team is placed by the Open Ranking's order and cannot be flagged."
        )
    return {
        "provisional": not final or standing or bool(borrowed),
        "committee_tail": "teams the committee did not rank follow its 25 in Open Ranking order",
        "committee_field_from_tail": borrowed,
        "scenario": {"open": stand_ins["open"], "committee": stand_ins["committee"], "note": " ".join(notes)},
        "field": {name: sorted(found, key=lambda t: found[t].seed or 0) for name, found in fields.items()},
        "flags": flags,
    }


def _games(team: Mapping[str, Any], names: Mapping[str, str]) -> list[dict[str, Any]]:
    biggest = sorted(team["rows"], key=lambda row: (-abs(row["points_cp"]), row["game_id"]))[:DECISIVE]
    return [
        {
            "opponent": names.get(row["opponent_id"], row["opponent_id"]),
            "result": row["result"],
            "points_cp": row["points_cp"],
        }
        for row in biggest
    ]


def reasons(
    team: str,
    other: str,
    teams: Mapping[str, Mapping[str, Any]],
    names: Mapping[str, str],
    *,
    remarks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """What the Open Ranking's ledger says about two teams on either side of a cutoff (CG-03)."""
    a, b = teams[team], teams[other]
    wins = {team: 0, other: 0}
    for mine, theirs in ((a, other), (b, team)):
        for row in mine["rows"]:
            if row["opponent_id"] == theirs:
                winner = mine["team_id"] if row["result"] == "W" else theirs
                wins[winner] += 1
    played = (wins[team] + wins[other]) // (2 if _both_list(a, b, team, other) else 1)
    if _both_list(a, b, team, other):
        wins = {k: v // 2 for k, v in wins.items()}
    lead = team if wins[team] >= wins[other] else other
    trail = other if lead == team else team
    label = "tied" if wins[lead] == wins[trail] else names.get(lead, lead)
    return {
        "pair": [team, other],
        "ledger_difference_cp": a["total_cp"] - b["total_cp"],
        "decisive_games": {team: _games(a, names), other: _games(b, names)},
        "decisive_rule": f"each team's {DECISIVE} largest ledger rows by size; a display rule, not a finding",
        "head_to_head": {
            "met": played > 0,
            "series": f"{label} {wins[lead]}-{wins[trail]}" if played else None,
            "treatment": {team: a.get("head_to_head"), other: b.get("head_to_head")},
        },
        "cross_league_sensitivity": "not delivered in the pilot",
        "chair": list(remarks) if remarks else "no dated public explanation is on file for this release",
        "inference": "none added",
    }


def _both_list(a: Mapping[str, Any], b: Mapping[str, Any], team: str, other: str) -> bool:
    """True if each ledger lists the meeting, so each game would be counted twice."""
    return any(r["opponent_id"] == other for r in a["rows"]) and any(
        r["opponent_id"] == team for r in b["rows"]
    )


def aggregate(rows: Sequence[Mapping[str, Any]], members: Mapping[str, str]) -> dict[str, Any]:
    """Shared-list mean lift and its coverage, who is on one list only, and lift by conference (CG-04)."""
    shared = [r for r in rows if r["lift"] is not None and r["open_rank"] <= RANKED]
    committee = [r for r in rows if r["actual_rank"] != OUTSIDE]
    by: dict[str, list[int]] = {}
    for row in shared:
        by.setdefault(members.get(row["team_id"]) or "none", []).append(row["lift"])
    return {
        "shared": len(shared),
        "coverage": len(shared) / len(committee) if committee else None,
        "mean_lift_shared": sum(r["lift"] for r in shared) / len(shared) if shared else None,
        "mean_abs_lift_shared": sum(abs(r["lift"]) for r in shared) / len(shared) if shared else None,
        "committee_only": [r["team_id"] for r in committee if r["open_rank"] > RANKED],
        "open_only": [r["team_id"] for r in rows if r["actual_rank"] == OUTSIDE],
        "bounded": {r["team_id"]: r["lift_bound"] for r in rows if r["actual_rank"] == OUTSIDE},
        "by_conference": {
            league: {"shared": len(found), "mean_lift": sum(found) / len(found)}
            for league, found in sorted(by.items())
        },
        "variability": "one release is one observation; variability by season block is not estimated here",
        "labels_removed": "not delivered in the pilot",
    }
