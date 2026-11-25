# Fixing the CFP rankings

John Taylor / CFP Research · Revised Proposal · 24 November 2026

> Transcribed from `docs/source/CFP_Rankings_Revised_Proposal.pdf`. Page markers (p. N) follow the PDF so that cross-references and SPEC citations resolve. If this file and the PDF disagree, the PDF wins and this file is corrected.

---

## Proposal overview (p. 1)

An open points system for the season a team earned, and a forecast of the committee's next ranking and final playoff field.

The CFP asks its committee to rank the best teams. Its protocol gives no fixed weights for a stronger résumé, a head-to-head win or an unavailable quarterback. This proposal makes the résumé tradeoffs explicit and forecasts how the committee weighs the evidence in practice. [1]

| Product | Question it answers | Public evidence |
|---|---|---|
| 01 Open Ranking | How many more games did this team win than a bubble team would expect against the same schedule? | An opponent-by-opponent ledger, frozen season rules and a reproducible rank. |
| 02 Shadow Committee | Where will the team rank at the next reveal, and what are its chances of making the final field? | Two timestamped forecasts, each graded against its own baselines. |
| Committee Gap | Where did the committee depart from the résumé standard, and how surprising was it? | Open rank, pre-reveal forecast and actual rank shown together. |

### The boundary between the systems

Both products read the same dated game records and bracket rules. The forecast can use the public résumé score. The Open Ranking's weights and policy settings are chosen independently of committee rankings, poll votes and betting odds. A model can forecast a decision accurately even if the open standard would select a different team.

### What this revision proposes

Count conference title games at full weight. Restrict head-to-head overrides to isolated pairs. Publish uncertainty around cross-conference comparisons. Grade weekly rankings and final-field probabilities separately. Trigger an explanation whenever a disagreement changes a bid, bye or hosting right.

### Where to find the specifications

Open Ranking build and tests, pp. 2–4 • Forecast build and tests, pp. 5–7 • Season rules, p. 8 • Public audit, p. 9 • Rollout, p. 10 • Sources, p. 11

---

## System 1 / Build — Calculate the Open Ranking (p. 2)

A bubble team is a hypothetical team near the edge of the field. Compare actual wins with its expected wins on the same schedule, adapting the wins-above-bubble idea used in college basketball. [8]

### The unit is one hundredth of a win

Game points = 100 × (actual win − bubble win probability). A win counts as 1 and a loss as 0. Sum the game points. For ordinary FBS games, 100 points equals one win above the bubble team's expected total.

1. **Take a dated snapshot.** After Week 7, release the first table using completed games through the announced cutoff. Store game ID, opponents, final score, official site, home designation, FBS/FCS status and conference membership on the game date. Omit canceled games, no-contests and postseason playoff or bowl games. Use the certified result for forfeits, omitting administrative margins from strength fitting.

2. **Rate opponents with the evaluated team removed.** For each FBS team A, remove every game involving A from the strength fit. Fit current-season FBS-versus-FBS margins, capped at ±24. Model margin as the difference in team strengths plus a home advantage, with zero site adjustment on neutral fields. Each team strength equals a conference effect plus a team deviation. Fit both with ridge shrinkage toward zero. Give independents individual effects without a shared league bonus.

3. **Set the reference for that fold.** Exclude A from the bubble candidate pool. Average the remaining FBS strength estimates ranked 1–8 for a four-team field, 9–16 for twelve, or 21–28 for twenty-four. These ranges define a strength standard by era. Record the band members and their average. Estimate the home advantage in the same fold.

4. **Convert the strength gap to win probability.** For opponent j, compute p = 1 / (1 + exp(−d / t)), where d equals bubble strength minus opponent strength, plus the home advantage at home or minus it on the road. On neutral fields, use the strength difference alone. Fit the positive scale t and shrinkage penalties on earlier seasons using pregame predictions of actual FBS results. Freeze these parameters before the season. No team carries over its own prior-year rating.

5. **Publish the ledger.** One row per game shows opponent, venue, result, reference probability, points, policy exception and revision since last week. Add the team total, raw rank, head-to-head decision, final open rank and rule-version ID. Recalculate old wins as evidence about opponents changes. A what-if tool lets readers flip a result and regenerate all ledgers and the bracket. Publish the input snapshot and formula hash with each edition.

