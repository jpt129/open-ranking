#!/bin/sh
# Capture Kalshi and Polymarket listings, best quotes and order books, then current game lines from
# The Odds API (3 credits a pull). All read-only. Run by cron.
# Skips the run if the previous one is still going. Output goes to lake/logs/markets.log.
cd "$(dirname "$0")/.." || exit 1
mkdir -p lake/logs
if ! mkdir lake/logs/markets.lock 2>/dev/null; then
    echo "$(date -u +%FT%TZ) skipped: previous capture still running" >> lake/logs/markets.log
    exit 0
fi
trap 'rmdir lake/logs/markets.lock' EXIT
{
    echo "$(date -u +%FT%TZ) start"
    "${UV:-uv}" run cfp markets snapshot
    echo "$(date -u +%FT%TZ) markets exit $?"
    "${UV:-uv}" run cfp ingest odds
    echo "$(date -u +%FT%TZ) odds exit $?"
} >> lake/logs/markets.log 2>&1
