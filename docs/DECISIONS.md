# Decisions

Format: ID | choice | reason | alternatives. SPEC IDs are added once docs/SPEC.md exists.

## 2026-11-25 — Critical-review suggestions a–l (final build package §1.4)

John accepted all twelve. These are tagged [S] in SPEC.md.

| # | Choice |
|---|---|
| a | Independents get ridge penalty 1/(σc²+σu²); publish Notre Dame's ledger under both penalties. |
| b | Keep the frozen pregame `t` for v1; report leave-one-game-out retrospective calibration as a diagnostic; decide before the 2027 freeze. |
| c | Open Ranking keeps FCS win 0 / loss −99; the CFP "at most one FCS win" rule is stored as a 2027+ eligibility note. |
| d | Integer centipoints: q = round_half_even(p×10⁴); win 10000−q, loss −q, FCS win 0, FCS loss −9900; boundary flag when p×10⁴ is within 10⁻⁶ of a .5 boundary; the Python value is canonical and the cross-check tolerates mismatches only on flagged games; tiebreak gaps are integers (≤2500); display rounds half-even. |
| e | Definitions: ordinary FBS game = a completed regular-season or title game between two teams classified FBS on the game date, not a forfeit; Week 7 = CFBD calendar week 7; cutoff = Monday 06:00 ET after the week's last game; transitioning programs use NCAA status on the game date with CFP eligibility as a separate flag. |
| f | Head-to-head series = every meeting that season, title games included; a 1–1 split keeps points order. |
| g | Title games are included in the strength fit; bowls and playoff games are excluded. **Amendment (accepted with the plan, docs/PLAN.md §5.3):** the site comes from the official site/home designation, not forced neutral, because several title games are played on campus. This overrides the "title games neutral" wording in prompt P04. |
| h | Resolve times in America/New_York and store UTC; on a DST-change Sunday use the later 02:00. |
| i | Prove pre-reveal issue by publishing the edition bundle's SHA-256 via a signed public git tag, an RFC 3161 timestamp token and a public post. |
| j | Add a secondary weekly score on the union of the forecast top 35 and the actual top 25; verify the 2026 FBS count (136 vs 138). |
| k | Bubble cohort = Baseline 2 cohort frozen at issue, used for every model. |
| l | Champion-naming rules are loaded per season as data; the 2027 freeze is blocked until each is published. |

## 2026-11-25 — Naming and repo

- One repository holds everything.
- Public display names: the project and the ranking are **Open Ranking**; the forecasting side is presented as **Open Ranking Models**. (Claude's reading of John's note; the exact wording of the second name was "Open Ranking Models or something like that" and is not final.)
- Internal names in the proposal and code (Shadow Committee, Committee Gap, `cfp.forecast`) are unchanged.

## 2026-11-25 — Sources available

- CFBD API key: available. Odds API key: available. Both live in `.env` (git-ignored).

## 2026-11-25 — Pack installation: departures from the final build package

Made by Claude while installing §5.1–5.5; flagged here for John's review.

- **guard.py is anchored to the project root** instead of substring matching. Reason: the pack's version blocked `ts/src/` in the clean-room session and read-only shell commands naming the frozen-parameters folder. Edits and writes under the editions and frozen folders are still blocked, as are shell commands that name those paths together with a mutating verb (including interpreters and redirects). The hook matcher also covers Grep and Glob so a clean-room session cannot search `src/`. Alternative: keep the pack's version and avoid a `src/` folder under `ts/`.
- **CLAUDE.md has a "Project notes" section** appended after the pack's verbatim text (decision overrides, CLI-only writes to frozen paths, display names, where the prompts live, key names).
- **docs/PROPOSAL.md** is a transcription of the Revised Proposal PDF with page markers; reference URLs were taken from the PDF's link annotations.

## 2026-11-25 — Pilot scope (accepted by John)

- **Pilot track additions.** Cut-down P11 (frozen parameters, labelled provisional), P14 (public ledger edition without the TypeScript what-if), P20 (scoring) and P22 (Gap) join the pilot track. Reason: the pilot cannot produce a ledger or score the 1 Dec reveal without them. Alternative: ship forecasts only.
- **RL-01a.** Until the second implementation exists, the release gate records "second implementation: not run" in the manifest and public page and does not fail on it. Alternative: every pilot release fails the gate.

## 2026-11-25 — SPEC review (spec-guardian) and resulting choices

The reviewer found PROPOSAL.md faithful to the PDF and SPEC.md's numbers verbatim, and listed places where SPEC.md went beyond or fell short of the proposal. Resolutions:

- **[K] tag.** Constraints that come from the final build package rather than the proposal (write-once editions, the OpenRankingView allow-list, hashing the preregistration before the first scored issue, "report complete, not empty", display rounding only at render, post-cutoff games excluded) are kept and tagged [K]. Reason: John approved building with the pack, whose CLAUDE.md and prompts state them. Alternative: drop them to the proposal's weaker wording.
- **VT-07 vs the boundary.** The closing-line benchmark is a report computed in `cfp.scoring`, outside `cfp.open_ranking`, and never selects a parameter. Alternative: carve calibration out of the boundary.
- **Forfeits (OR-07d).** Confirmed by John on 2026-11-25; see "John's rulings" below.
- **Missing requirements added:** OR-13, OR-14, CG-05, DS-06, DS-07, RL-05 to RL-10.
- **SC-04a.** Decided by John on 2026-11-25; see "John's rulings" below.

## 2026-11-25 — P01 store rules (after spec-guardian review of the first P01 commit)

The review confirmed six defects; each now has a test. Choices made (DS-01..DS-04):

- **The lake stamps ingest_time from its own clock.** A caller-supplied value is ignored, so a row cannot be backdated into a past live view. Alternative: trust ingest code to set it.
- **Correction versions are strict per key:** start at 0, rise by one, no gaps, no out-of-order appends. Alternative: any unique version number.
- **A batch lands in full or not at all**, under a per-table file lock; a failed batch leaves nothing and can be retried.
- **Raw payloads are verified on append** (digest format and bytes), and `put_raw` repairs a corrupt copy.
- **OpenRankingView holds no lake.** It is handed a reader that enforces the allow-list again, cannot be subclassed, and lives in a module that imports nothing able to open the lake. PointInTimeView moved to `cfp.store.pit`. Import contracts now forbid the lake transitively for open_ranking, snapshot and rules; a source scan test covers routes imports cannot see. Python has no real privacy: the last layer is still the planned test that deletes forbidden tables and demands a byte-identical edition (P14).
- **Scored reads report coverage through both views**, including the first dropped keys, and can be scoped to a season.
- **`as_of` raises on tied rows** instead of returning both.
- **Replay and scored modes ignore ingest_time** (only live mode requires it). Reason: backfilled history is ingested long after the fact, so requiring it would make every historical replay empty. Consequence: scored replays rest on the first_public_time asserted for reconstructed rows, which is why vintage is tracked. Read strictly, DS-03 asks for both conditions on every forecast query; this is a deliberate narrowing to live issues. Confirmed by John on 2026-11-25; see "John's rulings" below.
- **A row cannot be public after it was ingested** (first_public_time <= ingest_time is enforced). Ingest code must clamp estimated public times to the ingest time. Not in the proposal; a store invariant.
- **Scored mode drops only unknown vintage**, as DS-02 says; reconstructed rows are kept and counted in coverage.
- **Guard hook:** destructive commands are now parsed (including `cd` and quoted or bare folder arguments) rather than pattern-matched.