---

## System 1 / Scoring policy — What the points reward (p. 3)

The total measures how far a record exceeds schedule-adjusted expectations. With the same opponents, sites and reference probabilities, two 1–1 records earn the same total.

### Two paths through the same schedule

| | Hard game · p = 0.20 | Easy game · p = 0.90 | Total |
|---|---|---|---|
| Upset win, then an upset loss | Win +80 | Loss −90 | −10 |
| Expected loss, then the expected win | Loss −20 | Win +10 | −10 |

A "signature win" already earns full credit. Its value can be offset by a bad loss. Across a full FBS schedule, ten actual wins against an expected 7.45 yield +255 points. This is an arithmetic example. It makes no claim about a particular team.

### Preseason policy decisions

**Conference championship games.** Score the win and loss at full weight wherever a title game is played. In a 50–50 game this yields +50 or −50. Crediting the win fully and halving the loss would award a bubble team +12.5 expected points just for appearing.

**FCS games.** For the Open Ranking, every FCS win earns 0 and every FCS loss costs 99 points. The fixed loss penalty is a disclosed policy choice. Exclude FCS games from the FBS strength fit. This exception gives up schedule neutrality for these games. Official CFP treatment is separate (p. 8).

**Tiebreaks.** Sort by canonical points before display rounding. Form contiguous groups by joining adjacent scores at most 25 points apart. In a group of exactly two, put the head-to-head winner first if the teams met and one won the series. Leave larger groups in points order. A split series keeps points order. Publish shared ranks for unresolved exact ties; if a bracket needs a total order, use an auditable preseason draw attached to team IDs.

**Settings and sensitivity.** Publish alternatives for the strength band, 24-point margin cap and 25-point head-to-head window. Use the same band for selection and seeding in v1. A stronger reference raises its expected wins and lowers the absolute points awarded for any fixed win. The margin of a team's own win cannot raise that team's ledger under the leave-team-out design.

### Adoption decision

Before kickoff, ask the governing group to rank anonymized example résumés under alternate settings. Publish its rationale and each setting's historical field turnover. Choose the values in public; historical committee agreement has no role in selecting them.

---

## System 1 / Verification — Test the ranking before adoption (p. 4)

Test the guarantees the public will rely on. Measure the quality of the opponent ratings separately from the policy judgment about who deserves a bid.

| Test family | Procedure and acceptance condition |
|---|---|
| Points and invariance | Flip each ordinary FBS result with the schedule fixed. The evaluated team's total must change by exactly 100 before display rounding. Change only its margins while preserving results; its total must stay fixed. Rename teams, permute input rows, and rerun neutral-site reversals. Totals and mapped ranks must agree. |
| Full ordering | Exercise a split series, a three-team cycle, chained 25-point gaps and an exact tie at the cutoff. Replay every historical loss-to-win flip through all teams and tiebreaks. Publish any case where the winner's rank falls. Treat "winning cannot lower rank" as unproved unless established for the entire procedure. |
| Point-in-time replay | Rebuild each available weekly snapshot from 2014–25. Pin source hashes, league membership, rule version, dependencies, fixed-point precision and rounding. Check exact row sums and require two implementations to match canonical ledgers, ranks and bracket decisions. |
| Probability calibration | Use rolling, pregame FBS predictions for real teams. Compare Brier score and log loss against a venue-only model; plot observed wins by probability bin, venue and season. Use closing lines as an external schedule-strength benchmark where available. Freeze calibration before grading the next year. |

### How much evidence supports the last bid?

Hold results fixed. Run 1,000 refits with independent exponential weights of mean one for games, reusing each game's weight across every team. Refit the bubble benchmark and bracket. Publish the middle 80% of rank or points differences and the share of refits in which the team qualifies. These measure sensitivity to observed evidence.

Run two further checks: omit each interconference game from the fit, then fit without league effects. Flag disconnected schedules. Test whether skipping an optional game improves bid odds despite forfeiting expected points. Report 2020 separately.

### Release gate

Block releases with broken invariants, missing provenance, conflicting scores or bracket errors. Publish calibration, sensitivity and rank reversals. Require independent replication and public review before binding use.

