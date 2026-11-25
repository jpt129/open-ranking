# Data gaps

Missing sources, unknown vintages and unverified inputs. A missing input removes or disqualifies an output; it is never filled with a substitute.

| Date | Source / input | Gap | Effect on outputs | Status |
|---|---|---|---|---|
| 2026-11-25 | CFBD API (all endpoints) | The key in .env is rejected with HTTP 401 "Unauthorized". No CFBD data has been fetched. | Blocks games, polls and lines for every season, and the CFBD cross-check that 2014–25 committee releases need before they can be ingested. The 2026 releases are in (checked against ESPN). | open — needs John |
| 2026-11-25 | CFBD parsers (games, polls, lines) | Tested only on hand-written payloads in the shape of CFBD's published schema (v5.34), not on recorded responses. | Parsers are unproven on real data until the fixture calls run. | open — follows the key |
| 2026-11-25 | CFP site release dates | The site dates the 2016 final release 2016-12-06; ESPN's releases show it aired Sunday 2016-12-04 at noon ET. | The schedule file carries the true show date; the site's date is kept only as the lookup key. Other final dates were checked by weekday only. | handled |
| 2026-11-25 | CFP reveal show times | Times are scheduled starts from season-level announcements, several marked "approximately" (the 9 p.m. Champions Classic slots). Sources disagree for 2014-12-07 (12:45 recorded, 12:30 possible) and 2015-11-03 (19:30 recorded, 19:00 possible); the later time is used. | A replay's reveal-minus-60 cutoff may sit up to 30 minutes late for those two releases. | open — low priority |
| 2026-11-25 | Wayback copies of 2026 releases 2 and 3 (10 and 17 Nov) | No archived page within seven days was found that lists the 25 rows. | Those two releases are vintage "reconstructed"; they agree with ESPN. | open |
| 2026-11-25 | Reconstructed game schedules | Backfilled schedule rows come from CFBD's final data, so a game moved or cancelled in-season appears as it ended up, from 1 Aug. | Replay simulations of remaining games see the final schedule. Does not affect results or ledgers. | accepted limitation |
