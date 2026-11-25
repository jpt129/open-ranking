# Mac fallback for the issue workflow

GitHub's scheduler had not started a single scheduled run in the data repository by 25 Nov 19:38 UTC, although
hand-triggered runs work. These files are copies of what is installed on John's Mac so that an issue does not
depend on that scheduler alone.

- `trigger_workflow.sh` (installed in `~/Library/Application Support/OpenRanking/`) hand-triggers a workflow
  in `jpt129/open-ranking-data` with `gh`, retrying five times a minute apart. Log:
  `~/Library/Logs/OpenRanking/trigger.log`.
- `com.openranking.issue-fallback.plist` (in `~/Library/LaunchAgents/`) runs it for the `issue` workflow at,
  Eastern time: Sun 29 Nov 00:10, 01:10, 01:40; Tue 1 Dec 16:10, 17:10, 17:40; Sun 6 Dec 00:10, 01:10, 01:40,
  09:10, 10:10, 10:40. The issue job waits for the cutoff itself and refuses to write an edition twice.
- `com.openranking.keep-awake.plist` runs `caffeinate -i` so the Mac does not idle-sleep. It does not stop
  sleep when the lid is closed, and the Mac must be online.

Tested 25 Nov 19:42 UTC: a one-off launchd job started the `capture` workflow.

Remove after 6 Dec:

    launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.openranking.issue-fallback.plist
    launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.openranking.keep-awake.plist
    rm ~/Library/LaunchAgents/com.openranking.*.plist
