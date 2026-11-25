# CFP Rankings — consolidated build plan

Written 24 Nov 2026 from: `FixingCFPRankings2systems.pdf` (v1), `CFP_Rankings_Revised_Proposal.pdf` (v2, authoritative), `FinalBuildCFPRankingsStuff.pdf` (build package + prompt pack P00–P27), `open_ranking.py` / `test_open_ranking.py` (v0 reference).

## 1. What is being built

| Product | Question | Output |
|---|---|---|
| **Open Ranking** | How many more games did this team win than a bubble team would expect on the same schedule? | Per-game ledger in integer centipoints, rank, bracket, sensitivity intervals |
| **Shadow Committee** | Where will the committee rank the team next, and what are its odds of making the field? | Two timestamped, hashed forecasts per reveal (Sun 02:00 ET, reveal −60 min) |
| **Committee Gap** | Where did the committee depart from the résumé standard, and was it a surprise? | Open rank vs forecast median vs actual rank; flags on bid/bye/host changes |

Shared parts: a point-in-time data store, a season-versioned rules engine (4 / 12 / 24 teams), a scoring harness, and a write-once edition/release pipeline.

**The boundary that everything else protects:** Open Ranking code reads only games, teams and membership. Its settings are never tuned against committee rankings, polls or odds. Forecasts may read Open Ranking output. Playoff-futures prices are evaluation-only.

## 2. How the three documents relate

| Topic | v1 original | v2 revised (authoritative) | Final package adds |
|---|---|---|---|
| Title-game loss | 50% weight (a dial) | Full weight, win and loss | — |
| Link function | Normal CDF, σ = 16 | Logistic, scale `t` frozen pregame | — |
| Head-to-head | Adjacent swap inside 25 pts | Only in an isolated group of exactly two | Series = every meeting that season |
| FCS | Win 0, loss ≈ −99 | Win 0, loss fixed −99, FCS out of the fit | Confirms CFP "at most one FCS win" wording |
| "Winning never hurts" | Asserted as a rule | Unproved; publish every reversal | Report must be complete, not empty |
| Error bars | Posterior covariance | 1,000 Exp(1)-weighted refits + LOO interconference + no-league fit | Budget < 5 min |
| Points arithmetic | Floats | "Canonical points before rounding" | Integer centipoints, half-even, boundary flags |
| Committee model | Bayesian state-space + 4 add-ons (NumPyro) | Compact regularized Plackett–Luce; add-ons one at a time under a promotion rule | Gumbel-max sampling, L2 by chronological folds |
| Market claim | "Beat the market on log loss" | Preregistered contest; one season = pilot | Hash the preregistration first |
| Gap sign | Committee − open | Lift = open − actual (positive = committee higher) | — |
| Explain trigger | 3+ spots apart | Any change to bid, bye or host | — |
| Second implementation | University replication | Two implementations must match | Clean-room TypeScript, doubles as the what-if tool |

Where v1 and v2 differ, v2 wins. Where the final package differs from v2, it is a suggestion (a–l) that needs your accept/reject.

## 3. What the v0 sample code is good for

Ran `python3 test_open_ranking.py` on this machine: T1–T5 all pass and reproduce v1's simulated numbers (gap error ±27.0 same league vs ±68.0 cross league; 9.2-point median neighbour gap; 14 uncertain teams; naive-design leak up to +12.7).

It is a **reference for test ideas and the league generator, not a starting codebase**. It contradicts the current spec in seven places:

1. `title_loss_weight = 0.5` → full weight.
2. `norm.cdf(z / sigma_wp)` → logistic with frozen `t`.
3. Head-to-head swap loop → isolated-pair rule on ≤2500-centipoint groups.
4. Float points → integer centipoints.
5. FCS loss costs `100·p` (83–99 in the run) → fixed −9900; FCS teams are in the fit → excluded.
6. Independents share a conference effect via `conf_of` → individual effects.
7. Delta-method `stderr` and `np.linalg.inv` → reweighted refits and `solve`.

Carry over: `make_league` as the seed of the Hypothesis generators (P10), the margin/flip/shuffle/relabel tests, and `naive_points` as a regression demonstration of why leave-team-out exists. The NumPy matmul RuntimeWarnings it prints on this Mac are a BLAS quirk and do not change results, but they are a reminder that floats are not bit-reproducible across machines, which is the case for centipoints and boundary flags.

## 4. Architecture (from Part 2 of the final package)

```
sources → lake/raw (SHA-256 addressed) → lake/normalized Parquet (+6 provenance fields, vintage)
   ├─ OpenRankingView (games, teams, membership) → Open Ranking ─┐
   └─ PointInTimeView as_of(issue)            → Shadow Committee ─┼→ rules engine → editions (write-once)
                                                                  └→ scoring harness → scorecards, Committee Gap
```

