# SPEC — numbered requirements

Source: `docs/PROPOSAL.md`, a transcription of `docs/source/CFP_Rankings_Revised_Proposal.pdf`; page numbers refer to it. Precedence: the PDF, then PROPOSAL.md, then this file. Numbers are the proposal's own.

Tags: **[P]** stated in the proposal. **[S-x]** accepted suggestion *x* from the final build package §1.4, accepted by John on 2026-11-25 (`docs/DECISIONS.md`). **[S-pilot]** pilot decision accepted 2026-11-25. **[K]** constraint taken from the final build package (its CLAUDE.md, architecture or prompt text), adopted when John approved building with the pack; it tightens the proposal and is not proposal text. **[OPEN]** awaiting John's decision.

Units: proposal "points" are hundredths of a win. Code stores **centipoints (cp)**: 1 point = 100 cp, one win = 10000 cp. Where a requirement quotes points, the cp value follows in parentheses.

Defined terms [S-e]:
- **Ordinary FBS game**: a completed regular-season or title game between two teams classified FBS on the game date, not a forfeit.
- **FBS on the game date** [S, ruling 2026-11-25]: in that season the team is an NCAA FBS member (including a reclassifying member in its first FBS season) and a football member of an FBS conference or an FBS independent. The NCAA's bowl-eligibility counting of FBS wins is not an input.
- **Week 7**: CFBD calendar week 7.
- **Cutoff**: Monday 06:00 ET after the week's last game.
- **Transitioning programs**: classed by the rule above; bid eligibility is a separate sourced flag per team-season.

---

## OR — Open Ranking (pp. 1–3)

**OR-01 [P] Unit.** Game points = 100 × (actual win − bubble win probability). A win counts as 1 and a loss as 0. A team's total is the sum of its game points. For ordinary FBS games, 100 points equals one win above the bubble team's expected total.

**OR-01a [S-d] Fixed point.** q = round_half_even(p × 10⁴), an integer in 0..10000. Win = 10000 − q cp; loss = −q cp. If |p × 10⁴ − (⌊p × 10⁴⌋ + 0.5)| < 10⁻⁶ the game is flagged as a boundary case. The Python value is canonical. Totals, gaps and tiebreak comparisons are integer cp. Display rounds half-even. [K] Display rounding happens only at render.

**OR-02 [P] Opponent strength, evaluated team removed.** For each FBS team A:
- (a) remove every game involving A from the strength fit;
- (b) fit current-season FBS-versus-FBS margins, capped at ±24;
- (c) margin = home strength − away strength + home advantage, with zero site adjustment on neutral fields;
- (d) each team strength = conference effect + team deviation;
- (e) both are fitted with ridge shrinkage toward zero;
- (f) independents get individual effects without a shared league bonus;
- (g) no team carries over its own prior-year rating.

**OR-02a [S-a] Independents' penalty.** An independent's individual effect has ridge penalty 1/(σ_c² + σ_u²), matching a league team's prior variance σ_c² + σ_u². Notre Dame's ledger is published under both this penalty and the σ_u²-only penalty.

**OR-02b [S-g] Games in the fit.** Conference title games are in the fit. Bowl and playoff games are not. A title game's site adjustment follows its official site and home designation (zero only if the field is neutral).

**OR-03 [P] Reference band.** In A's fold, exclude A from the bubble candidate pool. The bubble strength is the average of the remaining FBS strength estimates ranked 1–8 for a four-team field, 9–16 for twelve, or 21–28 for twenty-four. Record the band members and their average. Estimate the home advantage in the same fold.

**OR-04 [P] Link.** For opponent j, p = 1 / (1 + exp(−d / t)), where d = bubble strength − opponent strength, plus the home advantage at home or minus it on the road; on neutral fields d is the strength difference alone. The positive scale t and the shrinkage penalties are fitted on earlier seasons using pregame predictions of actual FBS results, and frozen before the season.

**OR-05 [P] Title games.** A conference championship game scores the win and the loss at full weight. In a 50–50 game this yields +50 or −50 (±5000 cp).

**OR-06 [P] FCS games.** Every FCS win earns 0. Every FCS loss costs 99 points (−9900 cp). FCS games are excluded from the FBS strength fit.

