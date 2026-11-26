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

**Spec review of P09 (25 Nov).** No high findings; the official 2014–2025 fields and FF-06 reproduce, and output was identical across 200 input shuffles. Fixed, all in the direction of refusing rather than guessing:
- An ineligible champion of a named conference is an error: no source says where that place goes. (Before, the place silently became an extra at-large.)
- One team given as champion of two conferences is an error. Fewer eligible champions than the places for champions (2024, 2025) is an error.
- The group place is never named from one known champion when no group team is ranked: it needs the committee's extra ordering.
- Season files are strict: an unknown key is an error. The 2027 file now stores which games count toward the ten-game standard, the FCS-weight figure, and a list of what the CFP has not published (including how each league names its champion, S-l). Nothing yet reads that list to block a 2027 freeze; the freeze step must.
- A waiver is flagged only for a team that was otherwise ineligible. Reasons name Notre Dame, and say "outside the top four" in the four-team era.
- Tests added for the 24/25 cutoff and the 8/9 and 16/17 seed boundaries in 2027.

Left open: a waiver overrides any ineligibility, though the CFP's waiver covers scheduling only; in 2024, with fewer than four ranked champions, an extra-ordered unranked champion would take a top-four seed (literal to the rule, never happened, unverified).

## 2026-11-25 — Mac fallback for issue triggers

No scheduled run had started in the data repository by 19:38 UTC (capture slots at 18:17 and 19:17 produced nothing); hand-triggered runs work. John chose a fallback on his Mac. A launchd job hand-triggers the `issue` workflow three times before each cutoff, and a second job keeps the Mac from idle-sleeping. Files and removal steps: `scripts/mac_fallback/`. Tested with a one-off job that started a capture run at 19:42 UTC. The old local cron entries (failing hourly since macOS blocks cron from the Desktop folder) were removed. Limits: the Mac must be on, online, lid open, and logged in.

## 2026-11-25 — P17 (simulator, FF-02, VT-13)

John approved the plan and the order (simulator before the fitted ranking model).

- **Modules.** `cfp.forecast.simulator` (probabilities, draws, scores, fits) and `cfp.forecast.sim_inputs` (stored lines to probabilities; fits on past seasons; the slate of games still to play). Not yet called by any issue: the final-field step (P18) will call it.
- **Game probability**, in the spec's order: both moneylines with the margin removed in proportion; else the spread through the fitted curve; else a strength estimate handed in by the caller. Each book's latest quote counts and the median across books is used. A moneyline below 100 in size is dropped and counted. A game with none of the three stops the run.
- **Spread curve.** P(home) = Phi(-spread / scale), scale fitted by likelihood on the seasons before the one forecast. On 9,085 FBS games 2014–2025: 14.65 (2014–19: 14.23; 2020–25: 15.11). Refitted at each issue from what the store shows at the cutoff; nothing is saved.
- **Draws.** x = a(z_home − z_away)/√2 + √(1 − a²)e, home wins when Phi(x) > 1 − p. One generator from the recorded seed; games sorted by id, so input order does not matter.
- **Dependence weight a = 0.034** on 2014–2025 (97,892 pairs of games sharing one team; resampling seasons gives 0 to 0.16 as the 5–95% range; 2014–19 alone 0, 2020–25 alone 0.16). It is fitted by matching the signed product of residuals over those pairs. One number for all teams, as planned.
  - It is measured against closing lines, which already contain everything known about a team at kickoff. Used for games weeks ahead it is a floor, not an estimate: the lake holds only closing lines for past seasons, so the dependence at longer horizons cannot be fitted (DATA_GAPS).
  - In the pilot this has no effect: after 28 Nov the games left are title games and no team plays twice.
- **Scores.** Drawn from past games with the same winning side and the same tenth of pregame probability (a pilot simplification of "conditional on win and expected strength"). Whole numbers, never tied, always agreeing with the simulated winner.
- **Past lines.** History uses each closing line's own quote time; the store marks those lines public four hours after kickoff so a replay cannot see them early, and that rule is unchanged for the forecast season.
- **Finding, no action.** On the 3,771 past games with both, the spread curve scored slightly better than the moneylines (log loss 0.5446 against 0.5475). The spec's order (moneylines first) is kept.
- **Real-data check (25 Nov, 20:00 UTC cutoff).** 71 games left; 70 priced from moneylines; the Conference USA title game (placeholder pairing, no quote) is refused until it has a quote or a strength estimate. 10,000 paths with scores take 0.04 s. Over eight seeds of 200,000 paths the largest gap between a simulated win rate and its input was 2.9 standard errors across 71 games, as chance predicts.
- **Not built:** the strength estimate for unquoted games (P18 has the snapshot it needs); standings and title-game pairings (P18).

**Spec review of P17 (25 Nov).** No numerical or time-leak findings: win rates match at a = 0, 0.5 and 1; the covariance series is within 4.2e-7 of the exact value; the fit's equation has one root; outputs are identical under reordered inputs. Fixed:
- A missing seed was accepted and drew from the operating system. A seed must now be a whole number (DS-07).
- One bookmaker reaching the store from two sources was counted twice; books are now matched by name and the later quote counts. Names that differ between sources (for example William Hill) can still count twice.
- A moneyline pair is dropped and counted when either side is missing, not a number, under 100, or when the two implied probabilities sum below 1.00 or above 1.25. A strength estimate outside 0 to 1 is refused. The slate reports how many books priced each game.
- Quote ties are broken by a full sort, so row order cannot change a price.
- Tests renamed to the spec's names (`test_sim_win_rates_within_mc_error`, `test_within_team_dependence_vs_residuals`, `test_seed_recorded_and_reproducible`) and `test_futures_prices_not_in_predictor` added. The dependence test uses simulated seasons; the measurement on real residuals is the figure above, not a test.

