---
name: issue-sunday
description: Issue the 2 a.m. ET Sunday weekly and field forecasts.
---
Before any pairing file is committed for the issue, run `scripts/check_hook.sh` (prints core.hooksPath; stop if it is not scripts/hooks). Confirm the clock is at or after 07:00 UTC (EST) or 06:00 UTC (EDT). Run `cfp forecast issue --kind sun0200`. Hash the bundle, post the hash (git tag, RFC 3161, public post) and record the posting times.