**OR-07 [P] Snapshot.**
- (a) The first table is released after Week 7, using completed games through the announced cutoff. [S, ruling 2026-11-25] Selection Day has its own edition: in 2026 the cutoff is Sun 6 Dec 02:00 ET, published before 11:00 ET, because the Monday cutoff falls after the reveal.
- (b) Each game stores game ID, opponents, final score, official site, home designation, FBS/FCS status and conference membership on the game date.
- (c) Canceled games, no-contests and postseason playoff or bowl games are omitted.
- (d) A forfeit uses the certified result; its administrative margin is omitted from strength fitting. [S, ruling 2026-11-25] A forfeit is scored as a normal win or loss at the scheduled site at its reference probability, labelled "forfeit", with no special arithmetic. It is outside the ordinary-FBS population VT-01 is required for. An unplayed forfeit is not a meeting for head-to-head (TB-03). Vacated wins are not forfeits; a ruling made public after a cutoff is a later correction, invisible to replay at that cutoff. Forfeits are a hand-verified list kept as data; a game that looks like a forfeit and is not on the list blocks the snapshot and is logged in DATA_GAPS.md.
- (e) [K] A game that ends after the cutoff is excluded. Omissions are logged with reasons.

**OR-08 [P] Ledger.** One row per game: opponent, venue, result, reference probability, points, policy exception, revision since last week. Per team: total, raw rank, head-to-head decision, final open rank, rule-version ID. Old wins are recalculated as evidence about opponents changes. Each edition publishes its input snapshot and formula hash.

**OR-09 [P] What-if.** A reader can flip a result and regenerate all ledgers and the bracket. [S-pilot] Not delivered in the pilot; the pilot ledger page says so.

**OR-10 [P] Settings.** v1 uses the same band for selection and seeding. Alternatives are published for the strength band, the 24-point margin cap and the 25-point head-to-head window, with each setting's historical field turnover.

**OR-11 [P] Arithmetic fixtures.**
- (a) With p = 0.20 and p = 0.90: win +80 then loss −90 totals −10 (−1000 cp); loss −20 then win +10 totals −10 (−1000 cp).
- (b) Ten wins against an expected 7.45 yield +255 points (Σq = 74500 → +25500 cp).

**OR-12 [P] Independence of settings.** Open Ranking weights and policy settings are chosen independently of committee rankings, poll votes and betting odds. Historical committee agreement has no role in selecting them.

**OR-13 [P] Reference monotonicity.** A stronger reference raises its expected wins and lowers the absolute points awarded for any fixed win.

**OR-14 [P] Adoption decision.** Before kickoff the governing group ranks anonymized example résumés under alternate settings. Its rationale and each setting's historical field turnover are published, and the values are chosen in public.

## TB — Tiebreaks (p. 3)

**TB-01 [P] Groups.** Sort by canonical points before display rounding. Form contiguous groups by joining adjacent scores at most 25 points apart (gap ≤ 2500 cp).

**TB-02 [P] Isolated pair.** In a group of exactly two, the head-to-head winner goes first if the teams met and one won the series. Larger groups stay in points order.

**TB-03 [P] Split series.** A split series keeps points order. [S-f] The series is every meeting that season, title games included; a 1–1 split keeps points order.

**TB-04 [P] Exact ties.** Unresolved exact ties are published as shared ranks. Where a bracket needs a total order, an auditable preseason draw attached to team IDs supplies it.

## VT — Verification and scoring (pp. 4, 7)

**VT-01 [P] Flip exactness.** Flipping any ordinary FBS result with the schedule fixed changes the evaluated team's total by exactly 100 before display rounding (exactly 10000 cp).

**VT-02 [P] Margin invariance.** Changing only a team's margins while preserving results leaves its total fixed.

**VT-03 [P] Relabel, permutation, neutral reversal.** Renaming teams, permuting input rows and reversing home/away on neutral-site games leave totals and mapped ranks in agreement.

**VT-04 [P] Ordering cases.** Tests exercise a split series, a three-team cycle, chained 25-point gaps and an exact tie at the cutoff.

**VT-05 [P] Rank-reversal audit.** Every historical loss-to-win flip is replayed through all teams and tiebreaks. Every case where the winner's rank falls is published. "Winning cannot lower rank" is treated as unproved unless established for the entire procedure. [K] The test asserts the report is complete, not that it is empty.

**VT-06 [P] Point-in-time replay.** Each available weekly snapshot from 2014–25 is rebuilt with source hashes, league membership, rule version, dependencies, fixed-point precision and rounding pinned. Row sums are exact. Two implementations match on canonical ledgers, ranks and bracket decisions. [S-d] The Python value is canonical and the cross-check tolerates mismatches only on boundary-flagged games.

**VT-07 [P] Probability calibration.** Rolling, pregame FBS predictions for real teams are scored by Brier score and log loss against a venue-only model, with observed wins plotted by probability bin, venue and season. Closing lines are an external schedule-strength benchmark where available. Calibration is frozen before grading the next year. [K] The closing-line comparison is a report computed outside `cfp.open_ranking` (in `cfp.scoring`); it never selects t, the penalties or any setting (OR-12).

**VT-07a [S-b] Retrospective diagnostic.** Leave-one-game-out retrospective calibration is reported as a diagnostic only. The frozen pregame t stands for v1; the question is decided before the 2027 freeze.