- Layout: `src/cfp/{common,store,ingest,identity,snapshot,open_ranking,rules,forecast,scoring,markets,gap,release}`, `ts/`, `tests/{unit,property,fixtures,replay}`, `docs/`, `.claude/`, `lake/` (git-ignored), `frozen/`.
- Every row: `source_id, event_time, first_public_time, ingest_time, correction_version, raw_hash`, `vintage ∈ {live, archived_authentic, reconstructed, unknown}`.
- `as_of(table, t, mode)`: `first_public_time ≤ t`; live mode also `ingest_time ≤ t`; scored mode drops unknown vintage.
- Boundary enforced three ways: import-linter contract, `OpenRankingView` allow-list, and a test that deletes forbidden tables and demands byte-identical editions.
- Guardrails: `CLAUDE.md`, `docs/PROTOCOL.md` (8-step test-first loop), 8 subagents, 8 skills, `settings.json` deny rules, `guard.py` hook.

## 5. Problems I found in the package (fix before or during the build)

1. **The pilot track is missing prompts its own calendar needs.** Listed: P00–P09, P15–P19, P23, P24. But:
   - P05/P06 need frozen `t` and ridge penalties, which only P11 produces. → Add a **P11-lite** (grid search on 2015–25, write `frozen/params_2026.json`, labelled provisional).
   - Pilot exit criteria require a public ledger → needs a **P14-lite** (manifest, gate, write-once edition, JSON/HTML; no TypeScript what-if).
   - "Reveal → score, publish Gap" on 1 Dec → needs **P20-lite** and **P22-lite**.