## 2026-11-25 — Trading policy

- John confirmed that nobody on the project trades the covered markets (playoff qualifier, seed and related futures on the venues the project benchmarks against).

## 2026-11-25 — Hash-proof signing

- Edition tags are signed with an SSH key (git `gpg.format ssh`), configured per-repo. The public key must also be registered on GitHub as a signing key so tags show as verified.

## 2026-11-25 — John's rulings on the three open questions

### SC-04a — open points for forecasts (approved)

Each forecast issue (sun0200 and tminus60) computes open points at its own cutoff as a **feature build**.

- The forecast calls the Open Ranking package's public entry point with a snapshot at the forecast cutoff. There is no second copy of the formula in forecast code. Same frozen parameters and rule_version_id.
- The build reads through OpenRankingView only. The forbidden-tables test covers feature builds as well as editions.
- The forecast manifest's immutable inputs record the snapshot hash, frozen-parameters hash, rule_version_id and a feature_build_id.
- A feature build is never published or labelled as an Open Ranking edition. The Committee Gap's open rank comes only from the published edition frozen before the reveal.
- Test: when a feature build and a published edition share a snapshot hash, their ledgers are byte-identical.
- Replay and simulation paths build the feature the same way, so training and live match.
- Live issues run an ingest immediately before the cutoff, then freeze. A game that goes final after the cutoff waits for the next edition.

**Proposed, awaiting John's confirmation — Selection Day edition (OR-07a).** The weekly cutoff stays Monday 06:00 ET, but that falls after the 6 Dec reveal, so Selection Day gets its own Open Ranking edition: cutoff Sun 6 Dec 2026 02:00 ET (07:00 UTC), published before 11:00 ET (16:00 UTC). Alternative: no Open Ranking edition for Selection Day, so the final Gap would use the 30 Nov edition and miss the title games.

### OR-07(d) — forfeits (approved as read)

A certified forfeit is scored as a normal win or loss at the scheduled site, labelled "forfeit"; its margin is excluded from the fit; it is outside the "ordinary FBS" population the exact-flip test is required for. The arithmetic is not special-cased.

- An unplayed forfeit does not count as a meeting for head-to-head (TB-03).
- Vacated wins are not forfeits. A ruling made public after a cutoff is a later correction and is invisible to replay at that cutoff.
- Forfeits are kept as a hand-verified list in data. A game that looks like a forfeit and is not on the list blocks the snapshot and is logged in DATA_GAPS.md.

### DS-03 — replay ignores ingest time (approved; John's interpretation of proposal p. 10)

Live requires first_public_time <= t and ingest_time <= t. Replay requires first_public_time <= t only.

- Each correction version carries its own first-public time and replay filters on it. "Latest" means latest among those public by t.
- Estimated first-public times must err late. A game with no recorded end time is public at **kickoff + 4.5 hours** (not 3.5). Test: a 22:30 ET Saturday kickoff is invisible at the 02:00 ET Sunday cutoff.
- Vintage travels to every scorecard row. Unknown vintage is excluded from scored tests. Reconstructed is reported separately from authentic.
- Replay output is never labelled prospective. Only live issues count toward the pilot and the market contest.
- Reproducing a published live edition uses the manifest's pinned input IDs, not replay mode.

## 2026-11-25 — P02a/P02b conditions (John) and ingest rules (Claude)

John's conditions:

- Live-call order: fixtures (about 10), the 2026 season, 2014–25 rankings and games, lines last. The call counter is checkpointed after each stage; a stage that runs over twice its estimate stops the run.
- 300 CFBD calls stay in reserve through 30 Nov 2026 unless John says the key has been upgraded.
- Recorded fixtures hold no Authorization header or key, and are trimmed to the rows the tests need. A test fails if a key-shaped string appears under tests/.
- All CFBD backfill rows are vintage "reconstructed" with rule-based first-public times. Rows captured from now on are "live".
- P02b: "archived_authentic" requires a Wayback capture taken within seven days after the reveal whose 25 rows match the parsed release; the capture timestamp is stored. A capture that only predates our ingest is "reconstructed". First-public time is the scheduled show start.
- Every 2014–25 release is cross-checked against CFBD's committee rankings and each 2026 release against a second source. Any mismatch fails the ingest.

Rules Claude chose to carry these out (DS-01..DS-03, DS-06); open to revision:

| Record | first_public_time rule (reconstructed rows) | Reason |
|---|---|---|
| Game, final result | kickoff + 4.5 h | John's ruling; CFBD records no end time |
| Game not yet played | Past seasons: no row is written. Live season: public when we captured it | Superseded 2026-11-25 after review: a 1 Aug rule made unlabelled title games public months early |
| AP / Coaches poll for week N (N >= 2) | the Tuesday 17:00 ET after week N-1's last kickoff | The poll normally appears Sunday 14:00 ET; Labor Day polls slip to Tuesday afternoon |
| AP / Coaches preseason poll (CFBD week 1) | the season's first kickoff | Released in mid-August |
| Closing line | kickoff + 4.5 h, same as the result | CFBD gives no quote time; lines are never a predictor |

- **Rows captured live** use min(rule, capture time), since the store refuses a row that claims to be public after it was ingested. A correction observed live becomes public at the time we observed it.
- **Team and game IDs** at ingest are `cfbd-<id>`. P03 decides the canonical registry and may keep these.
- **title_game** at ingest is derived from CFBD's notes field (regular-season game whose note contains "Championship"). P04 replaces this with a hand-verified list.
- **Postseason polls are not ingested** (never a forecast input; the polls key has no season type). CFBD's copy of the committee rankings is not written to the polls table; it is used from raw only as the cross-check for P02b, because the week-based public-time rule above would be wrong for a Tuesday-night reveal.
- **Past seasons hold results only.** When a schedule became known cannot be read from CFBD, so reconstructed seasons carry no scheduled rows. Replay simulations of remaining games will need a separately sourced schedule table (full track).
- **Budget:** every HTTP attempt counts as a call, including retries. The counter lives in `lake/budget.json` and is written before the request goes out.

## 2026-11-25 — P02b choices made while building (Claude; DS-01, DS-02, DS-06)