**VT-08 [P] Evidence sensitivity.** With results held fixed, run 1,000 refits with independent exponential weights of mean one for games, reusing each game's weight across every team. Refit the bubble benchmark and bracket. Publish the middle 80% of rank or points differences and the share of refits in which the team qualifies. [K] Built as "sensitivity to the observed games", not a full uncertainty interval. Weights multiply squared-error terms only; penalties and frozen settings are unchanged. Each refit has its own seed from the edition seed and its index. Published per team: rank difference, margin to the at-large cut line in the same refit (the headline) and points difference, each as a middle 80%, and the qualify count. Before the title games the champion stand-ins are the published order's, held fixed across refits; the six-conference place is recomputed per refit. The report is a separate write-once file naming the edition by hash; the gate reruns ten refits chosen by that hash and does not block on it (docs/DECISIONS.md, 2026-11-26). [K, 26 Nov] Each row also names the team's route into the published field, so a guaranteed place below the at-large line is not read as out. The file records the hash of the field code and rules files, the tables the bracket inputs were read from, and the environment (OS, Python, numpy, BLAS); reproduction is claimed in that environment only. The command stops at a time limit (default ten minutes) and then writes nothing.

**VT-09 [P] Further checks.** Omit each interconference game from the fit; fit without league effects; flag disconnected schedules; test whether skipping an optional game improves bid odds despite forfeiting expected points; report 2020 separately.

**VT-10 [P] Forecast historical replay.** 2014–16 is the initial training window. Forecast 2017 forward one season at a time. Features and regularization are tuned in earlier chronological folds. Within a held-out season, updates use only already released rankings. Forecaster code, data vintage, issue time and sample seed are stored.

**VT-11 [P] Weekly rank score.** Score cumulative P(rank ≤ k) for k = 1…25 against the observed indicator and average squared errors over cutoffs and teams: S = (1/(25·N)) Σ_i Σ_{k=1..25} (P_i(r ≤ k) − 1[r_i ≤ k])². Also report top-25 entrants and exits, exact slots, and rank error on jointly ranked teams with its coverage. Compare AP-as-issued, prior-CFP update and the fitted model.

**VT-11a [S-j] Secondary weekly score.** The same score is also reported on the union of the forecast top 35 and the actual top 25. The 2026 FBS team count is verified from the source (reports conflict: 136 vs 138), and each season's count is read from data, not assumed.

**VT-12 [P] Final-field score.** Field and bye probabilities are scored with Brier score and log loss, reported by lead time, season, rules era, automatic/at-large route and bubble. The bubble is defined in advance as teams within five baseline rank positions of the projected last at-large team, and the same cohort is used for every model. [S-k] The cohort is Baseline 2's, frozen at issue.

**VT-13 [P] Bracket integrity.** Seeds, hosts and byes are unique per path. Field and bye probabilities sum to their respective counts. Simulated win rates match input probabilities within Monte Carlo error; within-team dependence is tested against historical residuals. The release hash replays.

**VT-14 [P] Promotion rule.** A component is promoted only if the primary held-out score improves (weekly rank score or final-field log loss) and bubble Brier worsens by no more than 0.01. One live season is a pilot. Replication is looked for across seasons.

## SC — Shadow Committee, next reveal (p. 5)

**SC-01 [P] Observation.** One training example is one committee release and its complete list of eligible FBS teams. The target is 25 ordered teams; each omitted team is known only to be below 25. Entrants and every unranked candidate are in the denominator. A separate eligibility flag records whether the school can receive a bid that season. Labels are official CFP releases.

**SC-02 [P] Two cutoffs.** A weekend forecast is issued at 2 a.m. ET Sunday after the Saturday slate, and an updated edition 60 minutes before the scheduled reveal. Each uses only poll releases, completed games and other inputs publicly available by its cutoff. Actual issue time and immutable input IDs are logged. If any label has leaked publicly, the edition is marked ineligible for prospective scoring.

**SC-02a [S-h] Time.** Issue times resolve in America/New_York and are stored in UTC. On a DST-change Sunday the later 02:00 is used.

**SC-03 [P] Baselines.**
- Baseline 1: carry forward the latest available AP order.
- Baseline 2: start with the prior CFP top 25, followed by all other teams ordered by AP votes, then open points. Add five to each team's initial position for each loss since that release. Sort by adjusted position, then original order. AP is the opening anchor. Remaining ties break by the published preseason draw.
- For probability comparisons, a rank-noise temperature is fitted for each baseline on earlier seasons and its full order is sampled. Deterministic rank accuracy is also shown.

**SC-04 [P] Plackett–Luce.** Each team gets a weighted score from available AP vote share, prior CFP position and unranked flag, losses, open points, and the latest result adjusted for opponent, site and capped margin. Features are standardized on prior training seasons. The model is a regularized Plackett–Luce: draw one team at a time with chance proportional to exp(score) among remaining teams, fitted against the observed first 25 picks. On the opening week the prior-CFP feature is omitted.

