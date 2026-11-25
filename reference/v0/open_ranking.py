"""Open Ranking v0 - reference implementation of a transparent CFP points system.

Every game earns or costs points equal to how much better or worse a team did than
a bubble-level playoff team would have been expected to do against the same opponent
at the same site:

    points = 100 * (won - P(bubble team beats this opponent here))

Three design rules are enforced by construction and checked in test_open_ranking.py:

  1. Only the result earns points. Scoring margin is used solely to grade opponents.
  2. Your opponents are graded without you: each team's ledger is computed from a
     strength model fitted on every game EXCEPT that team's own games, so nothing a
     team does on the field (other than win or lose) can change its own points.
  3. No preseason inputs and no game dates: the same set of results always gives
     the same ranking, whatever order the games were played in.

Inputs are final scores only. Constants marked FROZEN are meant to be estimated once
from past seasons and locked before a season starts; the DIALS are value judgments a
governing body sets in public before the season.

Quick start:

    games = [Game("Home U", "Away State", 31, 17), ...]      # every game, FCS included
    conf_of = {"Home U": "League A", "Away State": "League B", ...}
    fbs = {"Home U", "Away State", ...}                      # teams eligible to be ranked
    for sheet in rank(games, conf_of, fbs)[:24]:
        print(sheet.team, round(sheet.points), [round(l.points) for l in sheet.lines])

Status: v0. Tested on a simulated league only (python3 test_open_ranking.py); the
frozen constants below are placeholders until they are fitted to real seasons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.stats import norm


@dataclass(frozen=True)
class Game:
    home: str
    away: str
    home_pts: int
    away_pts: int
    neutral: bool = False
    title_game: bool = False  # conference championship game


@dataclass(frozen=True)
class Dials:
    """Value judgments, set in public before the season."""
    margin_cap: float = 24.0             # blowouts beyond this add no information
    bubble_band: tuple[int, int] = (21, 28)  # ranks that define the bubble team
    h2h_window: float = 25.0             # head-to-head decides inside this gap (points)
    title_loss_weight: float = 0.5       # share of a title-game loss that counts
    fcs_wins_count: bool = False         # 2027 rule: wins over FCS teams earn nothing


@dataclass(frozen=True)
class Frozen:
    """Constants estimated from past seasons and locked before kickoff."""
    tau_team: float = 9.0    # spread of teams around their conference (points)
    tau_conf: float = 6.0    # spread of conference strength (points)
    sigma: float = 13.0      # noise of a capped game margin (points)
    sigma_wp: float = 16.0   # converts a rating gap into a win probability


class Strength:
    """Ridge regression of capped margins on team, conference and home field."""

    def __init__(self, games: Iterable[Game], conf_of: dict[str, str],
                 dials: Dials, frozen: Frozen, exclude: str | None = None):
        self.teams = sorted(conf_of)
        self.confs = sorted(set(conf_of.values()))
        ti = {t: i for i, t in enumerate(self.teams)}
        ci = {c: len(ti) + i for i, c in enumerate(self.confs)}
        k = len(ti) + len(ci) + 1
        games = sorted((g for g in games if exclude not in (g.home, g.away)),
                       key=lambda g: (g.home, g.away, g.title_game))
        X = np.zeros((len(games), k))
        y = np.zeros(len(games))
        for r, g in enumerate(games):
            X[r, ti[g.home]] += 1.0
            X[r, ti[g.away]] -= 1.0
            X[r, ci[conf_of[g.home]]] += 1.0
            X[r, ci[conf_of[g.away]]] -= 1.0
            X[r, -1] = 0.0 if g.neutral else 1.0
            y[r] = float(np.clip(g.home_pts - g.away_pts, -dials.margin_cap, dials.margin_cap))
        pen = np.concatenate([
            np.full(len(ti), (frozen.sigma / frozen.tau_team) ** 2),
            np.full(len(ci), (frozen.sigma / frozen.tau_conf) ** 2),
            [1e-9],
        ])
        A = X.T @ X + np.diag(pen)
        self.cov = frozen.sigma ** 2 * np.linalg.inv(A)   # posterior covariance
        self.beta = self.cov @ (X.T @ y) / frozen.sigma ** 2
        self._ti, self._ci, self._conf_of = ti, ci, conf_of
        self.hfa = float(self.beta[-1])

    def rating(self, team: str) -> float:
        return float(self.beta[self._ti[team]] + self.beta[self._ci[self._conf_of[team]]])

    def loading(self, team: str) -> np.ndarray:
        """Row vector v with rating(team) = v @ beta (used for error bars)."""
        v = np.zeros(len(self.beta))
        v[self._ti[team]] = 1.0
        v[self._ci[self._conf_of[team]]] = 1.0
        return v


@dataclass
class LedgerLine:
    opponent: str
    site: str          # 'home', 'road' or 'neutral'
    won: bool
    p_bubble: float    # chance the bubble team wins this game
    points: float


@dataclass
class TeamSheet:
    team: str
    points: float
    stderr: float              # from uncertainty in opponent grades only
    wins: int
    losses: int
    lines: list[LedgerLine]


def team_sheet(team: str, games: list[Game], conf_of: dict[str, str], fbs: set[str],
               dials: Dials, frozen: Frozen) -> TeamSheet:
    """Ledger for one team, with opponents graded on games the team did not play in."""
    model = Strength(games, conf_of, dials, frozen, exclude=team)
    others = sorted((t for t in fbs if t != team), key=model.rating, reverse=True)
    lo, hi = dials.bubble_band
    band = others[lo - 1:hi]
    bubble = float(np.mean([model.rating(t) for t in band]))
    band_loading = np.mean([model.loading(t) for t in band], axis=0)

    lines, grad, total, wins, losses = [], np.zeros(len(model.beta)), 0.0, 0, 0
    mine = sorted((g for g in games if team in (g.home, g.away)),
                  key=lambda g: (g.title_game, g.home, g.away, g.home_pts, g.away_pts))
    for g in mine:
        is_home = g.home == team
        opp = g.away if is_home else g.home
        site = 0.0 if g.neutral else (1.0 if is_home else -1.0)
        won = (g.home_pts > g.away_pts) == is_home
        z = (bubble - model.rating(opp) + model.hfa * site) / frozen.sigma_wp
        p = float(norm.cdf(z))
        weight = 1.0
        if won and opp not in fbs and not dials.fcs_wins_count:
            weight = 0.0
        if not won and g.title_game:
            weight = dials.title_loss_weight
        pts = 100.0 * weight * ((1.0 if won else 0.0) - p)
        # d(points)/d(beta): points fall as p rises; p depends on bubble, opponent, hfa
        dz = band_loading - model.loading(opp)
        dz[-1] += site
        grad += -100.0 * weight * norm.pdf(z) / frozen.sigma_wp * dz
        total += pts
        wins += won
        losses += not won
        lines.append(LedgerLine(opp, "neutral" if g.neutral else ("home" if is_home else "road"),
                                won, p, pts))
    stderr = float(np.sqrt(max(grad @ model.cov @ grad, 0.0)))
    return TeamSheet(team, total, stderr, wins, losses, lines)


def rank(games: list[Game], conf_of: dict[str, str], fbs: set[str],
         dials: Dials = Dials(), frozen: Frozen = Frozen()) -> list[TeamSheet]:
    """The Open Ranking: points order, then head-to-head inside the window."""
    sheets = [team_sheet(t, games, conf_of, fbs, dials, frozen) for t in sorted(fbs)]
    sheets.sort(key=lambda s: (-s.points, s.team))

    net: dict[tuple[str, str], int] = {}      # net head-to-head wins of a over b
    for g in games:
        w, l = (g.home, g.away) if g.home_pts > g.away_pts else (g.away, g.home)
        net[(w, l)] = net.get((w, l), 0) + 1
        net[(l, w)] = net.get((l, w), 0) - 1

    swapped: set[frozenset[str]] = set()      # each pair may swap once: guarantees a stop
    changed = True
    while changed:
        changed = False
        for i in range(len(sheets) - 1):
            a, b = sheets[i], sheets[i + 1]
            pair = frozenset((a.team, b.team))
            if (pair not in swapped and a.points - b.points < dials.h2h_window
                    and net.get((b.team, a.team), 0) > 0):
                sheets[i], sheets[i + 1] = b, a
                swapped.add(pair)
                changed = True
    return sheets


def grading_uncertainty(games: list[Game], conf_of: dict[str, str], fbs: set[str],
                        dials: Dials = Dials(), frozen: Frozen = Frozen(),
                        draws: int = 2000, seed: int = 0) -> tuple[list[str], np.ndarray]:
    """Redraw every opponent grade from its error bar and rescore the whole field.

    Returns the FBS teams and a (draws x teams) array of point totals. Column spreads
    are the error bars; the share of draws a team lands inside the field is its
    chance of selection given how uncertain the grades are.
    """
    model = Strength(games, conf_of, dials, frozen)
    teams = sorted(fbs)
    idx = {t: i for i, t in enumerate(teams)}
    load = np.array([model.loading(t) for t in model.teams])        # all rated teams
    row = {t: i for i, t in enumerate(model.teams)}
    fbs_rows = np.array([row[t] for t in teams])
    who, opp, site, won, weight = [], [], [], [], []
    for g in games:
        for me, other, s in ((g.home, g.away, 1.0), (g.away, g.home, -1.0)):
            if me not in fbs:
                continue
            w = (g.home_pts > g.away_pts) == (me == g.home)
            wt = 1.0
            if w and other not in fbs and not dials.fcs_wins_count:
                wt = 0.0
            if not w and g.title_game:
                wt = dials.title_loss_weight
            who.append(idx[me]); opp.append(row[other])
            site.append(0.0 if g.neutral else s); won.append(float(w)); weight.append(wt)
    who, opp = np.array(who), np.array(opp)
    site, won, weight = np.array(site), np.array(won), np.array(weight)
    lo, hi = dials.bubble_band

    def score(beta: np.ndarray) -> np.ndarray:
        r = load @ beta
        bubble = np.sort(r[fbs_rows])[::-1][lo - 1:hi].mean()
        p = norm.cdf((bubble - r[opp] + beta[-1] * site) / frozen.sigma_wp)
        return np.bincount(who, weights=100.0 * weight * (won - p), minlength=len(teams))

    base = score(model.beta)
    official = np.array([team_sheet(t, games, conf_of, fbs, dials, frozen).points for t in teams])
    rng = np.random.default_rng(seed)
    sims = rng.multivariate_normal(model.beta, model.cov, size=draws, method="cholesky")
    return teams, official + np.array([score(b) - base for b in sims])
