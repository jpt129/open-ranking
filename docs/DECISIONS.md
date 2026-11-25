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
- **2019 is not ingested.** CFBD lacks the 26 Nov 2019 release. Awaiting John's decision on ESPN for 2019.
- **A Wayback outage fails the season's ingest** rather than marking its releases reconstructed, because vintage is fixed at first write. Rerunning fixes it (2017 needed one rerun).