**SC-04a [S, ruling 2026-11-25] Open points as a feature build.** Each forecast issue (sun0200, tminus60) computes open points at its own cutoff by calling the Open Ranking package's public entry point on a snapshot at that cutoff, with the same frozen parameters and rule_version_id; forecast code holds no copy of the formula. The build reads through OpenRankingView only, and the forbidden-tables test covers feature builds. The forecast manifest's immutable inputs record snapshot hash, frozen-parameters hash, rule_version_id and feature_build_id. A feature build is never published or labelled as an edition; the Committee Gap's open rank comes only from the published edition frozen before the reveal. When a feature build and a published edition share a snapshot hash, their ledgers are byte-identical. Replay and simulation build the feature the same way. Live issues ingest immediately before the cutoff, then freeze; a game that goes final after the cutoff waits for the next edition.

**SC-05 [P] Distribution.** Sample 10,000 ordered lists with a recorded random seed. Count each team's rank frequencies, grouping lower ranks as "outside 25". If a team's median is outside the published list, print that category. Produce pairwise probabilities for bubble comparisons. Any sampling temperature is calibrated on earlier validation folds. Public outputs: median rank category, probability of entering the top 25, and probabilities at the bye and hosting cutoffs.

**SC-06 [P] Expansion.** Season-varying weights, AP-history priors, team effects, injury status, a boosted ranker and coded chair remarks are tried one at a time. Each feature is dated. Post-reveal comments first become eligible at the following issue. A component is added only under VT-14.

## FF — Final-field forecast (p. 6)

**FF-01 [P] Frozen state.** Read completed scores, scheduled games, league membership, current standings, championship tiebreakers and polls at the issue cutoff. Store timestamped two-sided game prices where available. Team playoff-futures prices never enter the predictor; they are reserved for evaluation.

**FF-02 [P] Simulated scores.** Game probabilities come from the two normalized moneyline probabilities, or an as-of spread converted with a curve trained on past seasons, or a strength model for unquoted games. Future closing lines are not used. Games are correlated by normal team and game shocks: the standardized home-minus-away team shock and an independent game shock are combined with squared weights summing to one; the normal CDF gives a uniform draw; the home team wins when it exceeds 1 − p(home). Weights are fitted on prior seasons. Margins and totals are sampled from history conditional on win and expected strength; scores are valid and untied.

**FF-03 [P] Simulated résumés.** Each path adds simulated scores, resolves league standings, plays any title games and recomputes open points. Final-rank updates are anchored to the actual CFP and AP releases known at issue. Training uses only variables available both in historical replay and simulated futures. Weights are pooled with the weekly model; any Selection Day adjustment is shrunk toward the weekly estimate.

**FF-04 [P] Bids.** Each path samples a terminal committee order, including an order among potential unranked automatic qualifiers when required, and applies the season's rules (BR-*) to produce 4, 12 or 24 distinct qualifiers and their seeds. If an external league tiebreak input is unavailable, its scenarios are published when they alter a bid. The baseline is scored on the same paths by updating the last CFP order (AP before the first release) five positions per subsequent loss, under identical bid rules. [S, ruling 2026-11-26] A pairing is final only on the conference's announcement, or its published scenario plus the deciding final score. Scenarios are run one by one, never merged or weighted; over eight combinations, or an open league whose teams take the other conferences' place in more than 5% of paths, the field section is not delivered. For a named conference the schedule settles nothing and is a cross-check only. A scenario list rests on the conference's published scenarios or on two independent outlets that agree; if the pairing played was not listed, the section is not scored and is logged as a miss. The scenario that matches the pairings played is the one scored, as conditional on pairings, and such an issue is out of the market contest.

**FF-05 [P] Outputs.** At least 10,000 paths for public forecasts. Publish P(field), P(bye), P(host) with round identified, and the seed distribution; P(field | win next game) and P(field | lose next game), with path counts. Re-run at larger sample size if simulation noise could explain a reported difference. "Field if the season ended today" is shown separately from the forward forecast.

**FF-06 [P] 2025 acceptance fixture.** Given the official final order and champions, the rules engine returns No. 24 James Madison as seed 12, No. 20 Tulane as seed 11, and No. 11 Notre Dame outside the bracket.

## MK — Market contest (p. 7)

**MK-01 [P] Filters and scoring.** Match team, event and issue. Pilot filters require two-sided quotes within 30 minutes and exchange spreads ≤5 percentage points. Remove book margins or use the exchange midpoint. Archive quotes, depth and exclusions. For log loss only, clip all probabilities to [0.000001, 0.999999] and report clip counts; raw field totals are preserved. Compare paired log loss against the median qualifying venue probability.