---

## System 2 / Build the next-reveal forecast — Predict the next committee ranking (p. 5)

The target is the committee's next published top 25. The public sees a team's median rank category, probability of entering the top 25, and probabilities at the bye and hosting cutoffs.

1. **Define the observation.** One training example is one committee release and its complete list of eligible FBS teams. The target contains 25 ordered teams. Each omitted team is known only to be below 25. Include entrants and every unranked candidate in the denominator. A separate eligibility flag records whether the school can receive a bid in that season. Use official CFP releases as labels. [2]

2. **Capture two information cutoffs.** Issue a weekend forecast at 2 a.m. ET Sunday after the Saturday slate and an updated edition 60 minutes before the scheduled reveal. Use only poll releases, completed games and other inputs publicly available by each cutoff. The Sunday edition often has only the prior AP poll. Log actual issue time and immutable input IDs. If any label has leaked publicly, mark that edition ineligible for prospective scoring.

3. **Publish two simple baselines.** First, carry forward the latest available AP order. Second, start with the prior CFP top 25, followed by all other teams ordered by AP votes, then open points. Add five to each team's initial position for each loss since that release. Sort by adjusted position, then original order. Use AP as the opening anchor; break remaining ties by the published preseason draw. For probability comparisons, fit a rank-noise temperature for each baseline on earlier seasons and sample from its full order. Also show its deterministic rank accuracy.

4. **Fit a compact ranking model.** Assign each team a weighted score from available AP vote share, prior CFP position and unranked flag, losses, open points, and the latest result adjusted for opponent, site and capped margin. Standardize on prior training seasons. Fit a regularized Plackett–Luce model: draw one team at a time with chance proportional to exp(score) among remaining teams. Fit against the observed first 25 picks. On the opening week omit the prior-CFP feature.

5. **Produce a distribution.** Sample 10,000 ordered lists with a recorded random seed. Count each team's rank frequencies; group lower ranks as "outside 25." If its median is outside the published list, print that category. Produce pairwise probabilities for bubble comparisons. Calibrate any sampling temperature on earlier validation folds.

### When to expand the model

Try season-varying weights, AP-history priors, team effects, injury status, a boosted ranker and coded chair remarks one at a time. Date each feature. Post-reveal comments first become eligible at the following issue. Add a component only after it improves held-out performance under the test on p. 7.

---

## System 2 / Build the final-field forecast — Simulate Selection Day (p. 6)

This forecast prices a different event. A school can be favored for a top-12 spot on Tuesday and still face poor playoff odds because of its remaining games or automatic bids.

1. **Freeze the state of the season.** Read completed scores, scheduled games, league membership, current standings, championship tiebreakers and polls at the issue cutoff. Store timestamped two-sided game prices where available. Keep team playoff-futures prices out of the predictor; reserve them for evaluation.

2. **Simulate scores for the remaining games.** Normalize the two moneyline probabilities, or convert an as-of spread with a curve trained on past seasons. Use a strength model for unquoted games. Future closing lines are unavailable at forecast time. To correlate games, draw normal team and game shocks. Combine the standardized home-minus-away team shock and independent game shock with squared weights summing to one. The normal CDF gives a uniform draw; the home team wins when it exceeds 1 − p(home). Fit weights on prior seasons. Sample historical margins and totals conditional on win and expected strength; enforce valid, untied scores.

3. **Rebuild each simulated résumé.** Add simulated scores, resolve league standings and play any title games. Recompute open points on each path. Anchor final-rank updates to the actual CFP and AP releases known at issue. Train on variables available both in historical replay and simulated futures. Pool weights with the weekly model; shrink any Selection Day adjustment toward the weekly estimate.

4. **Award actual bids.** Sample a terminal committee order, including an order among potential unranked automatic qualifiers when required. Apply the season-specific rules on p. 8 to produce 4, 12 or 24 distinct qualifiers and their seeds. If an external league tiebreak input is unavailable, publish its scenarios when they alter a bid. [7] On the same paths, score the baseline by updating the last CFP order (AP before the first release) five positions per subsequent loss, as on p. 5. Compare it with the fitted model under identical bid rules.

