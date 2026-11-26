"""Forward-chained replay of past seasons (VT-10).

2014-16 is the first training window. Each later season is forecast by a model fitted on earlier seasons
only, and scored with the weekly rank score. Every sample seed is derived from a recorded label.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from cfp.common.hashing import sha256_hex
from cfp.forecast.final_field import BASELINE, Model, Setup, run
from cfp.forecast.noise_params import Example
from cfp.forecast.promotion import Scores, decide
from cfp.forecast.rank_noise import fit_temperature, published_probability, rank_frequencies, sample_orders
from cfp.forecast.simulator import simulate
from cfp.rules.engine import load_rules, select_field
from cfp.scoring.field import FieldRow, bubble_cohort, field_scores
from cfp.scoring.weekly import RANKED, cumulative_from_counts, score_weekly

FIRST_WINDOW: Final = (2014, 2015, 2016)
PATHS: Final = 10_000


def expanding_folds(seasons: Iterable[int]) -> list[tuple[tuple[int, ...], int]]:
    """(training seasons, held-out season) pairs: train on everything earlier, starting from 2014-16."""
    found = sorted(set(seasons))
    missing = [s for s in FIRST_WINDOW if s not in found]
    if missing:
        raise ValueError(f"the first training window is 2014-2016 and {missing} is missing")
    return [(tuple(s for s in found if s < held), held) for held in found if held > FIRST_WINDOW[-1]]


@dataclass(frozen=True)
class LossDrop:
    """Baseline 2 with a set number of places dropped per loss, and a temperature fitted per cutoff."""

    name: str
    drop: float
    kind: str = "weekly"

    def order(self, example: Example) -> list[str]:
        keyed = sorted(
            (place + 1 + self.drop * example.losses.get(team, 0), place, team)
            for place, team in enumerate(example.initial)
        )
        return [team for _, _, team in keyed]

    def fit(self, train: Sequence[Example]) -> dict[str, float]:
        """Temperature per cutoff, from the training seasons' releases of this kind."""
        taus: dict[str, float] = {}
        for issue in sorted({e.issue for e in train}):
            pairs = [(self.order(e), e.actual) for e in train if e.issue == issue and e.kind == self.kind]
            if pairs:
                taus[issue] = fit_temperature(pairs).tau
        return taus


@dataclass(frozen=True)
class AsIssued:
    """Baseline 1: the AP order as issued, with a temperature fitted per cutoff."""

    name: str = "baseline1"
    kind: str = "weekly"
    drop: float | None = None

    def order(self, example: Example) -> list[str]:
        return list(example.baseline1)

    def fit(self, train: Sequence[Example]) -> dict[str, float]:
        taus: dict[str, float] = {}
        for issue in sorted({e.issue for e in train}):
            pairs = [(self.order(e), e.actual) for e in train if e.issue == issue and e.kind == self.kind]
            if pairs:
                taus[issue] = fit_temperature(pairs).tau
        return taus


def _seed(example: Example, paths: int) -> int:
    """One seed per release, cutoff and path count: every model is scored on the same noise draws."""
    label = f"replay|{example.season}|{example.release_no}|{example.issue}|{paths}"
    return int(sha256_hex(label.encode())[:12], 16)