**MK-02 [P] Preregistration.** Venues, settlement events, timestamps and scoring weights are preregistered, and each test's benchmark, timestamp and scoring rule is specified before the outcome is known. [K] The preregistration is hashed before the first scored issue.

**MK-03 [P] Reporting.** Report each venue, Brier scores and bubble calibration. Weight seasons equally and average repeated issues within each team, event and horizon. Show matched counts and paired season-level differences. Season-block intervals are used only with sufficient seasons. Any market claim identifies the venues, events and period beaten.

## BR — Bracket rules (p. 8)

**BR-2014 [P] 2014–2023.** Four teams: the final committee top four in rank order for semifinals. No automatic bids or first-round byes.

**BR-2024 [P] 2024.** Twelve teams: five highest-ranked conference champions plus seven at-large. The four highest-ranked champions receive byes as seeds 1–4. Remaining qualifiers are placed in rank order.

**BR-2025 [P] 2025.** Twelve teams: five highest-ranked conference champions plus seven at-large. The top four ranked teams receive byes. Outside-top-12 qualifying champions get the bottom seeds in rank order.

**BR-2026 [P] 2026.** Twelve teams: ACC, Big Ten, Big 12 and SEC champions; the highest-ranked team from the other six specified conferences; seven at-large. Notre Dame is guaranteed a place if ranked in the top twelve. The top four receive byes. The special ordering procedure applies to unranked automatic qualifiers.

**BR-2027 [P] 2027 onward.** Twenty-four teams: four named power-conference champions, the highest-ranked team from the other six conferences, and 19 at-large. Seeds 1–8 receive byes and host in round two. Seeds 9–16 host in round one. How each league names its champion is loaded for that season. [S-l] Champion rules are data per season, and the 2027 freeze is blocked until each is published.

**BR-SCHED [P] Scheduling standards.** In 2027 the six-conference group is the American, Conference USA, MAC, Mountain West, Pac-12 and Sun Belt; its automatic place goes to its highest-ranked team across the group. The CFP permits consideration of at most one FCS win [S-c: stored as a 2027+ eligibility note; it does not change OR-06]. The ten-game scheduling standard counts conference games plus specified nonconference games: for the four power leagues, games against another power-league opponent or Notre Dame; for the six-league group, also games against either group or any FBS independent. The CFP can grant extraordinary waivers. Official eligibility and waivers are recorded; a raw count alone cannot exclude a team.

**BR-CONTRACT [P] Engine contract.** Inputs: rank order, official eligibility, conference champions, season rules and any extra committee ordering. Outputs: qualifier, bid route, seed, bye, host round and reason.

**BR-FIX [P] Fixtures.** A champion outside the top 25; a top-12 Notre Dame in 2026; a below-cutoff automatic bid; a scheduling waiver; each seed boundary; and FF-06.

## CG — Committee Gap (p. 9)

**CG-01 [P] Lift.** Join by team and reveal ID. The public formula rank and forecast edition are frozen before the announcement; the official release is recorded separately. Committee lift = open rank − actual committee rank; positive means the committee ranked the team higher. An omitted team shows "outside 25" and a bound where available. The pre-reveal 80% rank interval is displayed alongside the forecast median. Worked example: open 13, forecast median 9, actual 8 → lift 5, anticipated 4, one spot above the median.

**CG-02 [P] Consequence flags.** On Selection Day both orders run through the same eligibility, automatic-bid and seeding rules, and every change to a bid, a bye or the right to host is flagged, even if only one rank apart. Before Selection Day, weekly rank differences are shown and bracket effects are identified as provisional under the displayed champion scenario.

**CG-03 [P] Reasons.** For teams straddling a cutoff: ledger differences, decisive games, head-to-head treatment and cross-league sensitivity. The chair's dated public explanation is linked, and any additional inference is labeled.

**CG-04 [P] Aggregation.** Use that season's conference membership. Report entrants, exits, shared-list mean lift and its coverage. Bound missing ranks. Estimate variability in season blocks. Show how the association changes when poll and conference labels are removed.

**CG-05 [P] Governance.** The shadow ranking launches first. In the next phase a written explanation is sought for every change to a bid, a bye or hosting. The governing body decides on adoption after public review.

## DS — Data store (pp. 1, 10, 11)

**DS-01 [P] Provenance.** Every record keeps source ID, event time, first-public time, ingest time, correction version and raw hash.

**DS-02 [P] Vintage.** Authentic archived snapshots are tagged separately from reconstructed records. Unknown-vintage inputs are excluded from the scored test, or that forecast is suppressed and the missing coverage disclosed.