2. **The release gate requires a cross-implementation match (P13) that cannot exist in the pilot.** The gate needs an explicit "second implementation: not run" disclosure state, otherwise it either blocks every pilot release or gets bypassed.
3. **P04 says "title games neutral", but several 2026 title games are on campus** (the package's own table has the Pac-12 game at Boise State). v2 says to store the official site and apply home advantage at home. Use the real site flag; do not force neutral.
4. **`guard.py` matches substrings.** `"src/" in target` blocks `ts/src/` in the clean-room session, and `"frozen/"` blocks read-only Bash such as `cat frozen/MANIFEST`. Either keep TS sources out of a `src/` folder and read frozen files with the Read tool, or anchor the match to the project root. Also by design Claude can never write `frozen/` or `lake/editions/` directly, so P11 and P14 must write them through the `cfp` CLI.
5. **P-SPEC depends on your a–l decisions, but `CLAUDE.md` already hard-codes some of them** (d centipoints; P04 uses e; P08 uses f). Decide a–l before P00 so SPEC tags are honest.
6. **Calendar order risks the one deadline that cannot be repaired.** The package builds the ledger (Thu) before the baselines (Fri). A late ledger can be corrected; a missed forecast cannot. Build the forecast path first (section 7).
7. **The plan is staffed for eight people.** The schedule below assumes one person driving Claude Code; scope is cut accordingly.
8. **Unverified inputs the package itself flags:** 2014–23 top-four fixtures, AP release times, 2026 Big Ten tiebreak text, American/CUSA/MW/Sun Belt tiebreaks, FBS count (136 vs 138), Kalshi keyless reads and candlestick intervals.

## 6. Decisions needed from you before P00

| # | Decision | My recommendation |
|---|---|---|
| a | Independents get penalty 1/(σc²+σu²) | Accept; publish Notre Dame under both |
| b | Keep pregame `t`; LOO-game calibration as diagnostic | Accept |
| c | Keep Open Ranking FCS 0/−99; store CFP rule as 2027+ eligibility note | Accept |
| d | Integer centipoints, half-even, boundary flag | Accept (already assumed by CLAUDE.md) |
| e | Definitions: ordinary FBS game, Week 7, Monday 06:00 ET cutoff, transitioning programs | Accept |
| f | Series = every meeting; 1–1 keeps points order | Accept |
| g | Title games in the fit; bowls/playoff out | Accept, with the real site flag (problem 3) |
| h | America/New_York, store UTC | Accept |
| i | SHA-256 via signed public git tag + RFC 3161 + public post | Accept; needs a public repo and a signing key |
| j | Secondary weekly score on forecast top 35 ∪ actual top 25 | Accept |
| k | Bubble cohort from Baseline 2, frozen at issue | Accept |
| l | 2027 champion rules as data; block the freeze until published | Accept |

Also needed:
- **CFBD API key** (free tier is 1,000 calls/month; the backfill is about 500).
- **The Odds API**: paid, about $30/month. Without it, game probabilities come from the strength model and that is disclosed.
- **Public GitHub repo + signing key** for pre-reveal hash proof.
- **Trading policy**: confirm nobody on the project trades covered markets.
- **Repo location**: I recommend making this folder the repo, with the PDFs under `docs/source/` and v0 under `reference/v0/`.

## 7. Pilot schedule (solo, forecast path first)

Fixed times: Issue 1 Sun 29 Nov 02:00 ET (07:00 UTC) · Issue 2 Tue 1 Dec 18:00 ET (23:00 UTC), reveal 19:00 · Issues 3 and 4 Sun 6 Dec 02:00 and 11:00 ET (07:00 and 16:00 UTC), reveal noon.

| Day | Work | Prompts |
|---|---|---|
| Wed 25 | Decisions, keys, repo. Bootstrap, SPEC, store, CFBD + CFP ingest. Start 2014–25 backfill and price capture. | P00, P-SPEC, P01, P02a, P02b (P02c/d if keys) |
| Thu 26 | Identity, snapshots, baselines, issue pipeline. Dry-run an issue end to end with Baseline 2. | P03, P04, P15, P23 |
| Fri 27 | Open Ranking core on real 2026 data with provisional frozen params. | P11-lite, P05, P06, P07, P08 |
| Sat 28 | Rules engine with 2024/2025/2026 fixtures; minimal Plackett–Luce; title-game simulator. **18:00 ET go/no-go**: fitted model or Baseline 2 as the labelled forecast. Ingest finals overnight. | P09, P16, P17 |
| Sun 29 02:00 | **Issue 1**, hash posted. | /issue-sunday |
| Sun 29–Mon 30 | Ledger edition public; title-game matchups; field conditionals; scoring and gap. | P14-lite, P18 (matchups only), P19, P20-lite, P22-lite, P24 |
| Tue 1 Dec | **Issue 2** 18:00; after 19:00 reveal: ingest, score, Gap. | /issue-tminus60, /ingest-release, /score-reveal |
| Wed 2–Sat 5 | Scorecard; fix defects as new editions; capture title-game prices. | — |
| Sun 6 Dec | **Issues 3 and 4**; noon reveal; Selection Day Gap with bid/bye/host flags. | — |

Cut lines, in the order things get dropped if time runs out:
1. Never dropped: a hashed Baseline 2 weekly forecast (needs only P00, P01, P02a/b, P03, P15, P23).
2. Open Ranking ledger (P04–P08, P11-lite).
3. Final-field forecast (P09, P17, P19).
4. Fitted Plackett–Luce (P16).
5. Market contest for the pilot → "market contest not run".

Pilot simplifications that stay inside the spec:
- After 28 Nov only about ten title games remain, so P17 simulates those and P18 only has to resolve title-game participants; full tiebreak modules wait for the replay phase.
- Plain full refits in P05 (about 136 solves of a ~150-parameter system is already fast); Woodbury downdates move to the full track with their equality proof.
- Any missing input removes or disqualifies an output and is logged in `DATA_GAPS.md`; nothing is filled with a substitute.

## 8. After the pilot

| Phase | Dates | Prompts | Exit criteria |
|---|---|---|---|
| Hardening + replay | Dec 2026–Mar 2027 | P10, P11 full, P12, P13, P14 full, P18 full, P20–P22 full, P25 | 2014–25 rebuilt; Python and TypeScript match outside boundary flags; official fields reproduced; FSU 2023 and Miami/ND 2025 case files |
| Model expansion | within replay | P26, one candidate per session | Promote only if the primary score improves and bubble Brier worsens ≤ 0.01 |
| Audit and freeze | Apr–Aug 2027 | P27 | Red-team and leakage reports answered; 2027 policy, params, sources, code hash and contest frozen; champion rules archived |
| 2027 season | after Week 7 | weekly operating prompts | Every eligible issue graded; scorecard and replication published before any adoption request |

## 9. Acceptance numbers to hold the build to

- Ledger: p = 0.20 win then p = 0.90 loss = −1000 cp; reverse path = −1000 cp; ten wins with Σq = 74500 → +25500; title game at q = 5000 → ±5000; FCS win 0, FCS loss −9900; every ordinary FBS flip = ±10000.
- Ordering: split series, three-team cycle, chained 2400 + 2400 gaps, exact tie at the cutoff.
- Rules 2025: seeds 1–10 Indiana, Ohio State, Georgia, Texas Tech, Oregon, Ole Miss, Texas A&M, Oklahoma, Alabama, Miami; Tulane (No. 20) seed 11; James Madison (No. 24) seed 12; Notre Dame (No. 11) out.
- Rules 2024: Oregon, Georgia, Boise State (9), Arizona State (12), Texas, Penn State, Notre Dame, Ohio State, Tennessee, Indiana, SMU, Clemson (16).
- 2026 rules on the 2025 order: Notre Dame 10, Tulane 11, Duke 12; Miami and JMU out.
- Forecast: two losses move a team 10 places in Baseline 2; ΣP(field) = 12, ΣP(bye) = 4; perfect forecast scores 0.
- Budgets: `as_of` over 1M rows < 1 s; 136 fits < 1 s; 1,000-refit sensitivity < 5 min; 10,000 paths < 30 min on 8 cores.

## 10. First build session

1. Record your a–l answers and the items in section 6.
2. `git init` here; move sources; convert the Revised Proposal to `docs/PROPOSAL.md` verbatim.
3. Install the pack files: `CLAUDE.md`, `docs/PROTOCOL.md`, 8 agents, 8 skills, `settings.json`, `guard.py` (with the fixes from section 5).
4. Run P00 in plan mode, then P-SPEC.