def _mean(values: Sequence[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return sum(kept) / len(kept) if kept else None


def replay_weekly(
    examples: Sequence[Example], model: LossDrop | AsIssued, *, paths: int = PATHS
) -> dict[str, Any]:
    """The model's held-out rank score on releases of its kind, by season. The mean is over releases."""
    mine = [e for e in examples if e.kind == model.kind]
    earlier = {(e.season, e.release_no): list(e.actual) for e in examples}
    seasons: dict[str, Any] = {}
    every: list[float] = []
    secondary: list[float] = []
    for train_seasons, held in expanding_folds(e.season for e in mine):
        inside = set(train_seasons)
        taus = model.fit([e for e in mine if e.season in inside])
        cards = []
        for e in sorted((e for e in mine if e.season == held), key=lambda e: (e.release_no, e.issue)):
            if e.issue not in taus:
                raise ValueError(f"no earlier {e.issue} release to fit on before {held}")
            order = model.order(e)
            seed = _seed(e, paths)
            counts = rank_frequencies(sample_orders(len(order), taus[e.issue], paths, seed=seed), RANKED)
            forecast = {
                team: cumulative_from_counts([int(c) for c in counts[place]], paths)
                for place, team in enumerate(order)
            }
            prior = earlier.get((e.season, e.release_no - 1))
            card = score_weekly(model.name, order, forecast, list(e.actual), order, prior=prior)
            moved = card["movement"]
            cards.append(
                {
                    "release_no": e.release_no,
                    "issue": e.issue,
                    "seed": seed,
                    "score": card["score"],
                    "secondary": card["secondary"]["score"],
                    "exact_slots": card["exact_slots"],
                    "rank_error": card["rank_error"]["mean_abs_error"],
                    "coverage": card["rank_error"]["coverage"],
                    "entrants": len(moved["entrants"]) if moved else None,
                    "entrants_called": len(moved["entrants_called"]) if moved else None,
                    "exits": len(moved["exits"]) if moved else None,
                    "exits_called": len(moved["exits_called"]) if moved else None,
                }
            )
        scores = [c["score"] for c in cards]
        every.extend(scores)
        secondary.extend(c["secondary"] for c in cards)
        seasons[str(held)] = {
            "trained_on": list(train_seasons),
            "tau": taus,
            "releases": len(cards),
            "score": sum(scores) / len(scores),
            "cards": cards,
        }
    if not every:
        raise ValueError("no season after 2016 to score")
    return {
        "model": model.name,
        "drop": model.drop,
        "kind": model.kind,
        "paths": paths,
        "releases": len(every),
        "score": sum(every) / len(every),
        "secondary": sum(secondary) / len(secondary),
        "exact_slots": _mean([c["exact_slots"] for s in seasons.values() for c in s["cards"]]),
        "rank_error": _mean([c["rank_error"] for s in seasons.values() for c in s["cards"]]),
        "coverage": _mean([c["coverage"] for s in seasons.values() for c in s["cards"]]),
        "entrants": sum(c["entrants"] or 0 for s in seasons.values() for c in s["cards"]),
        "entrants_called": sum(c["entrants_called"] or 0 for s in seasons.values() for c in s["cards"]),
        "exits": sum(c["exits"] or 0 for s in seasons.values() for c in s["cards"]),
        "exits_called": sum(c["exits_called"] or 0 for s in seasons.values() for c in s["cards"]),
        "seasons": seasons,
    }


# --- Selection Day: field probabilities under candidate title-week models -------------------------------

DROP_GRID: Final = tuple(x / 2 for x in range(21))  # 0 to 10 places per loss, in halves
SHRINK: Final = 10  # title-week losses' worth of weight given to the regular-week drop
POPULATION: Final = 60  # places of the starting order scored for each Selection Day


def _fit_drop(examples: Sequence[Example], drop: float | None = None) -> tuple[float, float]:
    """(drop, temperature). With no drop given, the grid value that makes the releases most likely."""
    if drop is None:
        drop = max(
            (fit_temperature([(LossDrop("", d).order(e), e.actual) for e in examples]).log_likelihood, d)
            for d in DROP_GRID
        )[1]
    return drop, fit_temperature([(LossDrop("", drop).order(e), e.actual) for e in examples]).tau


def pilot_models(train_final: Sequence[Example], train_weekly: Sequence[Example]) -> list[Model]:
    """The baseline and the two title-week candidates the pilot plan named, fitted on earlier seasons only."""
    _, tau_base = _fit_drop(train_final, BASELINE.drop_title)
    drop_title, tau_title = _fit_drop(train_final)
    drop_weekly, _ = _fit_drop(train_weekly)
    losses = sum(sum(e.losses.get(team, 0) for team in e.initial[:RANKED]) for e in train_final)
    weight = losses / (losses + SHRINK)
    drop_shrunk = round((weight * drop_title + (1 - weight) * drop_weekly) * 2) / 2
    _, tau_shrunk = _fit_drop(train_final, drop_shrunk)
    return [
        BASELINE.with_tau(tau_base),
        Model("pilot_unshrunk", drop_weekly, drop_title, tau_title),
        Model("pilot_shrunk", drop_weekly, drop_shrunk, tau_shrunk),
    ]


def _route(route: str | None) -> str | None:
    if route is None:
        return None
    return "automatic" if route.startswith("auto") else "at_large"


def _label_seed(label: str) -> int:
    return int(sha256_hex(label.encode())[:12], 16)


def replay_final(
    finals: Sequence[Example],
    weekly: Sequence[Example],
    *,
    champions: Mapping[int, Mapping[str, str]],
    conference_of: Mapping[int, Mapping[str, str]],
    paths: int = PATHS,
    make: Callable[[Sequence[Example], Sequence[Example]], list[Model]] = pilot_models,
) -> dict[str, Any]:
    """Held-out field scores on each Selection Day after 2016, and what the promotion rule says of each model.

    `finals` and `weekly` are one cutoff's examples. With every game played, a path differs only in the
    committee's order. The bubble cohort is the baseline's, and every model is scored on the same teams.
    """
    by_season = {e.season: e for e in finals if e.kind == "final"}
    if len(by_season) != sum(1 for e in finals if e.kind == "final"):
        raise ValueError("more than one Selection Day example for a season: pass one cutoff")
    rows: dict[str, list[FieldRow]] = {}
    seasons: dict[str, Any] = {}
    for train_seasons, held in expanding_folds(by_season):
        if held not in conference_of:
            raise ValueError(f"no conference membership for {held}")
        example = by_season[held]
        models = make(
            [by_season[s] for s in train_seasons],
            [e for e in weekly if e.kind == "weekly" and e.season < held],
        )
        rules = load_rules(held)
        leagues = conference_of[held]
        won = dict(champions.get(held, {}))
        grouped = leagues if rules.group_of == "team" and rules.group else None
        actual = {
            e.team_id: e
            for e in select_field(rules, list(example.actual), won, conference_of=grouped)
            if e.qualifier
        }
        base_order = LossDrop("", BASELINE.drop_title).order(example)
        projected = select_field(
            rules, base_order[:RANKED], won, conference_of=grouped, extra_order=base_order[RANKED:]
        )
        last = max(
            base_order.index(e.team_id) for e in projected if e.qualifier and _route(e.route) == "at_large"
        )
        cohort = bubble_cohort(base_order, base_order[last])
        setup = Setup(
            held, list(example.initial), leagues, {}, {}, dict(example.losses), won, {}, frozenset()
        )
        tag = f"{held}|{example.issue}|{paths}"  # no model name: every model sees the same draws
        drawn = simulate([], paths, a=0.0, seed=_label_seed(f"replay-final|paths|{tag}"))
        era = f"{rules.field_size}-team, {rules.seeding} seeding"
        fold: dict[str, Any] = {}
        for model in models:
            result = run(setup, drawn, rules, model, seed=_label_seed(f"replay-final|order|{tag}"))
            for team in example.initial[:POPULATION]:
                routes = result.routes.get(team, {})
                auto = sum(count for route, count in routes.items() if _route(route) == "automatic")
                entry = actual.get(team)
                rows.setdefault(model.name, []).append(
                    FieldRow(
                        held,
                        example.issue,
                        era,
                        team,
                        published_probability(result.field.get(team, 0), paths),
                        published_probability(result.bye.get(team, 0), paths),
                        entry is not None,
                        bool(entry and entry.bye),
                        published_probability(auto, paths),
                        published_probability(result.field.get(team, 0) - auto, paths),
                        _route(entry.route) if entry else None,
                        team in cohort,
                    )
                )
            fold[model.name] = {
                "drop_regular": model.drop_regular,
                "drop_title": model.drop_title,
                "tau": model.tau,
                "order_seed": result.order_seed,
            }
        seasons[str(held)] = {
            "trained_on": list(train_seasons),
            "field": sorted(actual),
            "bubble": sorted(cohort),
            "paths_seed": _label_seed(f"replay-final|paths|{tag}"),
            "models": fold,
        }
    if not rows:
        raise ValueError("no Selection Day after 2016 to score")
    summary: dict[str, Any] = {}
    for name, found in rows.items():
        scored = field_scores(found)
        overall, bubble = scored["overall"]["field"], scored["by"]["bubble"].get("bubble")
        summary[name] = {
            "n": overall["n"],
            "log_loss": overall["log_loss"],
            "log_loss_sum": overall["log_loss"] * overall["n"],
            "brier": overall["brier"],
            "bubble_n": bubble["field"]["n"] if bubble else 0,
            "bubble_brier": bubble["field"]["brier"] if bubble else None,
            "by_season": {
                s: v["field"]["log_loss"] * v["field"]["n"] for s, v in scored["by"]["season"].items()
            },
            "bye": scored["overall"]["bye"],
            "by_era": scored["by"]["era"],
            "by_route": scored["by"]["route"],
            "by_lead": scored["by"]["lead"],
        }
    base = summary[BASELINE.name]
    decisions: dict[str, Any] = {}
    for name, got in summary.items():
        if name == BASELINE.name:
            continue
        ruling = decide(
            Scores(base["log_loss"], base["bubble_brier"]),
            Scores(got["log_loss"], got["bubble_brier"]),
            seasons=len(seasons),
        )
        change = None
        if base["bubble_brier"] is not None and got["bubble_brier"] is not None:
            change = got["bubble_brier"] - base["bubble_brier"]
        decisions[name] = {
            "promote": ruling.promote,
            "reason": ruling.reason,
            "seasons": len(seasons),
            "bubble_brier_change": change,
        }
    return {
        "held_out": [int(s) for s in seasons],
        "paths": paths,
        "population": POPULATION,
        "models": summary,
        "decisions": decisions,
        "seasons": seasons,
    }