**DS-03 [P] Point-in-time query.** A forecast query requires first-public time at or before issue time, and a record actually available to the live system then. [S, ruling 2026-11-25] Live requires first_public_time <= t and ingest_time <= t; replay requires first_public_time <= t only. Each correction version carries its own first-public time, and "latest" means latest among those public by t. Estimated first-public times err late: a game with no recorded end time is public at kickoff + 4.5 h. Vintage travels to every scorecard row; reconstructed is reported separately from authentic. Replay output is never labelled prospective; only live issues count toward the pilot and the market contest. Reproducing a published live edition uses the manifest's pinned input IDs, not replay mode.

**DS-04 [P] Boundary.** Both products read the same dated game records and bracket rules. The forecast can use the public résumé score. Open Ranking weights and policy settings are chosen independently of committee rankings, poll votes and betting odds (OR-12). [S, ruling 2026-11-26] The allow-list is: games, with the three hand-verified annotation lists (`data/title_games.csv`, `data/forfeits.csv`, `data/unplayed_games.csv`); teams; membership. They reach the snapshot through `cfp.snapshot.data`, loaded by the command, not through the view. They never change the scoring formula. What they do change: the title list marks title games and keeps one the source files as postseason from being omitted; a forfeit made public by the cutoff sets the certified result, leaves its margin out of the fit and leaves the game out of the head-to-head tiebreak; the unplayed list only explains omissions. A hash of the lists' parsed entries (not of the files' other columns) is in each edition's manifest. A title-list row for a game that is not in the store, and the forecast's pairing columns in that file, change no ledger row, total, rank or included game (`test_annotation_rows_and_columns_change_no_number`); the same holds, snapshot hash included, for a listed game that is in the store and not final, whether or not the source flags it (`test_a_listed_title_game_not_yet_final_changes_no_number`). [K] Enforcement: `cfp.open_ranking` reads only games, teams and membership through `OpenRankingView`, which refuses committee releases, polls, lines, market tables and chair remarks; an edition built with those tables deleted is byte-identical.

**DS-05 [P] Stack and separation.** Python, Polars and DuckDB over versioned Parquet; NumPy for opponent fits; a regularized likelihood fitter for committee ranks; a seeded simulator for field paths. Repeated fit inputs are cached and linear solves batched where possible. Full path recomputation is benchmarked, and any approximation is validated against exact paths near the cutoff before use. Forecast issues are stored separately from subsequent outcomes and scorecards. Code, data manifests and public-source reconstruction instructions are published, subject to feed rights.

**DS-06 [P] Source record.** The release manifest stores the exact source and its effective season for rules, historical fixtures and market conventions. Committee release tables are verified against individual releases. Each conference's tiebreak procedures are archived separately. Scores are reconciled to independent official box scores.

**DS-07 [K] Determinism.** Every random draw uses a recorded seed.

## RL — Release (pp. 4, 10)

**RL-01 [P] Gate.** A release is blocked by broken invariants, missing provenance, conflicting scores or bracket errors. Calibration, sensitivity and rank reversals are published.

**RL-01a [S-pilot] Second implementation state.** Until the second implementation exists, the gate records "second implementation: not run" in the edition manifest and the public page, and does not fail on it. [K] Once it exists, a cross-implementation mismatch outside boundary flags blocks the release, as does a frozen-hash mismatch.

**RL-02 [P] Corrections.** A missed forecast deadline is not repaired retrospectively. A verified score correction is published with its own audit trail. [K] Published editions are never modified; a correction creates a new edition citing the one it supersedes.

**RL-03 [P] Issue proof.** Timestamped hashes are posted before reveals. [S-i] The SHA-256 of the edition bundle is published before the reveal through a signed git tag pushed publicly, an RFC 3161 timestamp token and a public post.

**RL-04 [P] Missing issues.** Missing forecasts and unverified price history are marked explicitly.

**RL-05 [P] Before binding use.** Independent replication and public review are required before binding use.

**RL-06 [P] Pilot (Nov. 24–Dec. 6, 2026).** Feeds are frozen. A ledger and rule tests are published. A simple forecast is issued before the Dec. 1 reveal and Dec. 6 Selection Day. Matched quotes are archived.

**RL-07 [P] Historical replay (Dec. 2026–Mar. 2027).** 2014–25 is rebuilt, including 2023 Florida State and 2025 Miami/Notre Dame case files. Expanding-season forecast tests are run. Official past fields are reproduced. Exceptions, input gaps and model versions are cataloged.

**RL-08 [P] Audit and freeze (Apr.–Aug. 2027).** Independent reviewers attack scheduling incentives, cross-conference dependence, rule exceptions and leakage; results, proposed changes and responses are published. The 2027 policy, metrics, source rules, code hash and forecast contest are frozen before kickoff.

**RL-09 [P] 2027 season.** Open rankings start after Week 7. Two forecast editions are published for each announced reveal. Every eligible issue is graded; the full season scorecard, independent replication and any failed tests are published before requesting adoption.

