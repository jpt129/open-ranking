"""One HTTP path for every source: rate limit, monthly budget, retries, raw archive (DS-01).

Every response body that is used is stored in the lake's raw area under its SHA-256, and every attempt is
counted against the source's monthly budget before it is sent. Secrets travel in headers or in named query
parameters; neither reaches the fetch log, the raw area or an error message.
"""

from __future__ import annotations

import fcntl
import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from cfp.common.timeutil import require_utc, utc_now
from cfp.ingest.errors import BudgetExceeded, SourceError, StageOverrun
from cfp.store.lake import Lake

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
REDACTED = "REDACTED"


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str]


Transport = Callable[[str, Mapping[str, str], float], Response]


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https on the same host, so request headers never travel elsewhere."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname:
            raise SourceError(f"refused a redirect from {old.hostname} to {new.scheme}://{new.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameHostRedirects)


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> Response:
    if not url.startswith("https://"):
        raise SourceError("only https sources are fetched")
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with _OPENER.open(request, timeout=timeout) as reply:
            return Response(reply.status, reply.read(), {k.lower(): v for k, v in reply.headers.items()})
    except urllib.error.HTTPError as error:
        return Response(error.code, error.read(), {k.lower(): v for k, v in error.headers.items()})


class TokenBucket:
    """At most `rate` calls a second on average, with bursts up to `capacity`."""

    def __init__(
        self,
        rate: float,
        capacity: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0 or capacity < 1:
            raise ValueError("rate must be positive and capacity at least 1")
        self._rate, self._capacity, self._clock, self._sleep = rate, capacity, clock, sleep
        self._tokens, self._at = capacity, clock()

    def take(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._at) * self._rate)
        self._at = now
        if self._tokens < 1:
            wait = (1 - self._tokens) / self._rate
            self._sleep(wait)
            self._at = self._clock()
            self._tokens = 1.0
        self._tokens -= 1


class Budget:
    """A monthly call counter per source, kept in a JSON file and written before each call goes out."""

    def __init__(self, path: Path | str, clock: Callable[[], datetime] = utc_now) -> None:
        self.path = Path(path)
        self._clock = clock

    def _month(self) -> str:
        return require_utc(self._clock(), "clock").strftime("%Y-%m")

    def _read(self) -> dict[str, Any]:
        """The stored counters. A file that exists but cannot be read is an error, never a fresh start."""
        if not self.path.exists():
            return {}
        try:
            state = json.loads(self.path.read_text())
        except ValueError as error:
            raise BudgetExceeded(f"{self.path} is unreadable; refusing to guess the call count") from error
        if not isinstance(state, dict):
            raise BudgetExceeded(f"{self.path} is unreadable; refusing to guess the call count")
        return state

    @contextmanager
    def _state(self) -> Iterator[dict[str, Any]]:
        """Read-modify-write under a lock; the new file replaces the old one in a single step."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._read()
            yield state
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
            tmp.replace(self.path)

    def used(self, source: str) -> int:
        return int(self._read().get(source, {}).get(self._month(), {}).get("calls", 0))

    def stage_used(self, source: str, stage: str) -> int:
        return int(self._read().get(source, {}).get(self._month(), {}).get("stages", {}).get(stage, 0))

    def sync(self, source: str, used: int) -> int:
        """Raise the counter to the source's own figure when that is higher. Returns the counter."""
        with self._state() as state:
            month = state.setdefault(source, {}).setdefault(self._month(), {"calls": 0, "stages": {}})
            month["calls"] = max(int(month["calls"]), used)
            return int(month["calls"])

    def spend(self, source: str, allowance: int, stage: str, stage_estimate: int | None = None) -> int:
        """Count one call, or refuse it. `allowance` is the monthly limit less any reserve."""
        with self._state() as state:
            month = state.setdefault(source, {}).setdefault(self._month(), {"calls": 0, "stages": {}})
            if month["calls"] + 1 > allowance:
                raise BudgetExceeded(
                    f"{source}: {month['calls']} calls used this month; allowance {allowance}"
                )
            in_stage = int(month["stages"].get(stage, 0))
            if stage_estimate is not None and in_stage + 1 > 2 * stage_estimate:
                raise StageOverrun(
                    f"{source}: stage {stage!r} has used {in_stage} calls; estimate {stage_estimate}"
                )
            month["calls"] += 1
            month["stages"][stage] = in_stage + 1
            return int(month["calls"])


@dataclass(frozen=True)
class Fetched:
    source: str
    url: str  # secrets redacted
    raw_hash: str
    body: bytes
    fetched_at: datetime
    reused: bool = False

    def json(self) -> Any:
        return json.loads(self.body)


class Fetcher:
    """GET with a token bucket, a budget, retries and raw archiving, for one source."""

    def __init__(
        self,
        lake: Lake,
        source: str,
        base_url: str,
        *,
        budget: Budget,
        allowance: int,
        bucket: TokenBucket,
        headers: Mapping[str, str] | None = None,
        secret_params: Mapping[str, str] | None = None,
        transport: Transport = urllib_transport,
        attempts: int = 4,
        timeout: float = 60.0,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        seed: int = 0,
    ) -> None:
        self.lake, self.source, self.base_url = lake, source, base_url.rstrip("/")
        self.budget, self.allowance, self.bucket = budget, allowance, bucket
        self._headers = dict(headers or {})
        self._secret_params = dict(secret_params or {})
        self._transport, self._attempts, self._timeout = transport, attempts, timeout
        self._clock, self._sleep, self._jitter = clock, sleep, random.Random(seed)
        self._stage, self._stage_estimate = "default", None  # type: tuple[str, int | None]

    @property
    def log_path(self) -> Path:
        return self.lake.root / "fetch_log.jsonl"

    @contextmanager
    def stage(self, name: str, estimate: int | None = None) -> Iterator[None]:
        """Name the calls made inside the block; stop if they pass twice the estimate."""
        previous = (self._stage, self._stage_estimate)
        self._stage, self._stage_estimate = name, estimate
        try:
            yield
        finally:
            self._stage, self._stage_estimate = previous

    def _url(self, path: str, params: Mapping[str, object], secrets: Mapping[str, str]) -> str:
        query = {k: str(v) for k, v in sorted(params.items())} | dict(secrets)
        base = path if path.startswith("https://") else f"{self.base_url}/{path.lstrip('/')}"
        return f"{base}?{urlencode(query)}" if query else base

    def _secrets(self) -> list[str]:
        """Secret values this fetcher sends: named query parameters and any Authorization header."""
        values = list(self._secret_params.values())
        values += [
            v.removeprefix("Bearer ") for k, v in self._headers.items() if k.lower() == "authorization"
        ]
        return [value for value in values if len(value) >= 8]

    def _scrub(self, text: str) -> str:
        for secret in self._secrets():
            text = text.replace(secret, REDACTED).replace(quote(secret, safe=""), REDACTED)
        return text

    def lookup(self, public_url: str) -> Fetched | None:
        """The most recent archived response for this URL, if its raw payload is intact."""
        if not self.log_path.is_file():
            return None
        found: dict[str, Any] | None = None
        for line in self.log_path.read_text().splitlines():
            entry = json.loads(line)
            if entry["source"] == self.source and entry["url"] == public_url:
                found = entry
        if found is None or not self.lake.has_raw(found["raw_hash"]):
            return None
        at = datetime.fromisoformat(found["fetched_at"])
        return Fetched(
            self.source, public_url, found["raw_hash"], self.lake.get_raw(found["raw_hash"]), at, True
        )

    def get(self, path: str, params: Mapping[str, object] | None = None, *, reuse: bool = False) -> Fetched:
        """Fetch and archive. With `reuse`, an already archived response for the same URL costs no call."""
        params = params or {}
        public_url = self._url(path, params, {k: REDACTED for k in self._secret_params})
        if reuse and (cached := self.lookup(public_url)) is not None:
            return cached
        url = self._url(path, params, self._secret_params)
        problem = "no attempt made"
        for attempt in range(self._attempts):
            self.budget.spend(self.source, self.allowance, self._stage, self._stage_estimate)
            self.bucket.take()
            try:
                reply = self._transport(url, self._headers, self._timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                problem, retry_after = self._scrub(f"{type(error).__name__}: {error}"), None
            else:
                if reply.status == 200:
                    return self._archive(public_url, reply.body)
                problem = f"HTTP {reply.status}"
                if reply.status not in RETRY_STATUS:
                    detail = self._scrub(reply.body[:200].decode("utf-8", "replace"))
                    raise SourceError(f"{self.source}: {problem} for {public_url}: {detail}")
                retry_after = reply.headers.get("retry-after")
            if attempt + 1 < self._attempts:
                backoff = float(2**attempt)
                wait = backoff + self._jitter.uniform(0, backoff)
                if retry_after and retry_after.isdigit():
                    wait = max(wait, float(retry_after))
                self._sleep(wait)
        raise SourceError(
            f"{self.source}: gave up on {public_url} after {self._attempts} attempts ({problem})"
        )

    def _archive(self, public_url: str, body: bytes) -> Fetched:
        at = require_utc(self._clock(), "clock")
        if any(secret.encode() in body for secret in self._secrets()):
            raise SourceError(f"{self.source}: the response echoes a secret; not archived")
        raw_hash = self.lake.put_raw(body)
        entry = {
            "source": self.source,
            "url": public_url,
            "raw_hash": raw_hash,
            "fetched_at": at.isoformat(),
            "stage": self._stage,
            "bytes": len(body),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return Fetched(self.source, public_url, raw_hash, body, at)