5. **Aggregate and explain.** Use at least 10,000 paths for public forecasts. Publish P(field), P(bye), P(host) with round identified, and the seed distribution. Also show P(field | win next game) and P(field | lose next game), with path counts. Re-run at larger sample size if simulation noise could explain a reported difference. Separate "field if the season ended today" from this forward forecast.

### Acceptance check from the 2025 field

The rules engine given the official final order and champions must return No. 24 James Madison as seed 12, No. 20 Tulane as seed 11, and No. 11 Notre Dame outside the bracket. This tests rank, eligibility and seed as three distinct quantities. [5]

---

## System 2 / Verification — Score published forecasts (p. 7)

The weekly ranking test and the market test have different targets. Each test specifies its benchmark, timestamp and scoring rule before the outcome is known.

| Test | How to run it |
|---|---|
| Historical replay | Use 2014–16 as an initial training window for the committee model. Forecast 2017 forward one season at a time. Tune features and regularization in earlier chronological folds. Within a held-out season, update only from already released rankings. Store forecaster code, data vintage, issue time and sample seed. |
| Next ranking | Score cumulative P(rank ≤ k) for k = 1…25 against the observed indicator; average squared errors over cutoffs and teams. Report top-25 entrants and exits, exact slots, and rank error on jointly ranked teams with its coverage. Compare AP-as-issued, prior-CFP update and the fitted model. |
| Final field | Score field and bye probabilities with Brier score and log loss. Report by lead time, season, rules era, automatic/at-large route and bubble. Define the bubble in advance as teams within five baseline rank positions of the projected last at-large team. Use the same cohort for every model. |
| Bracket integrity | Validate unique seeds, hosts and byes per path. Sum field and bye probabilities to their respective counts. Test simulated win rates against input probabilities within Monte Carlo error, and within-team dependence against historical residuals. Replay the release hash. |

### The market contest

Preregister venues, settlement events, timestamps and scoring weights. Match team, event and issue. Pilot filters require two-sided quotes within 30 minutes and exchange spreads ≤5 percentage points. Remove book margins or use the exchange midpoint. Archive quotes, depth and exclusions. For log loss only, clip all probabilities to [0.000001, 0.999999] and report clip counts; preserve raw field totals. [10]

Compare paired log loss against the median qualifying venue probability. Report each venue, Brier scores and bubble calibration. Weight seasons equally and average repeated issues within each team, event and horizon. Show matched counts and paired season-level differences. Use season-block intervals with sufficient seasons.

### Promotion rule

Promote only if the primary held-out score improves (weekly rank score or final-field log loss) and bubble Brier worsens by no more than 0.01. Treat one live season as a pilot. Any market claim must identify the venues, events and period beaten. Look for replication across seasons.

---

## Shared implementation / Bracket rules — Version the rules by season (p. 8)

The Open Ranking supplies a public ordering. The Shadow Committee supplies sampled committee orders. Both can use the same tested code to turn an order into a field.

| Season | Selection and seeding to encode |
|---|---|
| 2014–2023 | Four teams. Use the final committee top four in rank order for semifinals. No automatic bids or first-round byes. [3] |
| 2024 | Twelve teams. Five highest-ranked conference champions plus seven at-large. The four highest-ranked champions receive byes as seeds 1–4. Place remaining qualifiers in rank order. [4] |
| 2025 | Twelve teams. Five highest-ranked conference champions plus seven at-large. Top four ranked teams receive byes. Assign outside-top-12 qualifying champions the bottom seeds in rank order. [4] |
| 2026 | Twelve teams. ACC, Big Ten, Big 12 and SEC champions; the highest-ranked team from the other six specified conferences; seven at-large. Guarantee Notre Dame a place if ranked in the top twelve. Top four receive byes. Apply the special ordering procedure for unranked automatic qualifiers. [1] |
| 2027 onward under the announced format | Twenty-four teams. Four named power-conference champions plus the highest-ranked team from the other six conferences and 19 at-large. Seeds 1–8 receive byes and host in round two. Seeds 9–16 host in round one. Load how each league names its champion for that season. [6] |

### Scheduling standards and exceptions