**RL-10 [P] Trading.** Staff trading stays outside the project's covered markets.

---

## Traceability

Test names are the planned acceptance tests; each build prompt creates them before the implementation.

| ID | Test | Module |
|---|---|---|
| OR-01, OR-01a | `test_ledger_points_unit`, `test_quantize_half_even`, `test_quantize_boundary_flag` | `cfp.open_ranking.link`, `cfp.open_ranking.ledger` |
| OR-02, OR-02a, OR-02b | `test_fit_excludes_team_games`, `test_margin_cap_24`, `test_independent_penalty`, `test_title_game_site_from_data`, `test_no_prior_year_inputs` | `cfp.open_ranking.strength` |
| OR-03 | `test_band_excludes_team`, `test_band_ranks_by_era` | `cfp.open_ranking.band` |
| OR-04 | `test_link_logistic`, `test_link_site_sign`, `test_frozen_hash` | `cfp.open_ranking.link`, `frozen/` |
| OR-05 | `test_title_game_full_weight` | `cfp.open_ranking.ledger` |
| OR-06 | `test_fcs_win_zero_loss_9900`, `test_fcs_excluded_from_fit` | `cfp.open_ranking.ledger`, `cfp.open_ranking.strength` |
| OR-07 | `test_snapshot_omissions`, `test_forfeit_margin_excluded`, `test_game_after_cutoff_excluded`, `test_2020_cancellations_logged` | `cfp.snapshot` |
| OR-08 | `test_ledger_row_fields`, `test_ledger_revision_since_last_edition`, `test_edition_manifest_hashes` | `cfp.open_ranking.ledger`, `cfp.open_ranking.release` |
| OR-09 | `whatif.flip.spec.ts` | `ts/` |
| OR-10 | `test_field_turnover_by_setting` | `cfp.open_ranking.sensitivity` |
| OR-11 | `test_two_paths_same_total`, `test_ten_wins_25500` | `cfp.open_ranking.ledger` |
| OR-13 | `test_stronger_reference_lowers_points` | `cfp.open_ranking.band`, `cfp.open_ranking.link` |
| OR-14, CG-05, RL-05, RL-10 | process requirements; evidence recorded in `docs/DECISIONS.md` and release notes | — |
| OR-12, DS-04 | `test_import_boundary`, `test_open_ranking_view_refuses_forbidden_tables`, `test_open_ranking_runs_without_forbidden_tables` | `pyproject.toml` contracts, `cfp.store.views` |
| TB-01..04 | `test_groups_join_within_2500`, `test_isolated_pair_h2h`, `test_split_series_keeps_points_order`, `test_three_team_cycle`, `test_chained_gaps`, `test_exact_tie_at_cutoff_shared_rank_and_draw` | `cfp.open_ranking.ordering` |
| VT-01..03 | `test_flip_exact_10000`, `test_margin_invariance`, `test_relabel_permutation_neutral_reversal` | `tests/property` |
| VT-04 | as TB-01..04 | `cfp.open_ranking.ordering` |
| VT-05 | `test_rank_reversal_report_complete` | `cfp.open_ranking.audit` |
| VT-06 | `test_replay_rowsums_exact`, `crosscheck` harness | `tests/replay`, `ts/crosscheck` |
| VT-07, VT-07a | `test_calibration_rolling_pregame_only`, `test_calibration_report`, `test_closing_line_report_outside_boundary` | `cfp.open_ranking.calibration`, `cfp.scoring.strength_benchmark` |
| VT-08 | `test_refit_weights_reused_across_folds`, `test_sensitivity_outputs`; also `test_field_function_reproduces_the_published_field`, `test_teams_in_by_guarantee_are_marked`, `test_refits_stop_at_the_time_limit` | `cfp.open_ranking.sensitivity`, `cfp.release.sensitivity` |
| VT-09 | `test_leave_one_interconference_game_out`, `test_no_league_fit`, `test_disconnected_components`, `test_optional_game_skip`, `test_2020_reported_separately` | `cfp.open_ranking.sensitivity` |
| VT-10 | `test_expanding_replay_no_future_seasons` | `cfp.scoring` |
| VT-11, VT-11a | `test_weekly_score_perfect_is_zero`, `test_weekly_score_uniform_hand_computed`, `test_secondary_cohort` | `cfp.scoring.weekly` |
| VT-12 | `test_field_scores_by_stratum`, `test_bubble_cohort_frozen_at_issue` | `cfp.scoring.field` |
| VT-13 | `test_integrity_sums_and_uniqueness`, `test_sim_win_rates_within_mc_error`, `test_within_team_dependence_vs_residuals` | `cfp.scoring.integrity` |
| VT-14 | `test_promotion_rule` | `cfp.forecast.promotion` |
| SC-01 | `test_observation_denominator`, `test_eligibility_flag` | `cfp.forecast.observations` |
| SC-02, SC-02a | `test_cutoffs_sun0200_tminus60`, `test_leaked_label_ineligible`, `test_dst_sunday` | `cfp.forecast.observations`, `cfp.release` |
| SC-03 | `test_baseline1_latest_ap`, `test_baseline2_two_losses_move_ten`, `test_baseline_tiebreak_draw` | `cfp.forecast.baselines` |
| SC-04a | `test_feature_build_matches_edition_on_same_snapshot`, `test_feature_build_without_forbidden_tables`, `test_forecast_manifest_records_feature_build` | `cfp.forecast.observations`, `cfp.open_ranking` |
| SC-04 | `test_pl_gradient`, `test_pl_recovers_weights`, `test_opening_week_drops_prior_cfp` | `cfp.forecast.pl` |
| SC-05 | `test_pl_sample_seed_reproducible`, `test_rank_dist_outputs` | `cfp.forecast.pl` |
| SC-06 | `test_remarks_eligible_next_issue` | `cfp.forecast` |
| FF-01 | `test_futures_prices_not_in_predictor` | `cfp.forecast.final_field` |
| FF-02 | `test_devig_moneylines`, `test_a_zero_independent`, `test_no_tied_scores` | `cfp.forecast.simulator` |
| FF-03 | `test_path_recomputes_open_points` | `cfp.forecast.final_field` |
| FF-04 | `test_baseline_same_paths`, `test_scenarios_when_tiebreak_input_missing` | `cfp.forecast.final_field`, `cfp.forecast.standings` |
| FF-05 | `test_field_and_bye_sums_match_era`, `test_conditionals_with_path_counts` | `cfp.forecast.final_field` |
| FF-06, BR-2025 | `test_rules_2025_official_field` | `cfp.rules.engine` |
| BR-2014 | `test_rules_top_four_2014_2023` | `cfp.rules.engine` |
| BR-2024 | `test_rules_2024_official_field` | `cfp.rules.engine` |
| BR-2026 | `test_rules_2026_on_2025_order`, `test_notre_dame_at_12_and_13`, `test_unranked_aq_ordering` | `cfp.rules.engine` |
| BR-2027, BR-SCHED | `test_rules_2027_byes_and_hosts`, `test_waiver_flag`, `test_ten_game_count_never_excludes` | `cfp.rules.engine` |
| BR-CONTRACT, BR-FIX | `test_field_output_contract`, `test_seed_boundaries` | `cfp.rules.engine` |
| MK-01..03 | `test_quote_filters`, `test_clip_counts`, `test_paired_ll_vs_median_venue`, `test_prereg_hash_precedes_first_issue` | `cfp.markets.contest` |
| CG-01 | `test_lift_sign_and_example`, `test_outside_25_bound` | `cfp.gap` |
| CG-02 | `test_consequence_flags`, `test_provisional_before_selection_day` | `cfp.gap` |
| CG-03, CG-04 | `test_gap_reasons_present`, `test_gap_aggregation_coverage` | `cfp.gap` |
| DS-01, DS-02 | `test_schema_has_provenance`, `test_scored_mode_drops_unknown_vintage` | `cfp.store.schemas`, `cfp.store.asof` |
| DS-03 | `test_row_public_after_t_invisible`, `test_late_correction_invisible_live`, `test_late_saturday_kickoff_invisible_at_sunday_cutoff` | `cfp.store.asof`, `cfp.ingest.public_time` |
| DS-05 | `test_issues_stored_apart_from_scorecards`, `test_approximation_matches_exact_near_cutoff` | `cfp.release`, `cfp.forecast.final_field` |
| DS-06 | `test_manifest_records_sources`, `test_release_cross_checked`, `test_score_conflict_blocks` | `cfp.release`, `cfp.ingest` |
| DS-07 | `test_seed_recorded_and_reproducible` | `cfp.common` |
| RL-01, RL-01a | `test_gate_fails_on_planted_break`, `test_gate_second_impl_not_run_state` | `cfp.release.gate` |
| RL-02 | `test_editions_write_once`, `test_correction_creates_new_edition` | `cfp.release` |
| RL-03 | `test_issue_refuses_after_reveal`, `test_hash_replays_bytewise` | `cfp.release.issue` |
| RL-04 | `test_missing_issue_marked` | `cfp.release` |
| RL-06 | pilot runbook `docs/PILOT.md` and its issue checklist | `cfp.release` |
| RL-07 | `test_rules_official_fields_2014_2025`, case files under `reports/` | `tests/replay`, `cfp.rules.engine` |
| RL-08 | `test_frozen_hash`, freeze checklist | `cfp.release` |
| RL-09 | season scorecard | `cfp.scoring` |