- **Primary source** is the CFP site's own data endpoint (`/api/v2/rankings?year=`), one payload per season. All 78 releases from 2014 to 24 Nov 2026 are there with 25 rows each. Alternative: scrape rendered pages.
- **Release numbering** is by date within a season (`cfp-2026-04`); the site's own "week" field is inconsistent across seasons and is not used.
- **Show starts** live in `data/cfp_reveals.csv` with a source URL and quote per row (76 from CFP or ESPN press releases, 2 from news). The 2026 rows were checked by Claude against the CFP's schedule page; the rest were gathered by a research agent and are not independently re-verified. A release with no sourced time cannot be ingested.
- **Team names** resolve through `data/aliases_cfp_site.csv` (98 names, built from ESPN's team list, eight resolved by hand). IDs are written as `cfbd-<id>` using ESPN's numeric ID, on the assumption that CFBD uses the same IDs. P03 must verify that against CFBD once the key works; the 2014–25 CFBD cross-check will also expose any mismatch.
- **"live" vintage for releases** means we captured the release ourselves within seven days of its show, mirroring John's seven-day Wayback window. Alternative: live only if captured before the next release.
- **Authentic copies** are looked for first in the CFP's dated press-release pages on Wayback, then on its rankings page. The old rankings page loaded its rows by script, so it rarely verifies. Unverified releases are "reconstructed".
- **committee_releases gained three columns:** `source_name` (the name as printed), `archive_capture_utc` and `archive_raw_hash` (set only for archived_authentic rows).
- **A later change to a published release** is written as a correction that becomes public when we observed it.
- **Second source by season:** CFBD for 2014–25 (matched by release order; the counts must agree), ESPN for 2026, as John specified.
- **Live-season games (P02a):** the first catch-up of games already played uses the rule time; a result first seen for a game we already held is public at the moment the payload showing it arrived. A game we hold as final is never reverted by the source: the ingest reports it and a person records a correction.

## 2026-11-25 — P02 review round (spec-guardian) and what the real data showed

The reviewer confirmed sixteen defects in the first P02 commit. All are fixed with tests. Choices that changed:

- **The .env loader kept an inline comment as part of a value.** This, not the key, caused the CFBD 401s.
- **"Observed" time is when the payload arrived**, not when the job started. A result that arrives at 02:01 ET is invisible at the 02:00 ET cutoff in live and replay alike (DS-03, SC-04a).
- **One row per game per capture, in its current state.** No scheduled rows are invented for past seasons (see above).
- **Vintage is per row.** "live" means the live system captured the record within seven days of its rule-based public time; the first catch-up of earlier 2026 games is "reconstructed". This narrows John's "rows captured from now on are live" to rows that were actually fresh when captured. Needs John's confirmation.
- **Placeholder kickoff times** (CFBD `startTimeTBD`) start the 4.5-hour clock at the end of that day, Eastern.
- **A weekly poll is dated only when the previous week's games are held**; otherwise the ingest fails.
- **Release numbers come from the schedule file**, and a payload that lacks a release whose show has already aired fails. A missing release can no longer shift the IDs.
- **Finding or losing an archived copy later never writes a correction.** Vintage is fixed at first write, so the Wayback lookup runs before the first ingest.
- **A page verifies a release only if each name ends where the release's name ends** ("3. Texas A&M" does not verify Texas at 3).
- **No switch selects a weaker cross-check.** 2014–25 need CFBD; the live season uses ESPN.
- **Budget file:** written by atomic replace; an unreadable file stops all calls; every CFBD entry point first raises our counter to CFBD's own count.
- **Redirects** are followed only to https on the same host. A response that echoes a key is not archived.
- **Missing classification is stored as "unknown"**, never assumed. A snapshot must resolve it (P04).
- **A game marked completed with no score** stops the ingest if an FBS team is involved; otherwise it is left out and reported. Real data: 5 such games in 2026 (all Division II/III).
- **title_game (provisional)** now needs both teams FBS and a note of the form "<conference> Championship". On the recorded 2025 title week it finds exactly the nine title games; four of them are not neutral-site, which supports amendment g.

Verified on recorded responses: CFBD's week-1 poll is the preseason poll, and its week-11 committee ranking equals the CFP site's first 2025 release, so "the week-N poll follows week N-1's games" holds. Every alias ID equals the CFBD ID of a 2025 FBS school.

**To raise with John:** his ruling makes a release public at the scheduled show start. On Selection Day the full top 25 was read well after the start in some years (about 14:30 ET against a noon start in 2016). That errs early for those releases. Options: keep the show start (current), or use a later sourced time for Selection Day.

## 2026-11-25 — Release cross-check exceptions (DS-06)

- **2023 is checked against ESPN, not CFBD** (John, 2026-11-25: "use ESPN as the second source for 2023 if we need to"). CFBD's copy repeats a rank in two 2023 releases. The exception is a named list in code (`ESPN_SEASONS`); no command-line switch changes the check. Past seasons are read from ESPN's core API, which keeps history; its site API holds only the current season.
- **A postseason entry in CFBD that is identical to the final regular-season release is treated as a copy, not a release** (Claude). Seen in 2014. Alternative: fail the season.
- **2019 is checked against ESPN** (John, 2026-11-25). CFBD lacks the 26 Nov 2019 release.
- **A Wayback outage fails the season's ingest** rather than marking its releases reconstructed, because vintage is fixed at first write. Rerunning fixes it (2017 needed one rerun).

## 2026-11-25 — John's confirmations

- **Selection Day edition (OR-07a):** confirmed. Cutoff Sun 6 Dec 2026 02:00 ET (07:00 UTC), published before 11:00 ET.
- **Selection Day public time:** stays at the scheduled show start, like every other release.
- **"live" label:** John left the choice to Claude. Kept: a row is "live" only when the live system captured it within seven days of its public time; the catch-up of earlier 2026 games and polls is "reconstructed". Reason: the label should mean we held the record when it was fresh, which is what a scorecard reader will assume.

## 2026-11-25 — P03 team identity and membership (plan approved by John; rules by Claude; DS-04, OR-12, BR-*)

- **Canonical team ID stays `cfbd-<id>`.** `teams.espn_id` is filled only where ESPN lists the same number under the same school name, or the pair is on the hand-checked list `data/espn_id_matches.csv`. An FBS team that ESPN does not confirm stops the build; all pass. One non-FBS pair is left unconfirmed (cfbd-108358).
- **Built from archived /games payloads**, which name each side's classification and conference per season. No CFBD calls. A team whose name, classification or conference changes within a season stops the build (none does, 2014–2026).
- **Membership is one row per team per season**, valid 1 Aug to 31 Jul, treated as public on 20 Aug of the season: after conference moves are settled and after the August 2020 opt-outs, before any season's first game.
- **FBS counts are checked** against `data/fbs_counts.csv` (sourced by a research pass, reviewed by Claude). The check uses teams that played: 127 in 2020, when three of 130 members sat out. 2026 is 138: North Dakota State and Sacramento State joined.
- **`cfp_group`** comes from `data/conference_groups.csv`: power / non_power by season, and "independent" for FBS Independents (the research file said non_power with a note on Notre Dame; Claude changed the label so no rule can mistake Notre Dame for a non-power conference member). For 2024–25 the CFP had no formal split; those labels are common usage and are flagged in the file. Bracket rules (P15) read the rule text, not this label.
- **Names resolve by exact match within a source.** An unknown name raises. A name ESPN prints for two schools is left out of the alias list. CFBD prints "Charlotte" for two teams in 2014; the second (cfbd-3253, unclassified, one game) is renamed in `data/team_name_overrides.csv`; ESPN lists that id as "Charlotte Saints", short name "Faith NC".
- **`data/transitioning.csv`** (programs moving up to FBS, with NCAA status and CFP eligibility by season) is stored as sourced data for P04 and the eligibility table; nothing reads it yet.

## 2026-11-25 — P02d Kalshi and Polymarket readers (approved by John; MK-01, RL-06, DS-04)

- **Reading only.** Public, unauthenticated GET endpoints; a test fails if order, account or signing code appears in `cfp.markets`.
- **What is captured** is listed in `data/market_events.csv`: playoff qualifiers, top-four seeds, exact seeds, later rounds, champion, and Kalshi's markets on the next committee rankings. Order books are fetched for qualifiers, top-four seeds and Kalshi's top-4/12/25 ranking markets; the rest store the best quotes carried by the listing.
- **Prices are the Yes probability, 0..1.** A side with nothing resting is null, never 0 or 1. On Kalshi both sides of the book are bids, so the Yes ask is 1 minus the best No bid.
- **Time rule:** a listing or book quote is public at our capture time. Venue history rows (Kalshi hourly candles, Polymarket price series) are public at their own period time and are always vintage "reconstructed"; only quotes we captured ourselves are live. A period the venue later revises is a correction public when we saw it.
- **`market_quotes` gained `kind`** (top, book, candle) in its key; **`market_catalogue`** is new and maps each contract to an event, a question and a team. Both are refused by the Open Ranking's view, and a test scans the predictor packages for their names.
- **Team mapping** uses hand-checked alias files per venue. An unmapped name is stored with no team and reported. Polymarket's closed "Team X" placeholders are stored and not reported.
- **Full depth** is kept in the archived raw payload; the table holds the best bid and ask with sizes.

## 2026-11-25 — P03/P02d review round (spec-guardian)

Twelve findings confirmed; fixed with tests unless noted.
- **False offers.** An ask of 1 (and a bid of 0) is the venues' way of printing an empty side; both are now null. 92 stored Polymarket rows were corrected.
- **Revised candles** were backdated to the period time; they are now public when observed.
- **An event that returns no contract** is reported and the command exits 1. So does an unmapped active name.
- **ESPN ids** are confirmed by name (above). **Alias rows** cite their own source and payload.
- **Forecasts may not import `cfp.markets`** (fifth import contract, with planted-violation tests).
- **Closed contracts** get no quote row.
- **Rows written earlier the same day by the faulty code were removed and rebuilt** (identity tables, venue history). They were hours old, unpublished and fully derived from archived payloads. This is not a precedent: from the first published edition on, the lake changes by correction only.
- **Not changed:** history is hourly, which cannot meet MK-01's 30-minute matching on its own; matched quotes for the contest come from live snapshots, and history is a price path for context. Kalshi's listing is asked for open events only, so a contract's settlement is not yet recorded; that arrives with the contest scoring step. `data/transitioning.csv` is still read by no code (P04).

## 2026-11-25 — John's ruling: who is FBS (S-e, OR-07b, OR-05) and bid eligibility

- **Rule, not a two-team exception.** A team is FBS on the game date if, in that season, it is an NCAA FBS member (including a reclassifying member in its first FBS season) and is a football member of an FBS conference or an FBS independent.
- **Consequences.** Its games against FBS opponents enter the strength fit, score through the normal link and belong to the exact-flip population. Its own games against FCS teams follow the FCS policy. North Dakota State and Sacramento State are ordinary FBS opponents in 2026: a loss to either scores −q, never −9900.
- **Bid eligibility is a separate flag per team-season** (`eligibility.cfp_eligible`), set from sources. True for both newcomers in 2026, citing the NCAA Division I Cabinet decision of 24 June 2026. James Madison 2022–23 is FBS for the ledger and not bid-eligible.
- **Data, with a source per row.** Classification lives in `membership` (`source_url`), eligibility in `eligibility`. If CFBD's classification disagrees with the rule for any team-season, the identity build stops; if a game row disagrees with the membership table, the snapshot stops. Checked on real data: CFBD agrees with the rule in every team-season 2014–2026, including all 37 sourced transition rows.
- **Closed question:** the NCAA's bowl-eligibility counting of "FBS wins" is not an input to the Open Ranking. The empty `counts_as_fbs_opponent` values for 2026 do not matter and need no follow-up.
- **How the rule is applied (Claude):** "an FBS conference" is any conference with a sourced row for that season in `data/conference_groups.csv`. A team-season with no eligibility row is an established member with no restriction.
- Carry-over to P07: `test_loss_to_first_year_fbs_member_scores_minus_q` on the ledger. The snapshot-level test exists now.

## 2026-11-25 — P04 snapshot builder (plan approved by John; OR-07)

- `build_snapshot(view, season, title_games, forfeits, unplayed)` reads only through the Open Ranking's view. It keeps completed regular-season and listed conference-title games with at least one FBS team that were public at the cutoff, and logs every omission with a reason (no FBS team, not final at the cutoff, postseason, cancelled / no contest / never played).
- **Blocks rather than guesses:** a 0–0, 1–0 or 2–0 final not on the forfeit list; a tie; a final with no score; a classification clash with membership; a team with no membership on the game date; a listed title game overdue by three days and absent; a game the source flags as a title game that is not on the list.
- **Title games** come from the hand-verified list, matched by the two teams and the date. The site flag is CFBD's; nothing is forced neutral. A listed title game is kept even if the source files it under postseason.
- **Snapshot hash:** SHA-256 over the kept rows in game-ID order as canonical JSON, including each row's correction version and raw hash. It does not include the cutoff, so a feature build and an edition over the same rows share a hash (SC-04a).
- **Games never played** (2020) cannot come from CFBD, which omits them; they are a sourced list logged in the omissions.

## 2026-11-25 — P02c The Odds API reader (approved by John; DS-01, DS-03, SC-04)

- **Credit cap (Claude, on John's "be realistic"):** the plan is 15M credits a month, shared with John's other projects. This project caps itself at 50,000 a month (0.33%), counted before each request: one credit per market per region, ten times that for historical snapshots. Change `MONTHLY_CREDITS` to move it.
- **What is pulled now:** current moneyline, spread and total for every listed college game from US-region books, 3 credits a pull, hourly with the market snapshots (about 2,200 credits a month).
- **Rows** go to `lines` with provider `oddsapi:<book>`, the home team's spread (as CFBD), public at capture time, vintage live. Prices on spreads and totals stay in the archived payload.
- **Matching:** the API's team names resolve through ESPN display names plus a hand-checked file; an event is tied to the stored game between the same two teams within 36 hours. Anything unmatched is reported and skipped.
- **Not done:** historical snapshots (available from June 2020). They wait for John's plan for this source; the parser already accepts the historical wrapper.
- **Schedules:** `scripts/market_snapshot.sh` runs from John's crontab at five past every hour, and at 01:50 ET Sun 29 Nov, 17:50 ET Tue 1 Dec, and 01:50 and 10:50 ET Sun 6 Dec. It needs this machine awake.

## 2026-11-25 — P04/P02c review round (spec-guardian) and the sourced lists

Sourced lists (research pass, checked by Claude against the store):
- **Title games:** `data/title_games.csv`, 120 rows, 2014–2026. All 112 played games match exactly one stored game, CFBD's neutral-site flag agrees with the list's site type for every one, and all 41 games CFBD itself flags (2022 on) are on the list. Basis is ESPN's scoreboard for 2014–25, so the list and the site flags are not independent of ESPN. Names were changed to the store's spelling (Miami, Hawai'i, San José State). Seven 2026 pairings are not yet known; those rows have blank teams and will block a snapshot three days after the game date until filled in.
- **Forfeits:** none found in 2014–2026 (ESPN statuses for 10,950 FBS events, plus searches on the 2021 conference forfeit policies). `data/forfeits.csv` is header-only.
- **2020 games never played:** `data/unplayed_games.csv`, 105 rows for 90 fixtures (some were called off twice). `no_contest` is assigned by conference policy, not verified game by game.

Review findings fixed with tests:
- A game the source flags as a title game must be on the list even when the list is empty; a blank-team row that is overdue blocks.
- Odds matching used every stored version of a game, so a rescheduled game would have lost its lines; it now uses the latest version, matches either home/away orientation (reporting the stored home team's numbers), and skips games already under way.
- The capture script recovers a stale lock and exits non-zero on failure.
- A forfeit carries the time its ruling became public and is invisible to an earlier cutoff (OR-07d).
- An FBS team's opponent with no known division blocks the snapshot.
- The snapshot hash includes the season; a second hash covers the hand-kept lists so a manifest can pin them.
- `cfp ingest odds` exits 1 when an event cannot be matched.

Accepted, not changed:
- A result that became public after the cutoff appears in the omissions only if a scheduled row was already in the store. For 2014–25 there are no scheduled rows (DATA_GAPS), so those games are simply absent; listing them would mean reading past the cutoff.
- Eligibility rows are public on 20 Aug of their season. An in-season eligibility ruling would need its own dated row.
- Credit counting over-counts slightly on refused or retried requests; that errs safe.
- **For P16:** the hourly job does not ingest CFBD results. The issue pipeline must run the CFBD games ingest immediately before each cutoff (SC-04a), within the CFBD call budget.

## 2026-11-25 — Captures that do not need John's Mac (John approved)

- **Second copy on GitHub Actions.** A private repository, `jpt129/open-ranking-data`, holds a copy of the lake and a workflow (`capture`) that runs `cfp markets snapshot` and, when the `ODDS_API_KEY` secret is set, `cfp ingest odds`, then commits the new files. It runs hourly at :17 and twice in the 40 minutes before each pilot cutoff, because GitHub starts scheduled runs late. It is separate from this repository because this one goes public and the captured data is not ours to republish.
- **Access.** The workflow fetches this repository's code with a read-only deploy key ("open-ranking-data capture (read-only)") while it is private. The key can be deleted once the repository is public. The private half exists only as the `CODE_DEPLOY_KEY` secret.
- **Two independent copies, not one store.** The cloud lake and the local lake each version their own corrections and keep their own request log and credit ledger. Raw payloads and quote rows can be copied across to fill a gap; the tables that carry correction versions (`market_catalogue`) must not be merged file by file. Each copy applies the 50,000-credit monthly cap on its own, so the combined ceiling is 100,000; actual use is about 2,200 a month each.
- **Issue runs (P16/P17).** The issue pipeline is to be built to run on Actions as well as locally: scheduled ahead of the cutoff, with the cutoff enforced by the store's `as_of`, never by when the job starts. A job that starts late must fail loudly, not issue late.
- John keeps the Mac awake as the primary (`pmset`), since the local copy also holds CFBD data.

## 2026-11-25 — P15 (observations, baselines) and P23 (issue pipeline, proof)

John approved both plans and these five choices:
1. **AP votes outside the top 25 come from ESPN** (SC-03). CFBD stores only the ranked 25. `cfp ingest ap-others` reads ESPN's "others receiving votes" and accepts a poll only when its ranked 25, team by team and point by point, equal an AP poll already stored from CFBD; the new rows take that poll's week and public time. Votes for a school that is not a tracked FBS team are skipped. 2026 weeks 2–13 are loaded; earlier seasons are not (DATA_GAPS).
2. **Open points are absent until the ledger exists.** Baseline 2 then orders teams with equal AP votes by the draw alone, and the edition lists `open_points` under `missing_inputs`.
3. **The tiebreak draw was not published before the season.** `data/preseason_draw_2026.csv` was generated and committed on 25 Nov 2026. A team's place is the rank of SHA-256("open-ranking tiebreak draw 2026|<team_id>"), so the phrase is the recorded seed and any language reproduces it. A published draw is never redrawn.
4. **Timestamp authorities:** FreeTSA, then DigiCert. Only the edition's SHA-256 is sent. Both granted a token for a dry-run hash on 25 Nov.
5. **Rank-noise temperature is deferred** until open points exist for past seasons. Until then a baseline is an order without probabilities, and the edition lists `rank_noise_temperature` under `missing_inputs`.

Choices made while building (Claude):
- **SC-03 "sort by adjusted position, then original order"** is applied literally. A team at 3 with two losses has adjusted position 13 and sorts ahead of the team that started 13th, so it lands 12th: its adjusted position moves ten, its final place nine. `test_baseline2_two_losses_move_ten` pins both numbers.
- **"Losses since that release"** are losses in final games that kicked off after the prior release's reveal time. On the opening week the anchor is the latest AP poll, and losses count from that poll's week (the week-N poll follows week N-1's games). Losses to any opponent count, FCS included.
- **Which release is forecast** comes from the sourced reveal schedule. If the schedule says an earlier release exists and the store does not hold all 25 rows of it at the cutoff, the issue is refused; it never falls back to an older release.
- **SC-02a:** Sunday 02:00 is taken in standard time when the clocks go back that morning (07:00 UTC, not 06:00).
- **Issue window (P23):** a live issue is refused before its cutoff (inputs incomplete) and at or after the reveal. It runs just after the cutoff and reads everything through `as_of(cutoff, live)`, so anything ingested after the cutoff is invisible. This replaces the earlier note that a job starting after its cutoff must fail: starting after the cutoff is the normal case; starting after the reveal is the failure.
- **The edition is one canonical JSON document** with no wall-clock time in it, so the same inputs and the same code commit give the same bytes. The time of issue, the tag name and the timestamp authority are in `receipt.json` beside it. `code_hash` is the git commit, with `-dirty` appended if the tree has uncommitted changes.
- **Input IDs** are, per table, the count and a SHA-256 over each visible row's key, correction version and raw payload hash; `ingest_time` is left out so a second store holding the same rows gives the same edition.
- **Edition IDs:** `scw-<season>-r<release number>-<issue>-e<revision>`. A folder that exists is never rewritten; a correction is `--revision 2`.
- **A replay is never prospective.** `prospective_eligible` is true only for a live issue whose label had not leaked.
- **`--now`** (a frozen clock) exists for tests and dry runs and cannot be combined with a proof.
- The headline forecast of an edition is Baseline 2 until the fitted model (P16) exists; the edition says so in `headline_forecast`.

Dry run (scratch copy, replay mode): forecasting the 24 Nov release from the 22 Nov cutoff, Baseline 2 had 22 of the committee's 25 teams with mean rank error 1.64 on those; Baseline 1 had 21 with 2.52.

## 2026-11-25 — P15/P23 review round (spec-guardian) and issues on GitHub Actions

John chose to run issues on GitHub Actions. The `issue` workflow in the private `jpt129/open-ranking-data` repository runs `scripts/issue.sh` from this repository against the lake held there, which is now the store live issues are built from. Each cutoff has four scheduled triggers from two hours before it, because GitHub starts scheduled runs late; the script waits for the cutoff itself and a second run finds the edition already written. The capture and issue workflows share one concurrency group, so only one job writes the lake at a time.

Review findings fixed with tests:
- **Stale results.** A live issue is refused (exit 18) when a game involving an FBS team should be final by the cutoff (kickoff + 4.5 h, within the last 7 days) and is still listed as scheduled. `--allow-unresolved` issues anyway and lists those games in the edition. The script retries once with that flag, so a forecast still exists, with the gap disclosed. A missing newer AP poll is listed under `missing_inputs` as `latest_ap_poll`.
- **Dry runs and replays have their own edition IDs** (`-dry`, `-replay`), are never prospective, and a dry run writes no editions row. They can no longer take the live edition's ID.
- **"Losses since that release" (SC-03), revised.** A loss counts if the game was not yet final at the reveal: kickoff later than the reveal minus 4.5 hours, the same lag used to date results. The first version used kickoff after the reveal, which dropped two 24 Nov games that kicked off 30 minutes before the show and ended after it. Claude's reading of the spec; John has not ruled on it.
- **AP rank ties** fall to open points, then the draw, not to row order. Only games involving an FBS team are examined, so a tied lower-division game cannot stop an issue.
- **Edition folders appear in one step** (staged, then renamed) and the folder is read-only. A run that died after writing the folder and before recording it is repaired by the next run. The timestamp request is tried three times; the tag command has a timeout.
- **A live issue needs committed code:** a `-dirty` or `unknown` code hash is refused.
- **Corrections** carry `supersedes` and are refused if the edition they supersede does not exist.
- `build_issue` moved to `cfp.release.issue`, the module the SPEC table names.
- An AP poll with no "others" votes is now disclosed (`ap_votes_outside_25`) instead of refused, so a failed ESPN read cannot cost the forecast.

Known and not fixed:
- **Leak marking cannot fire from ingested data** (SC-02): release rows are always public at the scheduled show start, so the store never holds a label before its reveal. A real early leak would have to be marked by hand, and no tool does that yet.
- If no timestamp authority answers, the edition is written without a token and cannot be given one later.
- `test_missing_issue_marked` (RL-04) does not exist; missed issues are not recorded yet.
- The token check confirms the status and that the hash is present; it does not verify the authority's signature (use `openssl ts -verify`).

Rehearsal on Actions (25 Nov 18:16 UTC, replay mode, temporary copy): inputs refreshed, edition built and hashed, timestamp token granted. Two steps did not run because their credentials are not there yet: the CFBD results pull (`CFBD_API_KEY` secret) and the signed tag (`ISSUER_KEY` secret; Claude was not permitted to create a write-access key and John must do it).

## 2026-11-25 — P05 (strength engine, OR-02)

John approved the ledger plan (P05, P06, P11-lite, P07, P08) with two scope cuts: plain full refits instead of Woodbury downdates, and no closing-line comparison in calibration for now.

- **Model.** Capped margin = θ_home − θ_away + h·(not neutral); θ = league effect + team deviation. Minimises squared error plus λ_c·Σ(league effects)² + λ_u·Σ(team deviations)². The penalties are on the squared-error scale (noise variance over prior variance). h is not penalised.
- **Independents (OR-02a).** One individual effect each, no league effect, penalty 1/(1/λ_c + 1/λ_u) by default; `independent_penalty="team"` gives the λ_u-only alternative for Notre Dame's second ledger. Independents are the teams whose conference is `fbs-independents`.
- **Evaluated team removed.** `fit(exclude=A)` drops every game involving A and returns no strength for A. `fit_all` gives one such fold per FBS team.
- **Which games.** Snapshot rows with `ordinary_fbs` true and `margin_excluded` false: FBS v FBS, title games included, forfeits out. The site term follows the row's neutral flag.
- **No home games in a fold:** h is set to zero, since nothing estimates it.
- **Order independence.** Rows are sorted by game ID before any arithmetic, so input order cannot change a result. Tests compare for exact equality.
- **Numerics.** Each fold rebuilds and solves the normal equations with numpy (LAPACK). 138 folds on the real 2026 snapshot take 0.04 s. Results are deterministic on one machine; a different machine may differ in the last bits. That is why the ledger will carry only integer centipoints plus the boundary flag (OR-01a), and no floats, in anything that is hashed.
- **Not done:** Woodbury downdates and their equality proof (full track).
- Process note: the tests were written first, but the code was written before a failing run was shown.

Real-data check with placeholder penalties (not calibrated): 697 games, home advantage 2.2 points, SEC the strongest league. The numbers mean nothing until P11-lite sets the penalties.


## 2026-11-25 — P06 (band and link), P11-lite (calibration), P07 (ledger), P08 (ordering)

**P06 (OR-03, OR-04, OR-13).**
- The band is ranks 1–8 for a 4-team field (through 2023), 9–16 for 12 (2024–26), 21–28 for 24 (2027 on). The field size by season lives in `band.py` until the rules engine (P09) owns it.
- Band members are ranked by strength, ties by team ID, and summed strongest first.
- q = Python `round(p·10⁴)`, which rounds halves to even. The boundary flag is set when p·10⁴ is within 1e-6 of a half.

**P11-lite (OR-04, OR-12, VT-07).**
- Objective: pooled log loss of rolling pregame predictions of FBS-v-FBS results, each game predicted from that season's earlier weeks only. Game results are the only input.
- Only games from week 8 on are scored, because the first ledger follows week 7 and the link is never used earlier. (Claude's choice; John has not ruled.)
- A team with no earlier game that season is given its league's effect (zero for an independent).
- Grid: λ_c and λ_u each in {0.25, 0.5, 1, 2, 4, 8, 16, 32}; t from 3.00 to 20.00 in steps of 0.25. Ties go to the first point in grid order. The freeze command refuses a choice on the edge of the grid.
- Result on 2015–2025 (4,132 games): λ_c = 4, λ_u = 4, t = 5.75; log loss 0.5420 against 0.6828 for venue only; Brier 0.1834 against 0.2448. Out of sample (each season scored with parameters chosen on earlier seasons) the model beats venue-only in every season 2018–2025. The surface is flat near the minimum: the six best penalty pairs are within 0.0002 log loss.
- The venue-only benchmark takes its home win rate from the games it is scored on, which flatters it slightly.
- `frozen/params_<season>.json` is written once by `cfp calibrate freeze`, with its SHA-256 beside it, status "provisional". **Nothing is frozen yet**: the file cannot be rewritten, so it waits for John's go-ahead.
- `RULE_VERSION_ID = "or-1.0-pilot"`.
- Not done: closing-line comparison (`test_closing_line_report_outside_boundary`), the leave-one-game-out diagnostic, reliability split by venue and season, the public adoption review.

**P07 (OR-01, OR-05, OR-06, OR-08, OR-11).**
- For team A: one fit without A's games, the band without A, then one row per game. FBS opponent: win 10000 − q, loss −q, title games and forfeits the same. Forfeit rows are labelled `forfeit`. Non-FBS opponent: win 0, loss −9900, no q.
- The site of every game, title games included, is the snapshot's neutral flag.
- An FBS opponent with no fitted strength (no game with a usable margin outside A's) stops the build with an error.
- `revision_cp` is this edition's points minus the last edition's for the same game; a row new since then has none.
- Totals are integer sums. No float is stored in a ledger row except through q; the band strength and home advantage are carried for display only and must not be hashed.
- `test_edition_manifest_hashes` (OR-08) belongs to the Open Ranking release step, which is not built.

**P08 (TB-01..04).**
- Sort by total, then draw position. Adjacent gaps ≤ 2500 join a group. Only a group of exactly two looks at head-to-head.
- The series is every played meeting; forfeits are not meetings. A split is noted and points order kept.
- A pair exactly tied on points and settled by head-to-head gets separate ranks. Any other exact tie shares a rank, listed in draw order.
- `raw_rank` is the rank by points alone. `order` is the total order (head-to-head, then the draw).
- The preseason draw moved from `cfp.forecast.draw` to `cfp.common.draw` so both products can use it.

Real-data check, 2026 season to 25 Nov with the unfrozen parameters above: 138 ledgers in 0.05 s; no row on a rounding boundary; q from 815 to 9971. Not compared with any committee ranking or poll.

Process note: for P11-lite, P07 and P08 the tests were written first, but the code was written before a failing run was shown.

**Spec review of P05–P08 (25 Nov).** No wrong total or order was produced; flips were exact in 294 of 294 cases across three band eras. Fixed:
- An FBS opponent whose only usable games are against the evaluated team now stops the build (before, it was scored at strength zero).
- A null division stops the ledger; duplicate draw positions and a null forfeit flag stop the ordering.
- `rule_version_id` is on every ledger (OR-08).
- The frozen file's hash is written before the parameters, and a reader checks the season inside the file.
- VT-01..03 tests moved to `tests/property`; the relabel test now scrambles names and leagues and checks mapped ranks. Added `test_import_boundary` (renamed) and `test_open_ranking_runs_without_forbidden_tables`. Two tests that asserted nothing were rewritten.

Left open:
- Head-to-head ignores every forfeit, played or not. OR-07(d) excludes only unplayed ones, and `data/forfeits.csv` has no column to tell them apart. The list is empty, so nothing is affected today; a played-then-forfeited game needs a column and a ruling.
- A forfeit against an FCS team is labelled `fcs_win` or `fcs_loss`, not `forfeit`.
- A conflicting conference on a row outside the fit is not checked.
- Calibration orders games by week number, not kickoff time. The reviewer found no scored game in 2015–2025 with a later kickoff in its fit.

**Numerics review of P05–P08 (25 Nov).** No high findings. Measured: worst condition number on the calibration grid 5.9e3; `solve` agrees with Cholesky to 2.5e-13; solver noise moves p·10⁴ by under 3e-9 against a 1e-6 boundary flag; over 22,170 real rows the closest approach to a rounding half was 2.6e-5; four reruns under different hash seeds and thread counts gave identical bits. Fixed: a fit with a condition number of 1e12 or more is refused (two existing tests use near-zero penalties on purpose, at 1.4e8); the boundary flag is always a plain bool. Left open: nothing acts on the boundary flag yet (the release step should print it); band strength and home advantage are floats and must stay out of hashed bytes; no near-tie flag at the band edge.

**Frozen (25 Nov).** John approved the freeze and the week-8 start. `cfp calibrate freeze --season 2026` wrote the 2026 parameters: λ_c = 4, λ_u = 4, t = 5.75, cap 24, status provisional, SHA-256 `c25944752a640cce1c3340293f0a1364a1689b636080751b7a0fa3fd87261566`, at code `4b235dd`.

## 2026-11-25 — Open Ranking release step (OR-08, RL-01a, RL-02)

John asked for the release step after the freeze.

- **One document per edition**, canonical JSON, built by `cfp.open_ranking.release.build_edition` and written once by `cfp open-ranking build --season --cutoff [--mode live|replay] [--revision N] [--previous ID|none]`.
- **Edition ID:** `or-<season>-<cutoff as YYYYMMDDtHHMMz>[-replay]-e<revision>`. Revision N supersedes N−1, which must exist.
- **Manifest:** snapshot hash, lists hash, frozen-parameters hash and values, formula hash, draw hash, code hash, rule version, band ranks, game count, omissions by reason, rows on a rounding boundary, and "second implementation: not run" (RL-01a).
- **Formula hash:** SHA-256 over the rule version, the frozen-parameters hash, the field size and band, the 2500 window, the FCS points, the scale, and the source bytes of `strength.py`, `band.py`, `link.py`, `ledger.py`, `ordering.py`. Any edit to those files changes it.
- **Content:** every team in final order with total, raw rank, group, head-to-head decision, open rank, order, record, band members, rule version and its rows. Everything computed is an integer. The only floats are the three frozen parameter values, copied from their file. Band strength and home advantage are left out.
- **Revision since last edition:** measured against `--previous`, or by default the latest earlier edition of the same kind (live or replay) in the editions folder.
- **Refusals:** a cutoff in the future; a live edition from uncommitted code; parameters from another season or rule version; an edition ID that already exists (exit 17).
- **Not built:** the full gate (`cfp gate`, RL-01), the public post, a signed tag or timestamp for Open Ranking editions, team display names in the document, the rendered page.

End-to-end check on a scratch copy of the lake (replay, cutoffs 22 Nov 07:00 and 25 Nov 12:00 UTC): both editions built; the second measured revisions against the first; a repeat exited 17. With the committee, poll, line and market tables deleted from the copy, both editions were byte-identical (OR-12). A live-mode edition with a cutoff one minute in the past also built. The real `lake/editions` was not touched.

**Spec review of the release step (25 Nov), fixed:**
- **Corrections (RL-02).** `--revision N --corrected-as-of T` builds a new edition with the same cutoff that supersedes revision N−1: it holds exactly the superseded edition's games, re-read as public at T. The document carries both `cutoff_utc` and `data_as_of_utc`. A plain `--revision N` (no later read time) is for a fix to code or a hand-kept list.
- **Crash repair.** If the folder was written and the table row was not, the next run records the row from the folder's own bytes and still exits 17.
- **Previous edition is an input.** Its ID and hash are in the document's `inputs`, so the bytes depend only on declared inputs.
- **The snapshot is published.** `games.jsonl` sits beside `edition.json`; the manifest pins its SHA-256.
- **Formula hash** now also covers `cfp/snapshot/build.py` and `cfp/snapshot/data.py`.
- **Code hash** is read from the repository this code lives in, not the caller's directory (this also applies to forecast issues).
- A cutoff must be a whole minute; a bad time prints a message, not a traceback; live and replay editions cannot be mixed as `previous`.
- Command-level tests added (`tests/unit/test_open_release_cli.py`).

Left open: the lists hash covers every season of the hand-kept lists, so adding a 2027 row changes a 2026 replay's bytes; `revision_cp` does not show rows dropped since the previous edition; "previous" is the latest earlier edition, not strictly last week's.

## 2026-11-25 — Open points in the forecast (SC-04a)

- `cfp.open_ranking.feature.feature_build(snapshot, frozen)` is the public entry point. It runs the same ledger code as an edition; on the same snapshot its rows are byte-identical to the edition's (`test_feature_build_matches_edition_on_same_snapshot`). A feature build is never written as an edition.
- `cfp.forecast.observations.open_points_feature` builds the snapshot through `OpenRankingView` at the issue cutoff. Forecast code holds no formula.
- The issue document (schema 2) records `open_ranking_feature` (feature build ID, snapshot hash, lists hash, frozen-parameters hash, formula hash, rule version), lists `feature:<id>` among its inputs, and gives each Baseline 2 row its `open_points_cp`.
- Feature build ID: `orf:` + SHA-256 of snapshot hash, parameters hash, formula hash and rule version.
- **Effect on Baseline 2:** open points only order teams level on AP standing (in practice, teams with no AP votes), before the draw.
- **If the build cannot be made** (no frozen file, a blocked snapshot, too few teams), the issue still goes out: `open_points` returns to `missing_inputs`, the reason is in `open_points_error`, and the command prints a warning. Claude's choice: a missed forecast deadline cannot be repaired (RL-02), a disclosed gap can.
- The issue command reads `frozen/` and `data/` relative to the code repository, which is where `scripts/issue.sh` runs.

Replay on a scratch copy (tminus60 for the 24 Nov reveal): all 138 teams carry open points; `missing_inputs` is `rank_noise_temperature` only.

**Spec review of the open-points wiring (25 Nov).** No high findings; the feature build reads the same rows as the rest of the issue, and byte replay holds. Fixed:
- "Byte-identical ledgers" is now tested against an edition that has a predecessor: the rows match once `revision_cp` is set aside. `revision_cp` is the edition's comparison with its predecessor, not part of the ledger (Claude's reading of SC-04a; John has not ruled).
- Failures are split. Data conditions (`SnapshotBlocked`, `LedgerError`, `BandError`, `StrengthError`) are disclosed by name. Any other fault is disclosed as "unexpected ..." and the issue still goes out. Claude's choice, for the same reason as before: the deadline cannot be repaired. The reviewer's objection stands on record: a live, prospectively eligible edition can ship while the feature build has a code fault. John to rule.
- When the command cannot load the frozen file or a list, the reason now reaches `open_points_error`.
- `inputs` now also lists the feature's snapshot hash, parameters hash and rule version.

Left open: no test that a row ingested late is invisible to the feature build specifically (the reviewer probed it by hand and it held); the forbidden-tables test removes only the two forbidden tables its world holds; simulation does not exist yet.

Rehearsal on Actions (25 Nov 19:11 UTC, run 45682742188, code `ffe752c`): every step passed and no open-points warning was printed.

**John's rulings (25 Nov, evening).** (1) If the open-points build fails for any reason, the forecast issue still goes out, without open points and with the reason disclosed; an unexpected fault is labelled as such. (2) SC-04a's "byte-identical ledgers" covers every row field except `revision_cp`, which is an edition's comparison with its predecessor.

## 2026-11-25 — P09 (rules engine, BR-*, FF-06)

John approved the plan. Rules and past fields were checked against collegefootballplayoff.com by the rules-verifier before the fixtures were fixed; its quotes and URLs are summarised here.

- **Rules are data**: `src/cfp/rules/seasons/{2014,2024,2025,2026,2027}.yaml`, each with its CFP source URL. `load_rules(season)`; `select_field(rules, order, champions, eligible=, conference_of=, extra_order=, waivers=, qualifying_games=)` returns one entry per team it was told about: rank, qualifier, route, seed, bye, host round, reason.
- **The sixth-conference place (2026, 2027) goes to the highest-ranked team, champion or not.** CFP protocol: "the highest-ranked team from the American, Conference USA, Mid-American Conference, Mountain West, Pac-12 Conference or Sun Belt Conference, along with the next seven highest-ranked teams." The engine therefore needs each team's conference for those seasons.
- **Notre Dame (2026).** "Notre Dame receives an automatic bid if it is ranked in the CFP Top 12 on Selection Day. If so, six (6) at-large bids would be awarded." Built as: if Notre Dame is in the top 12 and would not get in on rank, it takes the last at-large place (route `guarantee`); if it gets in on rank anyway, its route is `at_large`. That it displaces the lowest at-large team is the plain consequence of six at-large places; the CFP does not spell that case out.
- **Seeding.** 2024: "The four highest-ranked conference champions will be seeded one through four and receive a first-round bye"; the rest in rank order. 2025 on: straight by rank; a qualifier outside the top twelve is "seeded at the bottom of the 12 in rank order". Seeds 5–8 host round one.
- **Unranked automatic qualifiers.** The committee orders them itself ("determine their relative positions for seeding purposes"); the engine takes that as `extra_order` and refuses if two such teams must be told apart without it. A team in the extra ordering is seeded below every ranked team. How the CFP would sort an unranked qualifier against one ranked 13–25 is not stated; the engine puts ranked first.
- **2027.** 24 teams; seeds 1–8 bye and host round two; seeds 9–16 host round one. The ten-game count is reported in the reason and a flag, and never excludes a team. A waiver makes a team eligible and is flagged. Not published by the CFP as of 25 Nov 2026: any Notre Dame provision, seeding of an unranked qualifier, what missing the standard costs, how each league names its champion. The 2027 file has no Notre Dame guarantee for that reason.
- **Missing inputs stop the engine**: a named conference with no champion, no conference for a ranked team where one is needed, an order too short to fill the at-large places.
- `band.field_size` now reads the field size from these rules.
- **Fixtures** (`tests/fixtures/cfp_final_orders.json`): final orders from the verified release tables in the lake; champions are title-game winners from `data/title_games.csv` and game results. The 2014–2023 top fours and the 2024 and 2025 top 25s and seeds match collegefootballplayoff.com. The champion lists were cross-checked against Wikipedia only.

**Conflicts with the spec, raised not resolved:**
- BR-2026 and BR-2027 already say "team"; the P09 plan had read it as champion. No spec change needed.
- BR-SCHED says the CFP "permits consideration of at most one FCS win". The source says: "will not give any weight to a win over more than one (1) FCS opponent per season." Same effect, different wording; the 2027 file quotes the source.
- BR-FIX and the plan assume ten champions a season; 2024 and 2025 have nine (the two-team Pac-12 named none).
- Unverified: the 2024 rule sentence for placing a fifth champion ranked outside the top twelve (only the outcome, Clemson at seed 12, is primary).
