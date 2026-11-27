# Market contest preregistration, 2026 pilot — DRAFT, not hashed

Status: draft written 26 Nov 2026 for John's rulings. Nothing here is in force until John approves the text,
the file is renamed `PREREGISTRATION_2026.md`, and its SHA-256 is posted (signed tag and RFC 3161 token, as
for an issue). SPEC MK-02 requires that to happen before the first scored issue: Sunday 29 Nov 2026,
07:00 UTC. If it has not happened by then, the 2026 result is reported as "market contest not run"
(PLAN cut line 5). One season is a pilot; no claim to have beaten a market is made from it (MK-03).

Prices are for evaluation only. They never enter a predictor, and nobody on the project trades or advises
on the covered markets.

## 1. Venues

Kalshi and Polymarket, the two venues whose order books the project has archived since 25 Nov 2026,
16:51 UTC (`data/market_events.csv`). Sportsbook futures are not included: no two-sided archive exists.

## 2. Events and settlement

| Event | Our probability | Settles on |
|---|---|---|
| Team makes the 12-team field (primary) | `P(field)` in the issue's field section | The field announced on Selection Day, 6 Dec 2026, per each venue's contract rules |
| Team is a top-four seed (secondary) | `P(bye)` | The seeds announced the same day |

The venue contract rules are archived with the quotes. A contract whose rules settle on anything else is
excluded and listed.

## 3. Issues and timestamps

Every live issue that delivers an unconditional field section: Issue 1 (cutoff 29 Nov 07:00 UTC), Issue 2
(1 Dec 23:00 UTC), Issue 3 (6 Dec 07:00 UTC), Issue 4 (6 Dec 16:00 UTC). An issue whose field section is
not delivered, or is conditional on pairings (`market_contest` not "eligible"), is excluded and counted.
Replay editions never count.

The quote used is the last archived two-sided book for the contract at or before the issue's cutoff.

## 4. Filters (MK-01)

- Two-sided: a bid and an ask both present.
- Fresh: captured within 30 minutes before the cutoff.
- Spread: ask minus bid at most 5 percentage points.
- The venue probability is the midpoint of bid and ask.
- Every quote, its depth and every exclusion with its reason is archived and published.

## 5. Scoring

- Benchmark: for each team, event and issue, the median of the qualifying venues' probabilities (with two
  venues, their mean; with one, that venue). No qualifying venue: the row is unmatched and counted.
- Primary score: paired log loss, ours minus the benchmark, on matched rows. For log loss only, every
  probability is clipped to [0.000001, 0.999999]; clip counts are reported. Raw field totals are kept.
- Also reported: each venue separately, Brier scores, bubble calibration, matched and unmatched counts.
- Weights: repeated issues are averaged within team, event and horizon; teams weigh equally; the season
  is one block. No interval is reported from one season.
- Horizons: Issue 1; Issue 2; Issues 3 and 4 together.

## 6. Open points for John

1. Venues: Kalshi and Polymarket only?
2. Secondary event (top-four seed): keep, or primary only?
3. Horizon grouping in section 5.
4. Which team set is the "bubble" for calibration: the Baseline 2 cohort frozen at issue (decision k)?
5. If Issue 1's field section is not delivered, the contest starts at Issue 2. Is hashing before Issue 1
   still wanted? (Recommended: yes; it is the stricter reading of MK-02.)
