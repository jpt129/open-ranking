"""Property tests for open_ranking.py on a simulated league.

Run:  python3 test_open_ranking.py

The league is synthetic (no real teams or scores). The point is to check the design
rules hold by construction, not to rank anyone.
"""
from __future__ import annotations

import random
from dataclasses import replace

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from open_ranking import Dials, Frozen, Game, Strength, grading_uncertainty, rank, team_sheet

TRUE_SIGMA, TRUE_HFA = 16.0, 2.5


def make_league(seed: int, title_games: bool = False):
    """8 FBS conferences x 12 teams, plus 16 FCS teams. 12 games each."""
    rng = np.random.default_rng(seed)
    conf_of, truth, fbs = {}, {}, set()
    for c in range(8):
        effect = rng.normal(0, 6)
        for i in range(12):
            t = f"C{c}-T{i:02d}"
            conf_of[t], truth[t] = f"C{c}", effect + rng.normal(0, 9)
            fbs.add(t)
    for i in range(16):
        t = f"FCS-T{i:02d}"
        conf_of[t], truth[t] = "FCS", -25 + rng.normal(0, 7)

    def play(home, away, neutral=False, title=False):
        m = truth[home] - truth[away] + (0 if neutral else TRUE_HFA) + rng.normal(0, TRUE_SIGMA)
        m = int(round(m)) or int(rng.choice([-3, 3]))
        base = int(rng.integers(14, 35))
        hp, ap = (base + m, base) if m > 0 else (base, base - m)
        return Game(home, away, hp, ap, neutral, title)

    games = []
    for c in range(8):                       # 9 conference games: everyone but i+5, i-5
        ts = [f"C{c}-T{i:02d}" for i in range(12)]
        for i in range(12):
            for j in range(i + 1, 12):
                if (j - i) % 12 not in (5, 7):
                    h, a = (ts[i], ts[j]) if rng.random() < 0.5 else (ts[j], ts[i])
                    games.append(play(h, a))
    fbs_list = sorted(fbs)
    for _ in range(2):                       # 2 nonconference games vs other FBS leagues
        while True:
            perm = list(rng.permutation(fbs_list))
            pairs = list(zip(perm[::2], perm[1::2]))
            if all(conf_of[a] != conf_of[b] for a, b in pairs):
                break
        games += [play(a, b) for a, b in pairs]
    fcs = [f"FCS-T{i:02d}" for i in range(16)]
    for k, t in enumerate(fbs_list):         # 1 home game vs an FCS team
        games.append(play(t, fcs[k % 16]))
    for i in range(16):                      # FCS teams also play each other
        for d in (1, 2, 3):
            games.append(play(fcs[i], fcs[(i + d) % 16]))
    if title_games:
        for c in range(8):
            ts = [f"C{c}-T{i:02d}" for i in range(12)]
            w = {t: 0 for t in ts}
            for g in games:
                if g.home in w and g.away in w:
                    w[g.home if g.home_pts > g.away_pts else g.away] += 1
            a, b = sorted(ts, key=lambda t: (-w[t], t))[:2]
            games.append(play(a, b, neutral=True, title=True))
    return games, conf_of, fbs, truth


def calibrate(seeds, dials: Dials, base: Frozen, folds: int = 8) -> Frozen:
    """Estimate the FROZEN constants from 'past seasons', out of sample, then lock them.

    Each past season is split into folds; a game is always predicted by a model that
    never saw it. In-sample calibration would make the model look sharper than it is.
    """
    resid, gaps, wins = [], [], []
    for s in seeds:
        games, conf_of, _, _ = make_league(s)
        rng = np.random.default_rng(s)
        fold = rng.integers(0, folds, size=len(games))
        for k in range(folds):
            m = Strength([g for g, f in zip(games, fold) if f != k], conf_of, dials, base)
            for g in (g for g, f in zip(games, fold) if f == k):
                gap = m.rating(g.home) - m.rating(g.away) + (0 if g.neutral else m.hfa)
                y = float(np.clip(g.home_pts - g.away_pts, -dials.margin_cap, dials.margin_cap))
                resid.append(y - gap)
                gaps.append(gap)
                wins.append(g.home_pts > g.away_pts)
    gaps, wins = np.array(gaps), np.array(wins)

    def nll(s):
        p = np.clip(norm.cdf(gaps / s), 1e-9, 1 - 1e-9)
        return -np.sum(np.where(wins, np.log(p), np.log(1 - p)))

    s_wp = minimize_scalar(nll, bounds=(4, 40), method="bounded").x
    return replace(base, sigma=float(np.std(resid)), sigma_wp=float(s_wp))


