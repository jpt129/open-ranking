"""Shared HTTP path: budget, stage limits, rate limit, retries, raw archive, secret hygiene."""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfp.common.hashing import sha256_hex
from cfp.ingest.errors import BudgetExceeded, SourceError, StageOverrun, log_gap
from cfp.ingest.http import Budget, Fetcher, Response, TokenBucket
from cfp.store.lake import Lake

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
KEY = "sk-test-0123456789abcdef"


class FakeTransport:
    def __init__(self, replies: list[Response | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> Response:
        self.calls.append((url, dict(headers)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ok(body: bytes = b'[{"id": 1}]') -> Response:
    return Response(200, body, {})


def make(tmp_path: Path, replies: list[Response | Exception], allowance: int = 100, **kw: object) -> Fetcher:
    lake = Lake(tmp_path / "lake", clock=lambda: NOW)
    sleeps: list[float] = []
    fetcher = Fetcher(
        lake,
        "cfbd",
        "https://api.example.test",
        budget=Budget(tmp_path / "lake" / "budget.json", clock=lambda: NOW),
        allowance=allowance,
        bucket=TokenBucket(1000.0, 1000.0),
        headers={"Authorization": f"Bearer {KEY}"},
        transport=FakeTransport(replies),
        clock=lambda: NOW,
        sleep=sleeps.append,
        **kw,  # type: ignore[arg-type]
    )
    fetcher.sleeps = sleeps  # type: ignore[attr-defined]
    return fetcher


def test_get_archives_raw_and_logs(tmp_path: Path) -> None:
    fetcher = make(tmp_path, [ok()])
    got = fetcher.get("/games", {"year": 2025, "week": 1})
    assert got.raw_hash == sha256_hex(b'[{"id": 1}]')
    assert fetcher.lake.get_raw(got.raw_hash) == b'[{"id": 1}]'
    assert got.url == "https://api.example.test/games?week=1&year=2025"
    assert got.fetched_at == NOW
    assert got.json() == [{"id": 1}]
    entry = json.loads(fetcher.log_path.read_text().splitlines()[0])
    assert entry["raw_hash"] == got.raw_hash
    assert entry["url"] == got.url
    assert fetcher.budget.used("cfbd") == 1


def test_key_never_reaches_disk_or_errors(tmp_path: Path) -> None:
    fetcher = make(
        tmp_path, [ok(), Response(401, f"bad key {KEY}".encode(), {})], secret_params={"apiKey": KEY}
    )
    got = fetcher.get("/x")
    assert KEY not in got.url
    assert "apiKey=REDACTED" in got.url
    sent_url, sent_headers = fetcher._transport.calls[0]  # type: ignore[attr-defined]
    assert KEY in sent_url
    assert sent_headers["Authorization"] == f"Bearer {KEY}"
    with pytest.raises(SourceError) as failure:
        fetcher.get("/y")
    assert KEY not in str(failure.value)
    for file in (tmp_path / "lake").rglob("*"):
        if file.is_file():
            assert KEY.encode() not in file.read_bytes(), file


def test_retries_then_succeeds_and_counts_every_attempt(tmp_path: Path) -> None:
    replies: list[Response | Exception] = [
        Response(503, b"", {}),
        urllib.error.URLError("reset"),
        Response(429, b"", {"retry-after": "7"}),
        ok(),
    ]
    fetcher = make(tmp_path, replies)
    fetcher.get("/games")
    assert fetcher.budget.used("cfbd") == 4
    sleeps = fetcher.sleeps  # type: ignore[attr-defined]
    assert len(sleeps) == 3
    assert 1 <= sleeps[0] <= 2
    assert 2 <= sleeps[1] <= 4
    assert sleeps[2] >= 7


def test_gives_up_after_attempts(tmp_path: Path) -> None:
    fetcher = make(tmp_path, [Response(500, b"", {})] * 4)
    with pytest.raises(SourceError, match="gave up"):
        fetcher.get("/games")
    assert fetcher.budget.used("cfbd") == 4


def test_client_error_is_not_retried(tmp_path: Path) -> None:
    fetcher = make(tmp_path, [Response(404, b"nope", {})])
    with pytest.raises(SourceError, match="HTTP 404"):
        fetcher.get("/games")
    assert fetcher.budget.used("cfbd") == 1


def test_budget_refuses_before_sending(tmp_path: Path) -> None:
    fetcher = make(tmp_path, [ok(), ok()], allowance=1)
    fetcher.get("/a")
    with pytest.raises(BudgetExceeded):
        fetcher.get("/b")
    assert len(fetcher._transport.calls) == 1  # type: ignore[attr-defined]


def test_stage_stops_at_twice_its_estimate(tmp_path: Path) -> None:
    fetcher = make(tmp_path, [ok(b"%d" % i) for i in range(5)])
    with fetcher.stage("fixtures", estimate=2):
        for i in range(4):
            fetcher.get(f"/{i}")
        with pytest.raises(StageOverrun):
            fetcher.get("/4")
    assert fetcher.budget.stage_used("cfbd", "fixtures") == 4
    assert len(fetcher._transport.calls) == 4  # type: ignore[attr-defined]


def test_reuse_costs_no_call(tmp_path: Path) -> None:
    fetcher = make(tmp_path, [ok()])
    first = fetcher.get("/games", {"year": 2025})
    again = fetcher.get("/games", {"year": 2025}, reuse=True)
    assert again.reused
    assert again.raw_hash == first.raw_hash
    assert again.fetched_at == first.fetched_at
    assert fetcher.budget.used("cfbd") == 1


def test_budget_is_per_month_and_syncs_upward(tmp_path: Path) -> None:
    now = [datetime(2026, 11, 30, 23, 0, tzinfo=UTC)]
    budget = Budget(tmp_path / "b.json", clock=lambda: now[0])
    budget.spend("cfbd", 10, "s")
    assert budget.sync("cfbd", 7) == 7
    assert budget.sync("cfbd", 3) == 7
    now[0] = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)
    assert budget.used("cfbd") == 0


def test_token_bucket_waits_when_empty() -> None:
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    bucket = TokenBucket(2.0, 1.0, clock=lambda: now[0], sleep=sleep)
    bucket.take()
    bucket.take()
    bucket.take()
    assert waits == [0.5, 0.5]


def test_http_is_refused(tmp_path: Path) -> None:
    from cfp.ingest.http import urllib_transport

    with pytest.raises(SourceError):
        urllib_transport("http://example.test/x", {}, 1.0)


def test_log_gap_appends_once(tmp_path: Path) -> None:
    path = tmp_path / "DATA_GAPS.md"
    path.write_text(
        "# Data gaps\n\n| Date | Source / input | Gap | Effect on outputs | Status |\n|---|---|---|---|---|\n"
    )
    for _ in range(2):
        log_gap(
            path, NOW.date(), "cfbd /lines", "2014 has no moneylines | none", "VT-07 benchmark starts later"
        )
    rows = [line for line in path.read_text().splitlines() if line.startswith("| 2026")]
    assert rows == [
        "| 2026-11-25 | cfbd /lines | 2014 has no moneylines / none | VT-07 benchmark starts later | open |"
    ]
