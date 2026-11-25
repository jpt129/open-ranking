#!/bin/sh
# Capture Kalshi and Polymarket listings, best quotes and order books, then current game lines from
# The Odds API (3 credits a pull). All read-only. Run by cron. Output goes to lake/logs/markets.log.
# One run at a time: the lock holds the runner's PID, and a lock whose process is gone is taken over.
# Exits non-zero if either capture fails.
cd "$(dirname "$0")/.." || exit 1
mkdir -p lake/logs
LOCK=lake/logs/markets.lock
LOG=lake/logs/markets.log
if ! mkdir "$LOCK" 2>/dev/null; then
    holder=$(cat "$LOCK/pid" 2>/dev/null)
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
        echo "$(date -u +%FT%TZ) skipped: capture $holder still running" >> "$LOG"
        exit 0
    fi
    echo "$(date -u +%FT%TZ) taking over a stale lock (holder ${holder:-unknown})" >> "$LOG"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
status=0
{
    echo "$(date -u +%FT%TZ) start"
    "${UV:-uv}" run cfp markets snapshot || status=1
    echo "$(date -u +%FT%TZ) markets done, failed=$status"
    "${UV:-uv}" run cfp ingest odds || status=1
    echo "$(date -u +%FT%TZ) end, failed=$status"
} >> "$LOG" 2>&1
exit $status