def naive_points(team, games, conf_of, fbs, dials, frozen):
    """The tempting design: grade opponents with ALL games, including the team's own."""
    m = Strength(games, conf_of, dials, frozen)
    others = sorted((t for t in fbs if t != team), key=m.rating, reverse=True)
    lo, hi = dials.bubble_band
    bubble = float(np.mean([m.rating(t) for t in others[lo - 1:hi]]))
    total = 0.0
    for g in games:
        if team not in (g.home, g.away):
            continue
        is_home = g.home == team
        opp = g.away if is_home else g.home
        site = 0.0 if g.neutral else (1.0 if is_home else -1.0)
        won = (g.home_pts > g.away_pts) == is_home
        if won and opp not in fbs and not dials.fcs_wins_count:
            continue
        p = norm.cdf((bubble - m.rating(opp) + m.hfa * site) / frozen.sigma_wp)
        total += 100.0 * ((1.0 if won else 0.0) - p)
    return total


def set_margins(games, team, win_margin):
    """Rewrite the size (never the winner) of every game `team` won."""
    out = []
    for g in games:
        if team in (g.home, g.away) and ((g.home_pts > g.away_pts) == (g.home == team)):
            lose = min(g.home_pts, g.away_pts)
            hp, ap = (lose + win_margin, lose) if g.home_pts > g.away_pts else (lose, lose + win_margin)
            g = replace(g, home_pts=hp, away_pts=ap)
        out.append(g)
    return out