Noted, not changed: a = 0.034 is below what this estimator returns on average when the truth is zero (0.057 in the reviewer's simulation), so it is read as no measurable dependence. A quote's age is not checked. Draws for one game change when another game is added to the slate, so two runs with different slates are not comparable path by path. The 10,000-path floor for public forecasts is enforced where an edition is built, not here. An empty slate is returned as empty; the caller decides whether that is an error.

## 2026-11-25 — John's rulings on the simulator, rank noise, the group bid and the field forecast

John accepted the simulator as built and ruled on the plan for P18 and P19. What was built against each ruling, and what the data showed:

**Simulator.** The per-game three-standard-error test is replaced by one pooled chi-square test over 40 independent games, three weights and three fixed seeds (p > 0.001 both tails). Moneylines stay first. **Open question for the 2027 freeze:** on 3,771 past games with both, the spread curve scored 0.5446 against 0.5475 for moneylines.

**Rank noise (SC-03, SC-05).** `cfp.forecast.rank_noise`, `cfp.forecast.noise_params`, `cfp.release.history`; `cfp forecast fit-noise`.
- Model: orders are drawn one team at a time with chance proportional to exp(−place/τ), place being the baseline's own. τ is fitted by likelihood on the committee's actual 25 picks with the whole field in the denominator.
- Training examples are past issues rebuilt by the live issue code in replay at each cutoff, 2014–2025 (144 issues). Past orders are: prior CFP list plus losses; then AP top-25 standing; then open points at that cutoff (the 2026 frozen parameters applied to each season); then a draw from the same hash rule. Five 2020 issues had no open points (a ledger could not be built that early) and fall to the draw.
- Fitted on 2014–2025, written once to `frozen/rank_noise_2026.json` (SHA-256 `4dec5ead…8578`): Baseline 2 weekly 2.995 (Sunday cutoff) and 2.629 (hour before the reveal); **final release 1.305**; opening 4.647 and 3.443; final seen from two releases back 3.004 and 2.845. Baseline 1: 7.1 to 11.5.
- Forward-chained 2017–2025 the weekly value moved between 3.4 and 3.0 and the final between 1.30 and 1.38.
- Held-out calibration of P(top 25), weekly, hour-before cutoff: forecasts near 0.50 came in at 0.49 and near 0.19 at 0.22, but 0.95 came in at 0.80 and 0.002 at 0.021. The tail is too thin because past "others receiving votes" are missing (DATA_GAPS); the top is too sure because a loss costs more than five places (below).
- A known shape problem: this noise can move the first team only down, so the No. 1 team's median rank prints as 2.
- **Never 0 or 1:** a count of no paths or every path is published half a path short of the edge (0.00005 and 0.99995 at 10,000 paths), with the count beside it. Sums are checked on counts.
- The weekly issue (schema 3) now carries, per team, rank counts for places 1–25 and outside, P(top 25), the median rank category and P(rank ≤ 4, 8, 12, 25); the seed is derived from the edition ID and recorded.

**The six-conference bid (BR-2026).** `cfp.forecast.designations`, `data/committee_designations.csv`.
- The CFP's 24 Nov release page says: "The CFP selection committee selected Boise State as the best team from the remaining conferences." Verified on collegefootballplayoff.com by the rules-verifier. The rankings feed has no such field. Earlier 2026 releases had Boise State ranked. 2024 and 2025 release pages carry no equivalent sentence.
- **Position-26 rule, for John to confirm:** the designated team starts 26th in Baseline 2, ahead of every other unranked team. Reason: the committee has ranked it above every other team of the six conferences, and says nothing about where it stands against unranked teams from elsewhere.
- The row is dated by when we read it (25 Nov 20:15 UTC), because no archived copy proves the sentence was there at publication.
- A release with no group team in its 25 and no designation on file is listed in the issue as a missing input.
- AP "others receiving votes" for the 24 Nov poll are in the lake; the next poll's must be captured before Tuesday's issue.

**Losses and the pilot model (FF-04, VT-14).**
- The baseline counts real losses since the last release as well as simulated ones, five places each, and is labelled "baseline".
- Measured on 2014–2025: in regular weeks the best single drop is **9 places** (likelihood gain of 194 over five, 206.9 after the 2025 polls were re-dated; 118 of 310 ranked one-loss teams fell out of the 25 altogether). In title week it is **4 places** (gain of 8 over five; 70 ranked losers, 5 fell out, mean drop of those still ranked 2.0).
- **Promotion test, held-out Selection Days 2017–2025, issued at the Sunday cutoff:** baseline field log loss 27.59, bubble Brier 0.1046 (85 team-seasons). The pilot model as specified, title-week drop shrunk toward the weekly drop (weight n/(n+10) on its own estimate), scored 28.53 and 0.1075: **it fails**, because the weekly drop is larger, not smaller, than the title-week drop, so shrinking toward it moves the wrong way. Not promoted. The field forecast publishes the baseline alone and says that it drops title-game losers five places.
- Not adopted, reported only: the same model without shrinkage scored 24.90 and 0.0939. It was looked at after the specified model failed, so it is not a clean test.
- Not tested yet: a nine-place regular-week drop for the weekly forecast (held-out likelihood −1531 against −1656 for five; −1480.3 against −1617.5 after the 2025 polls were re-dated, positive in 8 of 9 seasons). It needs the weekly rank score (VT-11) before any promotion.

**Field forecast core (FF-03 to FF-05).** `cfp.forecast.final_field`: per path, simulated results, drops, a sampled order, the season's rules; counts for field, bye, host by round, seed and route; P(field | win) and P(field | lose) with path counts; "field if the season ended today" with each undecided league's best-placed team standing in as champion, shown as an assumption. A named conference with neither a champion nor a simulated title game stops the run. Open points are not recomputed per path (John's ruling); `open_points_on_path` does it and is under test.

**Rehearsal, 2024 and 2025 Selection Days from the release before each** (closing lines from CFBD, not as-of; temperature in-sample; unscored). The rules engine returns both official fields from the official final orders. ΣP(field) = 12 and ΣP(bye) = 4 on both. Teams within three places of the cut:
- 2024 (cut at No. 11 Alabama): SMU 0.620 (in), Indiana 0.948 (in), Boise State 0.636 (in), Alabama 0.584 (out), Miami 0.288 (out), Ole Miss 0.103 (out), South Carolina 0.049 (out). Also Arizona State 0.504 (in), Clemson 0.442 (in).
- 2025 (cut at No. 10 Notre Dame): Texas A&M 0.997 (in), Oklahoma 0.955 (in), Alabama 0.522 (in), Notre Dame 0.677 (out), BYU 0.202 (out), Miami 0.394 (in), Texas 0.190 (out). Also Tulane 0.448 (in), James Madison 0.429 (in).
- The baseline's weakness shows in both: SMU (2024) and Alabama (2025) lost title games and stayed in; the baseline gave them 617 of 4,422 and 734 of 5,517 losing paths.

**Not built yet:** the field edition itself (document, command, workflow step); title pairings with first-public times, scenarios and manifest hash; the strength estimate for unquoted games; the issue-trigger changes (item 7).

## 2026-11-25 — Field forecast in the issue document (FF-01 to FF-05)

John confirmed the position-26 rule and the CFBD schedule as a labelled fallback for title pairings.

- **One edition, one hash.** The field forecast is a section (`final_field`) of the weekly issue document, schema 4, not a separate edition. It shares the issue's cutoff, proof and write-once rule. If it cannot be built, `final_field` is null, `final_field_error` gives the reason, and the weekly forecast goes out whole. It is issued only when the target release is one of the season's last two (the temperatures cover one or two releases back).
- **Pairings** (`cfp.forecast.pairings`), in order: a hand row in `data/title_games.csv` with a source and a new `first_public_utc` at or before the cutoff ("official"); else the schedule in the store at the cutoff when exactly one game on the title date has both teams from that conference ("cfbd_schedule", secondary, labelled); else scenarios from `data/title_scenarios.csv`, each run on its own and never weighted (at most eight combinations); else open. A named conference with no champion, game or scenario stops the section. An open pairing in another conference is disclosed and its teams take no title-game result. The files' hash is in the inputs.
- The three 2026 pairings on file (ACC, Conference USA, Pac-12) are dated 25 Nov 21:00 UTC, when the rows were recorded, not when each league announced.
- **Prices.** A game in progress at the cutoff is unplayed and priced from each book's last quote before kickoff. A game with no quote takes a strength estimate: the Open Ranking's strength fit on the snapshot at the cutoff, through the frozen link (`strength_estimator`). Every game's source and book count is in the document.
- **A title game already final** at the cutoff gives its champion directly. A pairing with no game on the schedule is simulated as a neutral-site game priced from strength.
- **Conditionals** use each team's earliest remaining game.
- **Six-conference place:** filled on every path by the highest-placed team of the group in that path's sampled order (a test asserts one per path). The Open Ranking ranks every team; the forecast predicts the committee's field, so its order starts from the committee's list and uses open points only below it.
- **End-to-end check on real data** with invented pairings in a scratch file (not data): 74 games, 70 from moneylines and 4 from strength, ΣP(field) = 12 and ΣP(bye) = 4, under four seconds. With the real files today the section is refused: "no champion or title game for big-ten: its pairing is not known".

**Spec review of the field section, rank noise and pairings (25 Nov).** No post-cutoff input found. Fixed:
- **High:** games that kick off after the final reveal (Army–Navy on 12 Dec) were simulated and cost a team five places. Only games before the final reveal are simulated now.
- "Field if the season ended today" ignored losses already played; it now applies five places a loss.
- A pairing whose teams are not both in that conference is refused; a conference listed twice in the title file is refused; a final title game with no winner is refused.
- Conditionals check that the named next game was simulated and includes the team.
- Scenarios share the same draws, so two scenarios differ only by the pairing.
- The all-seasons games frame and the lines frame are recorded as inputs when the section is built; both rank-noise seeds are recorded.
- The per-path cache never hit and is removed.

Left open: the CFBD fallback cannot tell a title game from a makeup game between two teams of one conference on the title date (it needs exactly one such game; labelled secondary). `cfp.scoring` and a promotion module do not exist, so the promotion figures above came from scratch scripts and cannot yet be rerun from the repo; VT-12 and VT-14's named tests are missing with them. SC-05's pairwise probabilities for bubble comparisons are not built. A fitted temperature at a search bound is not flagged. A missing temperature for an issue's kind refuses the weekly issue rather than disclosing.

## 2026-11-25 — Leakage audit of the forecast path; 2025 polls re-dated; rank noise corrected (DS-03, DS-07, SC-05)

The audit traced every table read in 2025 replays and found no input public after its cutoff. It found one data fault.

- **Fault.** CFBD files lower-division playoff games in December under regular-season week 1. The poll-dating rule took the latest kickoff of all earlier weeks, so every 2025 AP and Coaches poll for weeks 2–16 was stored as public on 16 Dec 2025. Every 2025 training issue therefore ran on the preseason poll. The error was late, not early, so nothing leaked; it corrupted 12 of 144 training issues.
- **Fix.** Polls are dated from games with an FBS side only. The normaliser refuses two weeks with the same public time. A backfill may now write a re-dated record as a new correction version (`upsert(..., redate=True)`, asserted times only). Re-dated in the working store through the CLI, no API calls: 750 rows for 2025, 100 for 2019 (week 13 was a week late), and the preseason poll of 2014, 2015, 2017, 2019, 2020 and 2024 (first FBS kickoff, later than before).
- **Rank noise corrected.** Frozen parameters are never rewritten, so the refit is `frozen/rank_noise_2026.c1.json` (SHA-256 `b7663e78…27f5`), which names the file it replaces and the reason; the loader reads the latest correction. `cfp forecast fit-noise --correct REASON` writes one. No edition was published from the first file. Baseline 2: sun0200 weekly 2.995 → 2.916, opening 4.647 → 4.073, final 1.305 (unchanged), two-back 3.004 → 2.894; tminus60 weekly 2.629 → 2.549, opening 3.443 → 2.707, two-back 2.845 → 2.737. Baseline 1: sun0200 weekly 11.53 → 9.32, tminus60 weekly 7.21 → 4.45. **For John to confirm.**
- `build_issue` refuses rank-noise parameters fitted for another season.

Open, recorded not fixed:
- The promotion figures and the 2024/2025 rehearsal above were run before the re-dating and are stale for 2025.
- The cloud store still holds the old poll dates for past seasons. No 2026 issue reads them.
- Hand files (`title_games.csv`, `title_scenarios.csv`, `committee_designations.csv`) carry a first-public time but no recorded-at time, so live mode cannot prove a row was on file before the cutoff. The commit that the issue is built from is the only evidence.
- A replay cannot see a past game before its result (one final row per game), so games in progress at a past cutoff and future title games are absent; a two-back field replay of a past season is refused. Live issues are not affected.
- Open points in the training issues use the 2026 parameters, which were calibrated on the same seasons. The temperatures roughly double without open points, so the "held-out" label on 2017–2025 figures is not clean.
- The import contract and the futures test cover `cfp.forecast` but not `cfp.release`.

## 2026-11-25 — Reviews of the fixes, the re-dating and the rank noise (SC-05, DS-03, DS-07, VT-14)

Three reviews: spec check of the fixes, provenance of the poll re-dating, forecasting referee on the temperatures and the promotion claim. No leak and no High finding.

**Audit trail for the re-dating (added after the provenance review).** 1,100 poll rows got a version 1: 750 for 2025, 100 for 2019 (50 for week 13, 50 preseason), 50 each for the 2014, 2015, 2017, 2020 and 2024 preseason polls. Version 1 differs from version 0 in `event_time`, `first_public_time` and `ingest_time` only; version 0 rows remain in the store, which is not in git. The run made one CFBD `/info` call (stage "default"), not none. Baseline 1 changes not listed above: final 7.395 → 4.616; opening 10.50 → 8.22 (sun0200) and 7.08 → 4.28 (tminus60). The first correction file (c1) was fitted from an uncommitted tree and its `code_hash` ends `-dirty`; a second correction (c2) with the same values is written from the committed code so the hash names a commit.

**Fixed after the spec review.** The loader checks every rank-noise file in the chain (gap or changed file stops it). `--report` with `--correct` is refused. A season game with no kickoff time and a tied final title game are refused. `redate` only puts right a record dated too late: one dated too early stays visible at its old version between the two dates (six preseason polls, by a few days, in windows with no issue). Scenarios share a seed, which lines the draws up only when the scenarios have the same number of teams and games.

**Referee: temperatures.** One temperature per cell is sound: leave-one-season-out ranges are narrow (Baseline 2 weekly 2.81–3.00 at sun0200, 2.42–2.61 at tminus60; final 1.28–1.33) and move a published probability by under 0.02 in the cells 2026 still uses. Open points in the training issues are not a material leak: forward-chained Open Ranking parameters give 2.916 and 2.551, under 2% from the frozen values. 2024–25 against 2014–23 is within ordinary season variation.

**Referee: calibration, a concern.** Leave-one-season-out on weekly releases, 6,261 team-forecasts per cutoff:
- P(top 25) near 0.95 came in at 0.76–0.77; 0.986–0.988 at 0.92 and 0.81; 0.998 at 0.94 and 0.92. Teams published at 0.99995 stayed in 710 of 712 and 766 of 768.
- 0.002 came in at 0.022 and 0.014; 0.05 at 0.15 and 0.125.
- P(rank ≤ 12) and P(rank ≤ 4) err the other way: 0.60 came in at 0.85 and 0.94.
- Cause: 77 of the 105 baseline top-25 teams the committee dropped had lost that week; five places is too few.
- Field (2017–25): 0.09 came in at 0.19 (5 of 27).
The issue document now carries these as notes (`rank_noise.notes`, field notes). **For John:** whether to bound published P(top 25) to about 0.003–0.997. Not done: it changes what is published.

**Referee: promotion.** Protocol sound; figures reproduce after the re-dating (27.59 / 28.53 / 24.90). Specified pilot against baseline: +0.94 (season-bootstrap 90% +0.18 to +1.71), bubble Brier +0.0029: not promoted. Unshrunk: −2.68 (−4.55 to −0.86), but examined after the failure, resting on three team-seasons, and outside FF-03's shrinkage: not published. The field note now says this plainly. A nine-place regular-week drop gains 137.3 forward-chained, positive in 8 of 9 seasons; it waits for VT-11 scoring.

Open: `cfp.forecast.pl` and SC-05's named tests (`test_pl_sample_seed_reproducible`, `test_rank_dist_outputs`) do not exist under those names; tests for the duplicate-conference refusal and for field inputs recorded only on success; the 2026 preseason poll is dated from a non-FBS game (27 Aug, live row, still later than the real release).

## 2026-11-25 — John's rulings on calibration and the order of work (SC-05, VT-14)

- **No bound on published probabilities.** The raw baseline is published exactly as the spec defines it, with the calibration notes.
- **A second, labelled "calibrated" column** for P(top 25), P(rank ≤ 4) and P(rank ≤ 12): one monotone (isotonic) map per cutoff from published probability to observed frequency, fitted on the 2014–25 weekly issues. Verified leave-one-season-out, reliability shown before and after per cutoff. Frozen as a hashed file from committed code. It is a **disclosure column, not a promoted model**; both columns will be scored. No map for field probabilities (27 forecasts is too few; the note that forecasts near 0.09 came in near 0.19 stays). Deadline Sat 28 Nov 18:00 ET: if the maps are not verified by then, raw only. An unverified column is not shipped.
- **Confirmed:** `frozen/rank_noise_2026.c2.json` is the file for Sunday's issue.
- **Agreed:** the baseline alone is published; the unshrunk variant stays a note. The nine-place drop waits for the weekly scoring module and then goes through the promotion rule as a candidate; the baseline stays at five.
- **Rule for Sunday:** any output whose test is missing is left out of the edition and listed in its notes.

Done under item 1 of the order of work:
- `cfp.forecast.pl` is the spec-named module for SC-05's published side (sampling and fitting stay in `rank_noise`). `tests/unit/test_pl.py` has `test_pl_sample_seed_reproducible` and `test_rank_dist_outputs`. The per-team summary moved from the issue builder into `pl.rank_summary`.
- **Pairwise bubble probabilities** (`rank_noise.pairwise` in the issue document). The bubble is fixed before sampling, as VT-12 defines it: the teams within five Baseline 2 places of the last at-large team in the field as it stands today under the season's rules (stand-in champions for undecided titles). For each pair: paths on which the row team is ranked ahead of the column team, and the probability. If the field today cannot be worked out the pairs are left out and `pairwise_error` gives the reason.
- Tests added for the duplicate-conference refusal and for field inputs being recorded only when the section is built. `tests/unit/test_issue_field.py` builds a whole issue with a field forecast from a store (four title games, two past seasons of lines) and checks field and bye sums, the six-conference place on every path, recorded inputs and byte-identical rebuilds.
- The hourly capture job fired at 21:17:07 UTC on 25 Nov and its run succeeded.

## 2026-11-25 — The calibrated disclosure column (SC-05; John's ruling)

- **What it is.** `cfp.forecast.calibration`: for each cutoff (sun0200, tminus60) and each of P(top 25), P(rank ≤ 4), P(rank ≤ 12), an isotonic map from the raw published probability to the frequency observed on the 2014–25 weekly releases (6,261 team-forecasts a cell). In the issue document each Baseline 2 row gains `calibrated`; `rank_noise.calibration` carries the label ("a disclosure column, not a promoted model. Both columns are scored."), the file hash and the before and after scores. The raw column is unchanged and a test asserts it.
- **Verification, fixed before the real run.** Leave-one-season-out with the temperature and the map both fitted without the held-out season. A map is published only if held-out log loss is lower than the raw column's and the Brier score no higher. All six cells passed:

| Cutoff | Quantity | Log loss raw → calibrated | Brier raw → calibrated |
|---|---|---|---|
| sun0200 | top 25 | 0.10546 → 0.09240 | 0.02703 → 0.02628 |
| sun0200 | rank ≤ 4 | 0.02585 → 0.01051 | 0.00668 → 0.00244 |
| sun0200 | rank ≤ 12 | 0.03589 → 0.03286 | 0.00991 → 0.00850 |
| tminus60 | top 25 | 0.09367 → 0.08149 | 0.02420 → 0.02379 |
| tminus60 | rank ≤ 4 | 0.02302 → 0.01067 | 0.00587 → 0.00262 |
| tminus60 | rank ≤ 12 | 0.03190 → 0.03129 | 0.00899 → 0.00823 |

  Reliability before and after, per cutoff, is in the frozen file (`verification.cells.*.reliability_before/after`) and printed by `cfp forecast fit-calibration --season 2026 --report`. Example, sun0200 top 25: raw forecasts averaging 0.975 came in at 0.83 and 0.024 at 0.11; calibrated forecasts averaging 0.983 came in at 0.984 and 0.025 at 0.023.
- **Frozen.** `frozen/calibration_2026.json`, SHA-256 `63adf3ea18cc03f4561af74d2b6dab1b913824b45b5a4520cea39a2da632a467`, written once by the CLI from committed code (the command refuses a dirty tree). It records the rank-noise file it was fitted with (c2), the seasons, and the check. The final maps use the frozen weekly temperatures.
- **Weekly releases only.** The maps were fitted on weekly releases, so an issue that forecasts the opening or the final release publishes the raw column alone and says why. That covers Issues 3 and 4 (Selection Day). No map for field probabilities.
- **End steps.** Plain isotonic regression gives 0 or 1 to a step in which the event never or always happened. Such a step is set half an event short instead (0.5/(n+1)), then order is restored. Published values are also held half a path inside the edges like the raw column.
- **Known behaviour, disclosed in the document.** The map is a step function. On today's data it gives Tennessee (No. 5) 0.08 for rank ≤ 4 and every team from No. 6 down 0.0001, because across 2014–25 a team whose raw value was below about 0.3 never moved into the top four the next week. The 0.0001 is the pooled rate over thousands of forecasts, most of them teams far down the list; it overstates certainty for a team just past the step. The calibrated column sums to 25.28 teams, not 25.
- Not tested: the `fit-calibration` command itself (its functions are); the maps on 2026's four releases so far.

## 2026-11-25 — John's ruling on the calibrated column (SC-05)

1. **P(top 25): approved for Issues 1 and 2 as built.** The half-event end steps stay, as does the note that the column sums to 25.28. No renormalising.
2. **P(rank ≤ 4) and P(rank ≤ 12): the isotonic step maps are not published.** A 0.0001 for the No. 6 team is a pooled rate from teams far down the list, and one miss there costs 9.2 in log loss. Instead, for both cutoffs: a two-parameter logistic map on the logit of the raw value (slope and intercept: smooth and monotone), fitted only on teams within ten places of the cutoff rank in the prior release. **Pass rule, fixed before any fit:** leave-one-season-out log loss falls and Brier does not rise on that near-cutoff cohort, and no published value for a team within five places of the cutoff is below 0.01 or above 0.99. Deadline Sat 28 Nov 18:00 ET; if it has not passed, those two columns publish raw only, with the reason stated.
3. Issues 3 and 4 publish raw only. No field map.
4. Before Friday's dry run: run the frozen maps against the three 2026 weekly transitions so far (report only, no refit); a test for the `fit-calibration` command; the reliability report moved into docs/ and committed.
5. **Candidate for after the pilot, not for Sunday:** a raw 0.84 for the No. 1 team staying in the top four with no games played suggests the single rank-noise temperature is too wide at the top. Rank-dependent noise is recorded here as a candidate model; it goes through the promotion rule (VT-14) like the nine-place drop.
6. Title pairings: the field section stays refused until they are on file with sources.

How the pass rule is applied (my reading, for John to correct): "within N places of the cutoff" means the team's place in the starting order (the prior CFP list, then the rest) is within N of 4 or of 12. The 0.01–0.99 bound is checked on every held-out calibrated value for teams within five places, and again on the values an issue is about to publish; if either fails the column is raw only. A calibrated value is published only for teams inside the ten-place cohort the map was fitted on.

## 2026-11-25 — Calibrated column after the ruling: outcome (SC-05)

- **P(top 25): published for Issues 1 and 2, as built.** The isotonic maps in the corrected file are identical to those in the first file (checked value for value).
- **P(rank ≤ 4) and P(rank ≤ 12): raw only. The logistic maps failed the pass rule on its bound clause.** Leave-one-season-out on the near-rank cohort, log loss and Brier both fell in all four cells, but held-out values for teams within five places of the rank ran to 0.0001 and 1.0000, outside 0.01–0.99:

| Cutoff | Quantity | Cohort n | Log loss raw → map | Brier raw → map | Slope | Held-out values within five places |
|---|---|---|---|---|---|---|
| sun0200 | rank ≤ 4 | 672 | 0.2365 → 0.0890 | 0.0622 → 0.0231 | 5.74 | 0.0001 to 1.0000 |
| sun0200 | rank ≤ 12 | 1,008 | 0.2160 → 0.1983 | 0.0606 → 0.0535 | 1.64 | 0.0041 to 1.0000 |
| tminus60 | rank ≤ 4 | 672 | 0.2119 → 0.0878 | 0.0547 → 0.0224 | 5.04 | 0.0001 to 1.0000 |
| tminus60 | rank ≤ 12 | 1,008 | 0.1925 → 0.1782 | 0.0549 → 0.0499 | 1.59 | 0.0014 to 1.0000 |

  The slope is steep because the top four almost never change without a loss: any smooth map that fits that is near 0 or 1 a few places from the rank. The rule was not adjusted. The issue document lists both columns as left out with these figures.
- **Frozen:** `frozen/calibration_2026.c1.json`, SHA-256 `8586eb11d2b4e8faec2f340ff4e26282035e864ef69e447ae9f3388d730b9b98`, written from committed code as a numbered correction naming the first file and the reason. Calibration files now use the same numbered-correction chain as the rank-noise files (the loader checks every file in the chain).
- **Report only, no refit: the frozen maps on the three 2026 weekly releases so far** (releases 2–4, 414 team-forecasts and 75 events a cutoff). P(top 25): log loss 0.1168 → 0.0895 (sun0200) and 0.0789 → 0.0693 (tminus60); Brier 0.0269 → 0.0248 and 0.0231 → 0.0221. The unpublished rank maps, on 42 and 63 forecasts: rank ≤ 4 was worse than raw (0.293 → 0.417 and 0.280 → 0.427); rank ≤ 12 was better (0.173 → 0.123 and 0.155 → 0.115).
- **Reports** are in `docs/reports/`: the leave-one-season-out tables for the frozen file (`calibration_2026.txt`), the withdrawn all-isotonic run (`calibration_2026_isotonic_all_25nov.txt`), and the 2026 check with the four-team table (`calibration_2026_on_2026_releases_25nov.txt`).
- `tests/unit/test_calibration.py::test_fit_calibration_command` covers the command: report writes nothing, an uncommitted tree is refused, one write, a correction is a new numbered file.

## 2026-11-25 — P20-lite: scoring, scorecards and the promotion rule (VT-10, VT-11, VT-11a, VT-12, VT-13, VT-14)

- **What is compared (VT-11).** The spec names AP-as-issued, prior-CFP update and the fitted model. No fitted model was issued (P16 is not built), so a scorecard compares Baseline 1 and Baseline 2 and says "fitted model: not issued". Alternative rejected: leaving the scorecard out until a fitted model exists.
- **S uses path counts, not the published probabilities.** P(rank ≤ k) is the cumulative count over paths. The published values are held half a path away from 0 and 1 for log loss; a squared error does not need that. A team with no forecast row is scored as given no chance. N is the number of teams in the edition's own order, read from the data (138 in 2026), never assumed (VT-11a).
- **An edition with no sampled ranks is scored as a point forecast held with certainty**, and the scorecard says so. Alternative rejected: not scoring it.
- **The calibrated column is scored on P(top 25) alone** (Brier and log loss), beside the raw column on the same teams. It is not put into S, which needs every cutoff from 1 to 25. (John's ruling, 25 Nov.)
- **Scorecards are write-once** under `lake/scorecards/<id>/scorecard.json` with a receipt, written only by `cfp score`. A correction is a new numbered scorecard (`-e2`) that names the one it supersedes. The guard hook and the settings deny list now cover that folder. A scorecard is refused if the release is not in the store, if the time is before the reveal, if no edition was recorded, or if any edition's bytes do not match the hash recorded at issue (VT-13, the hash replays).
- **Prospective or reference.** An edition counts as prospective only if it was marked eligible at issue, its vintage is live, and both its cutoff and its issue time are before the reveal. Replay editions are scored and labelled "reference only".
- **Field probabilities in an edition are checked for integrity now and scored after Selection Day** (VT-12, VT-13). The integrity check (field, byes, seeds and hosts sum to the era's counts) runs on every scorecard. Scoring a live edition's field and bye probabilities against the bracket is not wired into `cfp score` yet; the functions and their tests exist. Due before 6 Dec.
- **Every probability scored by log loss must lie strictly inside 0 and 1.** Editions publish that way; a 0 or 1 means the rows were not built from an edition, and the scorer refuses.
- **A route is scored as its own event** (the chance published for qualifying automatically, or at large, against whether the team did). "auto:*" routes are automatic; at-large, top-four and guarantee are at large.
- **Replay (VT-10).** 2014–16 is the first training window; each later season is scored by a model fitted on earlier seasons only. Sample seeds are hashes of a recorded label (model, season, release, cutoff). `cfp score-replay` writes nothing.
- **The promotion rule is code (VT-14)**: `cfp.forecast.promotion.decide`. Strict improvement in the primary score, bubble Brier no more than 0.01 worse, at least two held-out seasons. If bubble Brier was not measured for both models the answer is "cannot be applied", never yes. The code reports; John rules.
- **The title-week comparison now reruns from the repo** and matches the scratch run within sampling noise: field log loss over 540 team-seasons, 2017–2025, baseline 27.79, specified shrunk pilot 28.53, unshrunk 24.87 (scratch: 27.59 / 28.53 / 24.90); bubble Brier 0.1054 / 0.1075 / 0.0942 on 85. The rule's arithmetic passes the unshrunk variant, but it was only looked at after the specified one failed, so the 25 Nov ruling stands: note only, not promoted.
- **Nine-place regular-week drop, report only.** Held-out weekly rank score 2017–2025, 70 releases: five places 0.010836, nine places 0.008808, better in 9 of 9 seasons. Two cautions. Nine was not fitted inside each fold; it came from an earlier fit on all seasons, so this is not yet a clean test. And the rule's second clause cannot be applied: a regular-week drop changes the field forecast only before Selection Day, and those past field forecasts cannot be rebuilt, so there is no bubble Brier to compare. Needs a ruling on what stands in for it. The baseline stays at five.
- **A mistake caught on the way.** My first rerun gave 32.26 / 32.73 / 30.79 because I built the past issues without the frozen Open Ranking settings, so teams below the ranked 25 were in draw order instead of open-points order. The store was unchanged. `cfp score-replay` passes the settings; the test for it does not cover that argument.

## 2026-11-25 — P14-lite: release gate and public page (RL-01, RL-01a, OR-08, OR-09)

- **The gate checks a written edition from its own files** (`cfp gate <edition>`): the hash against the receipt and the store; the games file against the manifest and the snapshot hash; every total is the sum of its rows; every row obeys the arithmetic (win 10000 − q, loss −q, FCS win 0, FCS loss −9900, title games the same formula at full weight); every row matches its game and every game is in its teams' ledgers; no game kicks off after the data cutoff and each carries its raw-source hash; the frozen parameters and formula hash match; a rebuild from the published games gives the same bytes; ranks are in one order; the second-implementation state. Any failure blocks publication. A check that cannot run counts as failed.
- **Second implementation (RL-01a):** "not run" is recorded in the manifest, the gate report and the page, and does not fail the gate. Any state other than "not run" or "match" fails it.
- **"No input after the cutoff" is checked from the published games file**, which carries kickoff times and raw hashes but not first-public times. The first-public-time rule is enforced where the snapshot is read (`as_of`); the gate's check is the part a reader can repeat from the public files.
- **`cfp publish --edition <id>`** runs the gate and refuses if it fails. It writes `site/open-ranking/<id>/` (edition.json, games.jsonl, gate.json, index.html) and refreshes `site/open-ranking/latest/` only if this edition's cutoff and revision are not older than the one shown. Publishing the same bytes again changes nothing; different bytes under the same id are refused. The gate report sits beside the public files, never in the write-once edition folder. Pushing `site/` anywhere public is John's step. (John's approval of the plan, 25 Nov.)
- **The page says what the pilot does not include:** sensitivity intervals, the rank-reversal report and the what-if tool are each listed as not delivered in the pilot (OR-09 allows this for what-if; for the other two RL-01 says they "are published", and John approved listing them as not delivered). It also states that the settings are provisional and that the second implementation was not run. Points are shown to two decimals; the whole centipoints in edition.json are the record.
- **Rehearsal** on a scratch copy of the store, replay edition at the 22 Nov cutoff: 138 teams, 819 games, 1,511 rows, all ten checks pass, page 265 KB.

## 2026-11-26 — Spec reviews of P20-lite and P14-lite: what was fixed and what is left open

**Scoring (VT-10 to VT-14). Fixed:**
- **Every model is now scored on the same noise draws.** Seeds are labelled by season, release, cutoff and path count, never by model. Before, a strict-improvement test carried about 0.3 of sampling noise in field log loss. Figures on common draws, 2017–2025: weekly rank score 0.010838 (five places) against 0.008817 (nine), better in 9 of 9 seasons; Selection Day field log loss 27.46 baseline, 28.40 shrunk pilot, 24.76 unshrunk (Sunday cutoff; 27.75 / 28.64 / 25.01 at reveal −60, a gap inside sampling noise). No ruling changes.
- **The replay now scores Baseline 1 and every kind of release** (opening, weekly, Selection Day list), with exact slots, rank error and entrants/exits called. Held out: opening 0.01902 (AP) against 0.01527 (Baseline 2); weekly 0.01906 against 0.01084; final list 0.01418 against 0.00661.
- **Prospective status also needs the store's own ingest stamp to be before the reveal**, and an edition whose own reveal time or release number differs from the release being scored is refused. A superseded revision is not counted as prospective.
- **A missing champion refuses the Selection Day replay.** A past title game with no teams on file, or one that cannot be matched to a single final game, is a problem, and the field scores are not computed.
- **`cfp score-replay` prints the store's as-of time and can write its full record** (seeds, fitted temperatures and drops, by-era and by-route scores) with `--out`.
- The scorecard field is now `hash_matches_issue` (the bytes match the hash recorded at issue; it does not claim a rebuild). The promotion rule treats a score that is not a number as "cannot be applied".

**Scoring. Open, not fixed:**
- **The folds are not clean of the Open Ranking settings.** Past issues order teams below the ranked 25 by open points computed with the 2026 settings, which were fitted on those same seasons' game results. The 2017 fold therefore uses settings that saw later results. This is not a Boundary breach (no committee data is involved), but it is leakage of game results across folds, and it applies equally to the frozen rank-noise and calibration fits, which use the same history. The command prints the caution. A clean fix needs settings fitted per fold. Needs John's ruling on priority.
- The "actual" field in the replay is the rules applied to the committee's final list and the title-game winners, not an official field list. The 2024 and 2025 brackets match the rules fixtures.
- Per-path bracket uniqueness (`check_path`) is tested but is not run on simulator output; published sections are checked by their sums. A failed integrity check is printed as a warning and recorded in the scorecard; it does not stop the scorecard.
- Numbers that are in neither the proposal nor the spec, recorded here: at least 2 held-out seasons before the rule can say yes; 60 places of the starting order scored per Selection Day; shrink weight 10; drop grid 0 to 10 in halves.

**Gate and page (RL-01, RL-01a, RL-02, OR-08). Fixed:**
- **Games are checked against the edition's cutoff, not its later read time**, and a correction must hold exactly the games of the edition it supersedes.
- **The previous edition must be the one the store recorded.** The gate now takes the store's hashes for every edition.
- **Publishing is once per edition.** An already published folder is left untouched; a new one appears whole (staging folder, then rename). `latest` is swapped as a whole folder, and a replay edition never replaces a live one.
- The page now shows the change since the last edition per row, each team's raw rank and head-to-head decision, and the snapshot hash. It also lists the calibration report and the bracket as not delivered in the pilot.

**Gate. Open, not fixed:**
- The rebuild uses the same code as the build, so it proves the bytes follow from the published games, settings and draw; it is not an independent implementation (that is P13). The omission counts, the lists hash and the code hash are taken from the document and are protected only by the hash the store recorded at issue.
- RL-01's "conflicting scores" is not a gate check: the gate sees one games file. RL-01's "bracket errors" has nothing to check, because the pilot edition carries no bracket. Team names on the page come from the store's teams table when the page is first written.

## 2026-11-26 — P22-lite: Committee Gap (CG-01, CG-02, CG-03, CG-04)

- **`cfp gap --release <id>`** writes one write-once report to `lake/gaps/<id>/gap.json` (guard and deny list extended). A correction is a new numbered report.
- **Which editions are compared (John's approval, 26 Nov).** The Open Ranking edition is the latest recorded live one whose cutoff, issue time and store stamp are all before the reveal; with none, the report is refused. The forecast is the latest prospective edition for that reveal (reveal −60 if there is one, else Sunday). With none, the forecast columns are empty and the report says no forecast was issued (RL-04). In replay mode, editions rebuilt later from a cutoff before the reveal are used and the report is marked reference only.
- **Lift = Open Ranking rank − committee rank** (shared ranks as published). A team the committee left out is 26th or lower, so its lift is a bound ("at most open − 26"). "Anticipated" is open rank − forecast median; "beyond forecast" is median − actual. Worked example in the tests: open 13, median 9, actual 8 gives 5, 4 and 1.
- **The 80% interval** is the rank range with at most a tenth of the forecast's paths beyond each end, from the edition's own path counts. The report also gives the forecast's chance of the committee's rank or better.
- **Consequence flags** run both orders through `field_today` and the season's rules and flag every difference in bid, bye or home game. Before Selection Day they are provisional: an undecided conference's best-placed team in each order stands in for its champion, and the stand-ins are listed (John's approval). Teams the committee did not rank follow its 25 in Open Ranking order; that only matters when an unranked team would be a champion stand-in. On Selection Day the real champions are required, and a title game that cannot be matched refuses the report.
- **Reasons (CG-03)** are given only for pairs on either side of a flagged change: ledger difference, each team's three largest rows, the head-to-head series and the Open Ranking's treatment of it, and any chair remark on file for the release. Cross-league sensitivity is "not delivered in the pilot". No inference about the committee is added.
- **Aggregation (CG-04):** teams on both lists, coverage, mean and mean absolute lift, the one-list-only teams with bounds, and lift by that season's conference. Variability by season block and the association with labels removed are stated as not estimated in the pilot.
- **Rehearsal** on a scratch copy against release 4 (reference only): 22 teams on both lists, mean lift size 2.86 places; six provisional bye/host changes (Alabama, Notre Dame, Texas Tech, Wake Forest), no bid changes.

## 2026-11-26 — Spec review of P22-lite: what was fixed and what is left open

**Fixed:**
- **A Selection Day report no longer says "final" when the committee's field depends on the Open Ranking's order (CG-02).** The committee publishes no order below 25, so unranked teams follow its 25 in Open Ranking order. If one of them reaches the committee's field (an unranked champion, or the six-conference place), the report lists it under `committee_field_from_tail`, is marked provisional, and says that place cannot be flagged. This also applies before Selection Day.
- **Editions are chosen by what their data saw (CG-01).** An Open Ranking edition whose data was read after the reveal is passed over in both modes, so a later correction never stands in for the edition frozen beforehand. A forecast edition must have a cutoff before the reveal and must have been issued for this reveal. Editions passed over are listed in the report with the reason.
- **Revisions sort by number**, so e10 is after e2.
- **A replay report has its own name** (`gap-<season>-rNN-replay-eK`), so a rehearsal can never take the live report's place.
- **Bid eligibility comes from the store's eligibility table** (eligible unless a sourced row says not), not from the forecast edition, so it is the same with or without a forecast.
- A Selection Day report with an unreadable title-games file is refused cleanly.
- The head-to-head series uses school names and says "tied" for a split. The report states that "decisive games" is a display rule (each team's three largest ledger rows); three is not in the proposal.
- Tests added: what the report reads from a real store (frozen before the reveal, rebuilt and late editions excluded, changed file, missing champion); head-to-head with both ledgers, a split and two meetings; a bid change one rank apart; the Notre Dame guarantee; Selection Day with differing orders; the interval across the edge of the 25.

**Open, not fixed:**
- The six-conference place and any unranked champion on the committee's side cannot be flagged at all, for the reason above. A committee order below 25 does not exist to use.
- If a forecast correction is issued after the reveal, the gap uses the earlier edition (the one frozen beforehand) and lists the correction as passed over; `cfp score` treats that earlier edition as superseded and not prospective. The two reports can therefore name different statuses for one edition.
- Under the 2024 and 2025 rules (no named conferences) a Selection Day report is not refused for a missing champion; it comes out provisional. Replay only.
- A conference whose best-placed team is ineligible refuses the whole weekly report (stand-in choice ignores eligibility; shared with the forecast's "field today").
- Nothing checks how old the Open Ranking edition is; its cutoff is now printed in the report.
- Scorecards still share one name between live and replay runs.

## 2026-11-26 — Cloud rehearsals on `716f654`, and a stale store checkout in the data repository's workflows

- **Run 45760598818 (05:17 UTC) failed at its last step.** The issue itself finished (replay edition `scw-2026-r04-sun0200-replay-e1`, SHA-256 `30ecdd31…2c3d64`). The store commit then hit a rebase conflict in `lake/fetch_log.jsonl`.
- **Cause.** The run was triggered nine seconds after the :17 hourly capture and waited for the shared `lake` lock. `actions/checkout` checks out the commit that was the tip when the run was triggered, not the tip when the job starts, so the run began from a store without the capture's commit. Both runs appended to the same log.
- **Run 45760929973 (05:20 UTC), started clear of a capture, passed every step** with the same edition hash.
- **Not fixed.** The fix is `ref: ${{ github.ref_name }}` on the store checkout in both `capture.yml` and `issue.yml` in `jpt129/open-ranking-data`. It has not been applied; it needs John's go-ahead. Until then, any run that queues behind another writer can fail to commit. For a live issue that would leave a written edition unpushed.
- **Fixed later the same day (John's go-ahead).** Both workflows now check out the store at the branch tip (`37bcf6a` in the data repository). **Proof:** run 45767143183 was triggered at 06:17:13 UTC, six seconds behind the 06:17 capture, and waited on the lock. It checked out `cd33363`, the commit that capture had just pushed, and committed `4016de4` on top with no conflict. Every step passed, on code `98e8bfb`.

## 2026-11-26 — Field and bye outcome scoring in `cfp score` (VT-12, VT-13)

- **When.** Only the Selection Day scorecard scores the field: the release whose number equals the count of that season's rows in `data/cfp_reveals.csv`. Every other scorecard has `field_outcome: null`.
- **What is scored.** Every forecast edition of the season that carries a field section, including the title-week editions issued for the release before. Each is marked prospective or not against its own reveal. The weekly rank scores stay per release as before.
- **The actual field** is the season's rules applied to the committee's final list, the store's eligibility table, that day's conference membership and the title-game winners on file. It is not an official field list, and the scorecard says so. It is refused, with the reason, if a champion is missing or the six-conference place would go to a team the committee did not rank.
- **If the field cannot be scored, the scorecard is still written** with the weekly scores, `field_outcome.scored = false` and the reason, and the command prints a warning. A later revision scores the field once the gap is filled. The field is never guessed.
- **Population.** Every team the edition listed (all FBS teams). A team with no paths was published half a path from zero and is scored at that. The replay scores 60 places; the scorecard scores all, because the edition published all.
- **Bubble** is the cohort the edition fixed at issue (`rank_noise.pairwise.teams`). An edition with none has no bubble score; none is made afterwards.
- **Scenarios** are scored one by one. None was weighted at issue, so no combined score is given.
- **Routes.** A team's published chance of an automatic place against whether it took one; likewise at-large, where at-large means every non-automatic route (top four, guarantee, at-large).
- Not yet run on a real field section: no edition with one exists until the title pairings are on file.

**Spec review of the field scoring (26 Nov).** The review found the arithmetic and route mapping correct, and `actual_field` reproduces the real 2024 and 2025 fields from the store. Fixed:
- An edition elsewhere in the season that cannot be read no longer refuses the scorecard; it is listed under `field_outcome.unreadable`.
- Each scored field section carries its own integrity result (VT-13), including title-week editions issued for the release before. A section that fails is still scored and is flagged.
- Any failure while working out the field (title-games file, eligibility, champions) ends as `scored: false` with the reason. A reveal schedule that cannot be read refuses the scorecard cleanly.
- An edition whose field could not be scored is no longer labelled as scored.
- An earlier-release edition is judged prospective against the store's release for its season and number; a document whose own reveal time differs is not prospective.
- Under rules with no named conferences (2024, 2025), every FBS conference's champion must be on file, so a missing one can no longer shift the fifth automatic place silently.
- The scorecard records each field team's seed, bye and route.

Open, not fixed: any unmatched title game leaves the field unscored, including one in a six-conference league that could not change the 2026 field; Selection Day is found by counting schedule rows that have a show time; the scorecard scores every FBS team where the replay scores 60 places, so the two are not comparable for VT-14; there is no pooled table by lead time across editions; the bye probability scored is derived from `bye_paths` (the edition publishes the count, not the probability).

## 2026-11-26 — Every simulated bracket is checked when a field forecast is built (VT-13)

- `final_field.run` takes an optional `check` and hands it each path's whole bracket. `build_field` passes `check_path` with the era's field size, byes and home games, so every path of every published field forecast is checked: each team once, each seed once, the right byes and hosts. A failure refuses the field section with the path number and the reason; the weekly forecast is still issued. The section's notes say the check ran.
- Closes the open item from the P20-lite review ("`check_path` is tested but is not run on simulator output").
- Run on real data through the report-only replay (2017–2025, both cutoffs, three models, 2,000 paths each): 54 simulator runs, 108,000 brackets across the four-team and twelve-team eras, no failure. Script kept outside the repo; it writes nothing.
