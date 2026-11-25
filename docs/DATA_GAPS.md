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