def main():
    dials = Dials()
    frozen = calibrate(seeds=[101, 102, 103], dials=dials, base=Frozen())
    print(f"FROZEN constants from 3 past seasons: sigma={frozen.sigma:.2f}, sigma_wp={frozen.sigma_wp:.2f}")

    games, conf_of, fbs, truth = make_league(seed=2026)
    sheets = rank(games, conf_of, fbs, dials, frozen)
    order = [s.team for s in sheets]
    pts = {s.team: s.points for s in sheets}
    print(f"Season: {len(games)} games, {len(fbs)} FBS teams")
    model = Strength(games, conf_of, dials, frozen)
    est = np.array([model.rating(t) for t in sorted(fbs)])
    tru = np.array([truth[t] for t in sorted(fbs)])
    print(f"Engine vs true strength: correlation {np.corrcoef(est, tru)[0, 1]:.3f}")
    print("Top 5:", [(s.team, f"{s.wins}-{s.losses}", round(s.points), f"+/-{s.stderr:.0f}") for s in sheets[:5]])
    ses = [s.stderr for s in sheets[14:34]]
    print(f"Error bar on a bubble-area score (ranks 15-34, bubble teams held fixed): median +/-{np.median(ses):.1f} points")
    gaps = [sheets[i].points - sheets[i + 1].points for i in range(17, 30)]
    print(f"Median gap between neighbours near the cut line: {np.median(gaps):.1f} points")

    # Joint uncertainty: are two teams easier to separate inside a league than across leagues?
    teams, sims = grading_uncertainty(games, conf_of, fbs, dials, frozen, draws=4000, seed=1)
    col = {t: i for i, t in enumerate(teams)}
    near = order[14:34]
    same, cross = [], []
    for i, a in enumerate(near):
        for b in near[i + 1:]:
            sd = float(np.std(sims[:, col[a]] - sims[:, col[b]]))
            (same if conf_of[a] == conf_of[b] else cross).append(sd)
    print(f"Error bar on the GAP between two bubble-area teams: same league +/-{np.median(same):.1f}, "
          f"different leagues +/-{np.median(cross):.1f} points ({len(same)} and {len(cross)} pairs)")
    ranks = (-sims).argsort(axis=1).argsort(axis=1)
    p_in = (ranks < 24).mean(axis=0)
    coin = sum(0.10 < p < 0.90 for p in p_in)
    print(f"Teams whose place in a 24-team field is genuinely uncertain (10%-90% in): {coin}")
    print(f"Same error bar when the bubble band is re-ranked in every draw: "
          f"+/-{np.median([np.std(sims[:, col[t]]) for t in near]):.1f} points")

    rnd = random.Random(7)

    # T1: only the result earns points - a team's own margins never move its own score.
    worst, naive_gain = 0.0, []
    for team in rnd.sample(sorted(fbs), 24):
        tight, blowout = set_margins(games, team, 1), set_margins(games, team, 60)
        a = team_sheet(team, tight, conf_of, fbs, dials, frozen)
        b = team_sheet(team, blowout, conf_of, fbs, dials, frozen)
        worst = max(worst, abs(a.points - b.points),
                    max(abs(x.points - y.points) for x, y in zip(a.lines, b.lines)))
        naive_gain.append(naive_points(team, blowout, conf_of, fbs, dials, frozen)
                          - naive_points(team, tight, conf_of, fbs, dials, frozen))
    assert worst < 1e-9, worst
    print(f"T1 margin-proof: PASS (largest change in own points across 24 teams: {worst:.1e})")
    print(f"   naive design, same test: mean {np.mean(naive_gain):+.1f}, "
          f"range {min(naive_gain):+.1f} to {max(naive_gain):+.1f} points for winning big instead of by 1")

    # T2: winning never hurts - flip a loss to a win and the team never drops.
    losses = [(g, t) for g in games for t in (g.home, g.away)
              if t in fbs and ((g.home_pts > g.away_pts) != (g.home == t))]
    flips, bad, gains = rnd.sample(losses, 150), 0, []
    for g, team in flips:
        flipped = [replace(x, home_pts=x.away_pts, away_pts=x.home_pts) if x is g else x for x in games]
        new = rank(flipped, conf_of, fbs, dials, frozen)
        new_order = [s.team for s in new]
        gains.append(next(s.points for s in new if s.team == team) - pts[team])
        bad += new_order.index(team) > order.index(team)
    assert bad == 0, bad
    fbs_gain = [x for x, (g, t) in zip(gains, flips) if g.home in fbs and g.away in fbs]
    assert max(abs(x - 100.0) for x in fbs_gain) < 1e-9
    print(f"T2 winning never hurts: PASS (0 rank drops in {len(flips)} loss-to-win flips; "
          f"each flip vs an FBS team is worth exactly 100 points, vs FCS {min(gains):.0f}-99)")

    # T3: no game dates - shuffling the order of games changes nothing.
    shuffled = games[:]
    rnd.shuffle(shuffled)
    again = rank(shuffled, conf_of, fbs, dials, frozen)
    assert [s.team for s in again] == order
    assert max(abs(s.points - pts[s.team]) for s in again) == 0.0, \
        max(abs(s.points - pts[s.team]) for s in again)
    print("T3 order-proof: PASS (identical ranking and points after shuffling the schedule)")

    # T4: no brand names - relabelling every team and league changes nothing.
    names = {t: f"X{rnd.randrange(10**9):09d}" for t in conf_of}
    cn = {c: f"L{rnd.randrange(10**6):06d}" for c in set(conf_of.values())}
    g2 = [replace(g, home=names[g.home], away=names[g.away]) for g in games]
    c2 = {names[t]: cn[c] for t, c in conf_of.items()}
    relabelled = rank(g2, c2, {names[t] for t in fbs}, dials, frozen)
    assert [s.team for s in relabelled] == [names[t] for t in order]
    assert max(abs(s.points - pts[t]) for s, t in zip(relabelled, order)) < 1e-6
    print("T4 name-blind: PASS (same ranking after renaming every team and conference)")

    # T5: title games use the configured loss weight; winners gain, losers lose at most half.
    games_t, conf_t, fbs_t, _ = make_league(seed=2026, title_games=True)
    with_t = {s.team: s for s in rank(games_t, conf_t, fbs_t, dials, frozen)}
    n_title = 0
    for g in games_t:
        if g.title_game:
            n_title += 1
            for t in (g.home, g.away):
                line = with_t[t].lines[-1]
                assert line.site == "neutral"
                assert (line.points > 0) == line.won
                if not line.won:
                    assert abs(line.points + 100 * dials.title_loss_weight * line.p_bubble) < 1e-9
    print(f"T5 title-game rule: PASS ({n_title} title games; a loss costs {dials.title_loss_weight:.0%} of full weight)")

    # Sensitivity report: how much does the field move when a dial moves?
    top24 = set(order[:24])
    for label, d in [("bubble band 9-16 (12-team era)", replace(dials, bubble_band=(9, 16))),
                     ("margin cap 17", replace(dials, margin_cap=17.0)),
                     ("margin cap 28", replace(dials, margin_cap=28.0)),
                     ("no head-to-head rule", replace(dials, h2h_window=0.0))]:
        f = calibrate(seeds=[101, 102, 103], dials=d, base=Frozen())
        alt = [s.team for s in rank(games, conf_of, fbs, d, f)]
        moved = sum(abs(alt.index(t) - order.index(t)) for t in order[:24]) / 24
        print(f"Dial check - {label}: {len(top24 - set(alt[:24]))} of 24 teams change, "
              f"mean move {moved:.2f} spots")


if __name__ == "__main__":
    main()