In 2027, the six-conference group is the American, Conference USA, MAC, Mountain West, Pac-12 and Sun Belt. The automatic place goes to its highest-ranked team across the group. The CFP permits consideration of at most one FCS win. Its ten-game scheduling standard counts conference games plus specified nonconference games. For the four power leagues the latter are games against another power-league opponent or Notre Dame; the six-league group also counts games against either group or any FBS independent. The CFP can grant extraordinary waivers. Record official eligibility and waivers; a raw count alone cannot exclude a team. [6]

### Rules-engine contract

Inputs: rank order, official eligibility, conference champions, season rules and any extra committee ordering. Outputs: qualifier, bid route, seed, bye, host round and reason. Add fixtures for a champion outside the top 25, a top-12 Notre Dame in 2026, a below-cutoff automatic bid, a scheduling waiver and each seed boundary.

---

## Public audit / Interpretation — Explain the Committee Gap (p. 9)

Publish the ranking the formula produced, the forecast issued before the reveal, and the committee's actual decision. Those three numbers distinguish a disagreement about merit from a forecasting miss.

| Open rank | Forecast median | Actual CFP rank |
|---|---|---|
| 13 | 9 | 8 |

What happened? In this example, the committee ranked the team five places higher than the Open Ranking. Before the vote, the model anticipated a four-place difference. The committee placed it one spot above the forecast median. Display the pre-reveal 80% rank interval alongside the median so readers can judge whether one spot was surprising.

### How to build the weekly comparison

1. **Join the correct versions.** Match team and reveal ID. Freeze the public formula rank and forecast edition before the announcement. Record the official release separately. Define committee lift = open rank minus actual committee rank; a positive number means the committee ranked the team higher. For an omitted team show "outside 25" and a bound where available.

2. **Compare the consequence.** On Selection Day run both orders through the same eligibility, automatic-bid and seeding rules. Flag every change to a bid, a bye or the right to host, even if only one rank apart. Before Selection Day, show weekly rank differences; identify bracket effects as provisional under the displayed champion scenario.

3. **Publish a reason a reader can inspect.** For teams straddling a cutoff, show ledger differences, decisive games, head-to-head treatment and cross-league sensitivity. Link the chair's dated public explanation and label any additional inference.

4. **Aggregate carefully.** Use that season's conference membership. Report entrants, exits, shared-list mean lift and its coverage. Bound missing ranks. Estimate variability in season blocks. Show how the association changes when poll and conference labels are removed. Sparse matchups and missing variables limit attribution.

### Governance

Launch a shadow ranking first. Seek a written explanation for changes to bids, byes or hosting in the next phase. The governing body decides on adoption after public review. With a binding formula, the simulator can still forecast unresolved bids.

---

## Delivery plan / Ownership and release — From a pilot to a frozen specification (p. 10)

Run the two products as independent releases. A missed forecast deadline cannot be repaired retrospectively; a verified score correction can be published with its own audit trail.

### One data store and two release pipelines

Use Python, Polars and DuckDB over versioned Parquet. Keep source ID, event time, first-public time, ingest time, correction version and raw hash on every record. A forecast query requires first-public time at or before issue time and a record actually available to the live system then. For historical data, tag authentic archived snapshots separately from reconstructed records. Exclude unknown-vintage inputs from the scored test or suppress that forecast and disclose missing coverage. [9]

Run NumPy for opponent fits, a regularized likelihood fitter for committee ranks, and a seeded simulator for field paths. Cache repeated fit inputs and batch linear solves where possible. Benchmark full path recomputation; validate any approximation against exact paths near the cutoff before using it. Publish code, data manifests and public-source reconstruction instructions subject to feed rights. Store forecast issues separately from subsequent outcomes and scorecards.

