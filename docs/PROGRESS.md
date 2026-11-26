# Progress

Updated at the end of every session (docs/PROTOCOL.md).

## 2026-11-25 — P00 Bootstrap + P-SPEC

Done
- Repo, signing, pack files (CLAUDE.md, PROTOCOL.md, 8 agents, 8 skills, settings, guard hook).
- uv project (Python 3.12), `src/cfp` skeleton, `cfp` CLI stub, CI workflow.
- Boundary: three import-linter contracts; `test_import_boundary` runs them in the suite.
- P00 acceptance: smoke tests pass; contract proven to fail on a planted `open_ranking -> forecast` import, probe deleted.
- `docs/SPEC.md` written with traceability table. No model code.

Commands run: `uv sync`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports`, `uv run pytest -q` (18 passed).

Open
- spec-guardian review of SPEC.md against the proposal PDF.
- Repo is private; must be public before Issue 1 (Sun 29 Nov 07:00 UTC).

Next prompt: P01 (store and point-in-time API), then P02a/P02b, P03, P04, P15, P23 per docs/PLAN.md §7.

## 2026-11-25 — P01 Store and point-in-time API (DS-01..DS-04)

Done
- `cfp.store.schemas`: 12 tables, each with the six provenance fields and vintage; validation on write.
- `cfp.store.lake`: raw payloads addressed by SHA-256; append-only Parquet partitioned by season; rejects rows citing a missing raw payload and duplicate (key, correction_version).
- `cfp.store.asof`: `as_of(rows, spec, t, mode)` with live / replay / scored modes and a coverage report.
- `cfp.store.views`: `OpenRankingView` (games, teams, membership only) and `PointInTimeView`.
- Guard hook: fixed false positives on the bare word for the frozen-parameters folder; hook behaviour is now covered by tests.
- SPEC.md revised after spec-guardian review (see DECISIONS.md).

Budget: as_of over 1,000,000 rows = 31 ms (budget 1 s).

Open
- SC-04a (open-points vintage for the Sunday issue) and the forfeit interpretation need John's decision.
- Scored mode drops only unknown vintage, as the spec says; reconstructed rows are kept and counted in coverage.

### P01 review round (same day)

spec-guardian confirmed six defects in the first P01 commit; all fixed with tests (see DECISIONS.md "P01 store rules"): backdatable ingest_time, non-atomic multi-season batches, unvalidated raw hashes, a bypassable OpenRankingView, weak import contracts, and silent drops in scored mode.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports` (4 kept, 0 broken), `uv run pytest -q` (129 passed). Budget: as_of over 999,999 lake-backed rows with three corrections per key = 24 ms.

Still to build for DS-04: `test_open_ranking_runs_without_forbidden_tables` (needs editions, P14).

Next prompt: P02a (CFBD client), P02b (CFP releases).

## 2026-11-25 — P02a (CFBD) and P02b (CFP releases)

Decisions: John ruled on SC-04a, forfeits and replay/ingest time, and set conditions for P02 (DECISIONS.md). SPEC.md updated; no [OPEN] items remain. One proposal awaits John: a Selection Day Open Ranking edition with cutoff Sun 6 Dec 02:00 ET.

Done
- `cfp.ingest.http`: one fetch path with token bucket, monthly budget and stage limits (written before each call), retries with jitter, raw archive, fetch log, key scrubbing.
- `cfp.ingest.public_time`, `cfp.ingest.upsert`: err-late first-public rules (kickoff + 4.5 h) and change-only appends.
- `cfp.ingest.cfp_releases` + `cfp ingest releases`: parse, sourced show time, alias resolution, cross-check, Wayback verification, vintage.
- **The four 2026 releases are in the lake** (100 rows), each identical to ESPN's copy. Vintage: release 1 archived_authentic, 2 and 3 reconstructed, 4 live.
- `cfp.ingest.cfbd`, `cfbd_normalize`, `cfp ingest cfbd`: client, parsers and staged season ingest, written against CFBD's published schema.
- Tests: no key-shaped string under tests/, and configured keys appear in no tracked file.

Blocked
- **CFBD rejects the key (HTTP 401).** Three calls were attempted; none succeeded. No games, polls or lines yet, and 2014–25 releases wait on the CFBD cross-check. See DATA_GAPS.md.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (31 files), `uv run lint-imports` (4 kept), `uv run pytest -q` (180 passed), `uv run cfp ingest releases --season 2026` (new=100).

