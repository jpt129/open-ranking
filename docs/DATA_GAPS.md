# Data gaps

Missing sources, unknown vintages and unverified inputs. A missing input removes or disqualifies an output; it is never filled with a substitute.

| Date | Source / input | Gap | Effect on outputs | Status |
|---|---|---|---|---|
| 2026-11-25 | CFBD API (all endpoints) | Calls failed with HTTP 401 until the .env loader was fixed (it kept an inline comment as part of the key). | None now. | closed 2026-11-25 |
| 2026-11-25 | CFBD games marked completed with no score | 2026: 5 games, all Division II/III. Also left out as unplayed or scoreless: 10 in 2023, 2 in 2024, 2 in 2025. | Left out of the games table. None involves an FBS team in 2026; earlier seasons to be itemised in P04. | open — P04 |
| 2026-11-25 | CFBD classification | Some opponents have no classification (114 game rows in 2026). | Stored as "unknown"; a snapshot must resolve or block on any that involve an FBS team. | open — P04 |
| 2026-11-25 | CFP site release dates | The site dates the 2016 final release 2016-12-06; ESPN's releases show it aired Sunday 2016-12-04 at noon ET. | The schedule file carries the true show date; the site's date is kept only as the lookup key. Other final dates were checked by weekday only. | handled |
| 2026-11-25 | CFP reveal show times | Times are scheduled starts from season-level announcements, several marked "approximately" (the 9 p.m. Champions Classic slots). Sources disagree for 2014-12-07 (12:45 recorded, 12:30 possible) and 2015-11-03 (19:30 recorded, 19:00 possible); the later time is used. | A replay's reveal-minus-60 cutoff may sit up to 30 minutes late for those two releases. | open — low priority |
| 2026-11-25 | Wayback copies of 2026 releases 2 and 3 (10 and 17 Nov) | No archived page within seven days was found that lists the 25 rows. | Those two releases are vintage "reconstructed"; they agree with ESPN. | open |
| 2026-11-25 | Schedules for past seasons | CFBD cannot say when a schedule became known, so 2014–25 hold results only. | Replay simulations of remaining games need a separately sourced schedule table. Ledgers and weekly forecasts are unaffected. | open — full track |
| 2026-11-25 | 2019 committee releases | CFBD has no copy of the 26 Nov 2019 release (its week 14 is missing), so the season cannot pass the CFBD cross-check. The other five 2019 releases match CFBD. | 2019 releases were checked against ESPN instead, with John's approval. | handled |
| 2026-11-25 | CFBD committee rankings, 2023 | CFBD repeats a rank in week 15 (two teams at 5) and in the final (two at 6). | 2023 releases were checked against ESPN instead, with John's approval. | handled |
| 2026-11-25 | CFBD team cfbd-3253 ("Charlotte", 2014) | An unclassified team that lost 56–0 at Davidson on 30 Aug 2014 shares the name of the Charlotte 49ers. ESPN lists the id as "Charlotte Saints", short name "Faith NC". | Renamed by a hand-kept override. It never meets an FBS team, so no ledger is affected. | handled |
| 2026-11-25 | Transitioning programs, 2026 | No source says whether a win over North Dakota State or Sacramento State counts as an FBS win in 2026; the field is empty in `data/transitioning.csv`. Several other rows rest on applying the NCAA rule or on Wikipedia (see the basis column). | P04 must settle how the two 2026 newcomers are classed before a ledger is published. CFBD lists both as FBS. | open — needs John |
| 2026-11-25 | Order-book depth before 25 Nov 2026 | Depth cannot be recovered after the fact. Venue price history back to 26 Oct was pulled, but books start with the first snapshot (25 Nov, 17:01 UTC). | Market comparisons before that date can use history prices only, without sizes. | accepted |
| 2026-11-25 | Polymarket history window | The venue refuses price-history requests longer than about 15 days. | History is fetched in seven-day windows. | handled |
| 2026-11-25 | Polymarket price history | The venue does not say whether a history point is a trade or a midpoint. | Stored in `last` as a price path only; never used as a two-sided quote. | open — low |
| 2026-11-25 | ESPN id for cfbd-108358 | CFBD calls the team "Phoenix"; ESPN calls the same number "Arizona Christian". Not confirmed as one school. | `espn_id` left empty. Not an FBS team. | open — low |