| Milestone | Owners and evidence required |
|---|---|
| Nov. 24–Dec. 6, 2026 Prospective pilot | Data and product engineers freeze feeds. Ranking lead publishes a ledger and rule tests. Forecast lead issues a simple forecast before the Dec. 1 reveal and Dec. 6 Selection Day. Post timestamped hashes before reveals; archive matched quotes. Mark missing forecasts or unverified price history explicitly. [1] |
| Dec. 2026–Mar. 2027 Historical replay | Ranking team rebuilds 2014–25, including 2023 Florida State and 2025 Miami/Notre Dame case files. Forecast team runs expanding-season tests. Rules lead reproduces official past fields; catalog exceptions, input gaps and model versions. |
| Apr.–Aug. 2027 Audit and freeze | Independent reviewers attack scheduling incentives, cross-conference dependence, rule exceptions and leakage. Publish results, proposed changes and responses. Freeze 2027 policy, metrics, source rules, code hash and forecast contest before kickoff. |
| 2027 season and beyond | Start open rankings after Week 7. Publish the two forecast editions for each announced reveal. Grade every eligible issue, then publish the full season scorecard, independent replication and any failed tests before requesting adoption. |

**Staffing.** Two ranking researchers own the strength and behavioral models; two quant developers own snapshots and replay. A market quant owns simulation and quotes, an ML engineer owns challenger evaluation, a product engineer owns the ledger and scoreboard, and a rules lead owns seasonal rules and acceptance fixtures. Keep staff trading outside the project's covered markets.

---

## Reference notes — Sources and implementation record (p. 11)

Rules, historical fixtures and market conventions are dated inputs. Store the exact source and its effective season in the release manifest. Linked references below were reviewed for this revision.

- **[1] 2026 selection process and dates.** Twelve-team bids, Notre Dame, unranked automatic qualifiers and scheduled reveal times. [CFP committee guide](https://collegefootballplayoff.com/news/2026/11/2/cfp-sc-101) · [CFP voting and seeding protocol](https://collegefootballplayoff.com/sports/2016/10/24/selection-committee-protocol)
- **[2] Historical committee releases.** Primary labels for the ordered top 25 and release dates. Verify tables against individual releases. [CFP week-by-week archive](https://collegefootballplayoff.com/sports/2026/8/9/wk-x-wk-rankings)
- **[3] Four-team playoff.** Historical fields and playoff results. [CFP season history](https://collegefootballplayoff.com/sports/2026/8/10/cfp-history)
- **[4] Twelve-team format changes.** Different bye policies require separate test fixtures. [2024 final order and rules](https://collegefootballplayoff.com/news/2024/12/8/cfp-rankings-241208) · [2025 seeding change](https://collegefootballplayoff.com/news/2025/5/22/2526-seeding-rev)
- **[5] 2025 acceptance fixture.** James Madison, Tulane and Notre Dame establish the difference between rank, seed and berth. [CFP final top 25](https://collegefootballplayoff.com/news/2025/12/7/cfp-rankings) · [CFP field and seeds](https://collegefootballplayoff.com/sports/2026/1/27/cfp-recap-2526)
- **[6] 24-team playoff and scheduling standards.** Bid routes, waivers, FCS wins, byes and host rounds. Verify annual conference championship and scheduling details before freezing a season. [CFP expansion announcement](https://collegefootballplayoff.com/news/2026/11/9/24-team-expansion) · [CFP format guide](https://collegefootballplayoff.com/sports/2026/11/9/24-team-format)
- **[7] Conference tiebreakers.** Example of a league-level rule dependency. Archive each conference's procedures separately. [Big Ten 2026 procedures](https://bigten.org/sports/2026/11/10/FB_1110261447.aspx)
- **[8] Wins-above-bubble precedent.** The NCAA describes comparing actual wins with the wins expected from a bubble team on the same schedule. [NCAA basketball selection criteria](https://www.ncaa.org/news/march-basketball/breaking-down-the-ncaa-division-i-mens-and-womens-basketball-committees-selection-criteria/)
- **[9] Football data and provenance.** Candidate source for games, polls and lines. Verify field coverage, historical vintages and redistribution rights; reconcile scores to independent official box scores. [CollegeFootballData](https://collegefootballdata.com/)
- **[10] Market prices and settlement.** Displayed price conventions and contract-specific settlements. Archive original two-sided quotes and rules for each benchmark venue. [Kalshi playoff qualifier market guide](https://kalshi.com/college-football/playoff-odds)

**Status.** This is a build and validation proposal. Worked point values, the three-rank comparison and test thresholds illustrate or specify the design. Historical backtest scores, measured market performance and real cross-conference intervals remain to be produced.