Next: once the key works — `scripts/cfbd_fixture_calls.py`, then `cfp ingest cfbd --season 2026 --what reference games rankings --stage season-2026`, then 2014–25 rankings and games, `cfp ingest releases --season 2014..2025`, lines last. Then P03.

### P02 review round and live ingest (same day)

- spec-guardian confirmed sixteen defects in the first P02 commit; all fixed with tests (DECISIONS.md). One of them, the .env loader keeping an inline comment, was the cause of the CFBD 401s.
- CFBD live calls, in John's order: fixtures (9), 2026 season (10, including a rerun), 2014–25 games and polls (35), lines (26). 118 calls used this month against an allowance of 700.
- In the lake: 31,269 game rows (2014–2026), 9,855 poll rows, 38,479 closing-line rows, and 70 committee releases (1,750 rows) for every season except 2019. Release vintage: 30 archived_authentic, 1 live, 39 reconstructed.
- Recorded, trimmed fixtures now back the CFBD parser tests.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports` (4 kept), `uv run pytest -q` (206 passed), `cfp ingest cfbd ...` and `cfp ingest releases ...` as above.

Open
- 2019 releases (CFBD lacks one); three confirmations from John (Selection Day edition, narrower "live" label, Selection Day public time).

Next prompt: P03 (team identity and membership), then P04, P15, P23.

## 2026-11-25 — P03 (identity and membership) and P02d (Kalshi and Polymarket readers)

Decisions: John approved ESPN for 2019, confirmed the Selection Day edition (cutoff Sun 6 Dec 02:00 ET) and the show-start public time, and left the "live" label to Claude (kept narrow). 2019 releases are in: 76 releases, 2014–2026.

Done
- `cfp.identity`: builder, exact-match resolver, dated membership lookup, `cfp identity build`. In the lake: 777 teams, 2,334 aliases, 5,985 membership rows (2014–2026). Every team ID in games, polls and releases resolves; FBS counts match the sourced figures (138 in 2026).
- `cfp.markets`: read-only Kalshi and Polymarket parsers, `cfp markets snapshot` and `cfp markets history`. First snapshot 25 Nov 16:51–16:55 UTC: 1,582 contracts, 1,999 quotes including 417 order books. Venue history back to 26 Oct: 58,394 Kalshi candles and 68,365 Polymarket price points.
- New tables `market_catalogue`; `market_quotes` keyed with `kind`. Fifth import contract: forecasts cannot import market code.
- spec-guardian review: twelve findings fixed (DECISIONS.md).

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (36 files), `uv run lint-imports` (5 kept), `uv run pytest -q` (243 passed), `cfp identity build`, `cfp markets snapshot`, `cfp markets history --hours 720`.

Open
- Snapshots run only by hand; a schedule around each issue time is still to set up.
- John: are North Dakota State and Sacramento State ordinary FBS opponents in 2026? John: Odds API plan and tier, for P02c.
- P04 carry-overs: title-game list for 2014–21, forfeit list, left-out games, `data/transitioning.csv`.

Next prompt: P04 (canonical games), P02c once John's plan is known, then P15, P23.

## 2026-11-25 — P04 (snapshot builder), P02c (The Odds API), FBS classification ruling

Decisions: John ruled that a reclassifying member in an FBS conference is FBS for the ledger, with bid eligibility as a separate sourced flag; approved P04; set the Odds API tier (15M shared, be realistic) and accepted a 50,000-credit project cap.

Done
- Identity build enforces the classification rule and writes 29 sourced eligibility rows; membership rows carry a source URL.
- `cfp.snapshot`: `build_snapshot` and `cfp snapshot build`. Snapshots build for every season 2014–2026 with the right number of title games (7 to 10 a season). 2026 at the Issue 1 cutoff today: 824 games, 697 FBS v FBS.
- Sourced lists installed: 120 title games, no forfeits, 105 unplayed 2020 dates.
- `cfp.ingest.odds_api` and `cfp ingest odds`: 6 credits used; lines from US books for all 69 listed games.
- Hourly capture script (markets, then odds) in John's crontab, plus runs just before each pilot cutoff.
- spec-guardian review: findings fixed (DECISIONS.md).

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (39 files), `uv run lint-imports` (5 kept), `uv run pytest -q` (272 passed), `cfp identity build`, `cfp snapshot build` for 2014–2026, `cfp ingest odds` (twice).

Open
- Cloud captures run hourly from the private `jpt129/open-ranking-data` repository (first run 17:46 UTC 25 Nov, 1,908 quotes). Odds lines there wait for John to add the `ODDS_API_KEY` secret.
- Fill in the 2026 title pairings after 28 Nov.
- P07 carry-over: `test_loss_to_first_year_fbs_member_scores_minus_q`. P16: CFBD ingest immediately before each cutoff.
- Odds API historical snapshots wait for John's plan.

Next prompt: P15 (bracket rules) and P23 (baselines), then P05–P08.

## 2026-11-25 — P15 (observations and baselines), P23 (issue pipeline and proof), cloud captures

Done
- Cloud capture: private `jpt129/open-ranking-data` runs markets and odds hourly on GitHub Actions (both verified).
- `cfp.forecast`: cutoffs, observations, tiebreak draw, Baseline 1 and 2, and `build_issue`.
- `cfp.release`: canonical edition bytes, input IDs, write-once edition folders, RFC 3161 request and check, signed-tag commands, post text.
- Commands: `cfp ingest ap-others`, `cfp forecast draw`, `cfp forecast issue`.
- Data: 2026 AP votes outside the top 25 (weeks 2–13); `data/preseason_draw_2026.csv`.
- Dry run on real data in a scratch copy (nothing written to `lake/editions`): last week's release forecast, Baseline 2 22/25.
- Both timestamp authorities granted a token for the dry-run hash; local tag signing works.

Tests: 295 passed. ruff, mypy (47 files), lint-imports (5 kept) clean.

Open
- Sunday's issue needs, before 02:00 ET: a CFBD games ingest after the last final, `cfp ingest ap-others` is not needed again until the next AP poll (Sunday afternoon, before Issue 2).
- The signed tag proves nothing publicly until the repository is public and the tag is pushed (`--push`).
- Issue runs still depend on John's Mac; an Actions job for issues is not built.
- Rank-noise temperature; open points (after P05–P08).

Next prompt: P11-lite, then P05–P08 (the ledger).

## 2026-11-25 (later) — review fixes; issues on GitHub Actions

Done: P15/P23 review findings fixed (304 tests); `scripts/issue.sh`; `issue` workflow in the data repository, rehearsed once.

John has since added the CFBD and issuer secrets and made the code repository public; rehearsal 2 on Actions passed every step.

## 2026-11-25 (evening) — Open Ranking core: P05, P06, P11-lite, P07, P08

Built: strength engine, reference band, link, calibration search and report, frozen-parameter files, ledger, ordering. 351 tests pass; ruff, mypy and the five import contracts are clean.

Calibration on 2015–2025 chose λ_c = 4, λ_u = 4, t = 5.75; frozen for 2026 on 25 Nov with John's approval (week-8 start approved). Both reviews done and fixes applied; 355 tests pass.

Waiting on John:
- Ruling on the "losses since" rule in Baseline 2 (still Claude's reading).
- 2026 title-game pairings in `data/title_games.csv` after 28 Nov, before Issue 3.

Open Ranking release step built (`cfp open-ranking build`); 359 tests pass. No Open Ranking edition has been written to the real lake yet.

Release-step review fixes applied (corrections, crash repair, published snapshot rows). Open points are wired into the forecast issue (SC-04a); 368 tests pass.

P09 rules engine built with season files for 2014–2027 and fixtures checked against CFP pages; 382 tests pass.

P17 simulator built (probabilities from lines, correlated draws, scores, fits on 2014–2025); not yet wired into an issue. Mac fallback for issue triggers installed and tested.

Rank noise fitted and written once; the weekly issue now publishes probabilities; designated six-conference team (Boise State, 24 Nov) placed 26th; field-forecast core built and rehearsed on 2024 and 2025; the specified title-week model failed promotion.

Next: the field edition (document, command, workflow), title pairings with first-public times and scenarios, strength estimate for unquoted games, issue trigger (one command, local job primary), Friday dry run; rank-noise temperature; the gate (RL-01); the ledger page; a first published Open Ranking edition.

Not confirmed: that the hourly cloud capture fires on schedule (only hand-triggered runs were observed).

## 2026-11-25 (evening) — field forecast in the issue; reviews; poll re-dating

- Done: `final_field` section in the issue document (schema 4): pairings with sources and scenarios, strength fallback, conditionals, today's field. Spec review and leakage audit run and their fixes pushed. 2025 polls re-dated; rank noise corrected as `rank_noise_2026.c1.json`. Hourly capture started from the Mac. 433 tests pass; cloud rehearsal 45698608906 passed at `2c516d2`.
- For John: confirm the corrected rank-noise file; add Big Ten, SEC and Big 12 title pairings to `data/title_games.csv` (source and first-public time) once official, or the field section is refused on Sunday unless CFBD's schedule supplies them.
- Next: Friday timed dry run; check the first :17 hourly capture; AP "others receiving votes" capture before Tuesday; scoring and promotion modules (VT-12, VT-14) so the promotion test reruns from the repo; rerun the 2024/2025 rehearsal on the re-dated polls; SC-05 pairwise probabilities.

## 2026-11-25 (night) — reviews closed, SC-05 completed, calibrated column frozen

- Done: three reviews (fixes, provenance, referee) and their fixes; rank noise c2 confirmed by John; `cfp.forecast.pl` with the spec-named tests; pairwise bubble probabilities; whole-issue field test; calibrated disclosure column fitted, verified leave-one-season-out (6 of 6 cells) and frozen (`frozen/calibration_2026.json`). 444 tests pass; cloud rehearsal 45705761200 passed at `c115582`. Hourly capture from the Mac confirmed (21:17 UTC run succeeded).
- For John: look at the reliability tables (`cfp forecast fit-calibration --season 2026 --report`); the step behaviour of the calibrated rank ≤ 4 column (No. 6 and below at 0.0001).
- Next: title pairings as they become official (Big Ten, SEC, Big 12 rows with source and first-public time); Friday timed dry run; scoring and promotion modules (VT-11, VT-12, VT-14).

## 2026-11-25 (late) — calibrated column settled

- Done: John's ruling applied. P(top 25) calibrated column is published for Issues 1 and 2; rank ≤ 4 and rank ≤ 12 are raw only (logistic maps failed the bound clause of the pass rule). Maps frozen as `calibration_2026.c1.json`. Command test added; reports in `docs/reports/`. 447 tests pass.
- Candidates for after the pilot (promotion rule): nine-place regular-week drop; rank-dependent noise.
- Next: Friday timed dry run; title pairings with sources as they become official.

## 2026-11-25 (night) — P20-lite: scoring

- IDs: VT-10, VT-11, VT-11a, VT-12, VT-13 (integrity part), VT-14.
- Added: `cfp.scoring.{weekly,field,integrity,replay,scorecard}`, `cfp.forecast.promotion`, `past_champions` in `cfp.release.history`; commands `cfp score --release <id>` (write-once scorecard) and `cfp score-replay --season <n>` (report only).
- Spec-named tests present: `test_weekly_score_perfect_is_zero`, `test_weekly_score_uniform_hand_computed`, `test_secondary_cohort`, `test_field_scores_by_stratum`, `test_bubble_cohort_frozen_at_issue`, `test_integrity_sums_and_uniqueness`, `test_promotion_rule`, `test_expanding_replay_no_future_seasons`. Not added here: `test_sim_win_rates_within_mc_error`, `test_within_team_dependence_vs_residuals` (simulator tests cover the first; the second is open).
- Rehearsed on a scratch copy of the store against release 4 (replay editions, reference only): Baseline 2 S 0.01305 (Sunday) and 0.01242 (reveal −60); Baseline 1 0.02452 and 0.01131.
- Open: field and bye outcome scoring wired into `cfp score` for Selection Day (before 6 Dec); a stand-in for bubble Brier when the candidate is a regular-week change (needs John's ruling); the nine-place drop fitted inside each fold.
- Next: P14-lite (Open Ranking edition, manifest, gate), then P22-lite (Committee Gap).

## 2026-11-25 (night) — P14-lite: gate and public page

- IDs: RL-01, RL-01a, OR-08 (page), OR-09 (pilot disclosure).
- Added: `cfp.release.gate`, `cfp.release.page`; commands `cfp gate <edition>` and `cfp publish --edition <id>`.
- Spec-named tests: `test_gate_fails_on_planted_break`, `test_gate_second_impl_not_run_state` (in `tests/unit/test_gate.py`), with command and refusal tests. 478 tests pass.
- Open: the first live edition (results through Sat 28 Nov, built Sunday after the 02:00 issue); John pushes `site/` public; sensitivity and reversal reports are not built.
- Next: P22-lite (Committee Gap).

## 2026-11-26 — reviews closed; P22-lite: Committee Gap

- P20-lite and P14-lite committed as `26e8bca` after both spec reviews; open items are listed in DECISIONS.md (26 Nov entry).
- P22-lite: `cfp.gap.core`, `cfp.gap.report`, command `cfp gap --release <id>`. Spec-named tests present: `test_lift_sign_and_example`, `test_outside_25_bound`, `test_consequence_flags`, `test_provisional_before_selection_day`, `test_gap_reasons_present`, `test_gap_aggregation_coverage`. Spec review run and its findings fixed or recorded (DECISIONS.md). 504 tests pass.
- Open: the replay folds use the 2026 Open Ranking settings (needs John's ruling); field and bye outcome scoring in `cfp score` before 6 Dec; first live Open Ranking edition Sunday; push and cloud rehearsal.
- Next: Friday timed dry run; title pairings as they become official; P24.
- Field and bye outcome scoring wired into `cfp score` for Selection Day (VT-12), spec review run and fixed; 513 tests pass. Not yet run on a real field section (none exists until the title pairings are on file).
- Data repository workflows now check out the store at the branch tip (`37bcf6a` there); proof rehearsal behind the 06:17 UTC capture pending.

## 2026-11-26 — VT-08: sensitivity to the observed games

- IDs: VT-08, RL-01 (published, not gated), OR-08 (golden edition test).
- Added: `cfp.open_ranking.sensitivity`, `cfp.release.sensitivity`; command `cfp open-ranking sensitivity --edition <id> [--revision N]`; a non-blocking gate check; a page section. The formula's own files are unchanged, so the formula hash is unchanged.
- Spec-named tests: `test_refit_weights_reused_across_folds`, `test_sensitivity_outputs` (in `tests/unit/test_sensitivity.py`); golden test `tests/unit/test_golden_edition.py`. 537 tests pass.
- Real data (scratch store, rehearsal edition of 22 Nov): 1,000 refits in 30 s on eight processes; the gate's rerun matched; the correction path was exercised.
- Open Ranking release order (the Monday 06:00 ET edition and the Selection Day edition, not the 02:00 ET forecast issue): build, sensitivity, gate, publish (`.claude/skills/release-open-ranking`). Sensitivity never holds the edition back.
- Open: John's rulings listed in DECISIONS (cut-line reading, eligibility and forecast code in the bracket step, hook change); VT-09 and OR-10 not built.
- Next: Friday timed dry run; title pairings as they become official.
- 26 Nov, after John's review: route marks and one-line cut-line definition; field-code and table hashes; environment record; ten-minute limit; import contract and test that forecast issues never run it. 549 tests pass. Decisions and answers A–D are in DECISIONS (26 Nov, "VT-08 accepted").
- Freeze after Friday's dry run: only fixes the dry run turns up. Sensitivity follow-ups wait until after Issue 1.
- Next: Friday timed dry run (build, sensitivity, gate, publish timed on the issuing machine; two title-pairing paths); pairings as they become official.

## 2026-11-26 — title pairings: rules for Issue 1

- IDs: FF-04, VT-12, VT-08 (page), MK (flag only).
- Added: the source rule and `review_pairings` in `cfp.forecast.pairings`; command `cfp forecast pairings`; the 5% rule, disclosure line and conditional flags in `cfp.release.field`; scoring of the matching scenario only in `cfp.scoring.scorecard`; "assumed" on the sensitivity page; a `result_url` column in both pairing files.
- 558 tests pass. Spec review run; one high finding fixed (an unreadable title file stopped the whole issue).
- Live pairings today: Big Ten 8, SEC 3, Big 12 2 (48 combinations; limit 8). Recount after Friday's games.
- Next: Friday dry run. Time the eight-combination case from ingest to finished issue; rehearse a malformed CSV at checkout, scenarios collapsing to a final pairing at 23:30, late-Saturday entry, and the field section not delivered; time build, sensitivity, gate and publish.
