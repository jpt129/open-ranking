"""Issue proof (RL-03): an RFC 3161 timestamp token, a signed git tag and the text of the public post.

Only the SHA-256 of the edition leaves the machine. Nothing here reads or writes markets or accounts.
"""

from __future__ import annotations

import http.client
import re
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

AUTHORITIES = ("https://freetsa.org/tsr", "http://timestamp.digicert.com")
ET = ZoneInfo("America/New_York")
# TimeStampReq: version 1, SHA-256 message imprint, certReq TRUE (RFC 3161 section 2.4.1).
_HEAD = bytes.fromhex("30390201013031300d060960864801650304020105000420")
_TAIL = bytes.fromhex("0101ff")
GRANTED = (0, 1)  # granted, grantedWithMods

Post = Callable[[str, bytes], bytes]


class ProofError(RuntimeError):
    """A proof step failed."""


def _digest(sha256: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError(f"not a SHA-256 hex digest: {sha256!r}")
    return bytes.fromhex(sha256)


def timestamp_query(sha256: str) -> bytes:
    """The DER-encoded RFC 3161 request for a timestamp over this hash."""
    return _HEAD + _digest(sha256) + _TAIL


def _skip_header(data: bytes, at: int) -> int:
    """Index of the first content byte of the DER element at `at`."""
    first = data[at + 1]
    return at + 2 if first < 0x80 else at + 2 + (first & 0x7F)


def granted(reply: bytes, sha256: str) -> bool:
    """True if `reply` is a timestamp response with status granted that covers this hash."""
    try:
        if reply[0] != 0x30:
            return False
        info = _skip_header(reply, 0)  # PKIStatusInfo
        if reply[info] != 0x30:
            return False
        status = _skip_header(reply, info)
        if reply[status : status + 2] != b"\x02\x01":
            return False
        return reply[status + 2] in GRANTED and _digest(sha256) in reply
    except IndexError:
        return False


def http_post(url: str, body: bytes) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/timestamp-query", "User-Agent": "research-client"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as reply:
        return bytes(reply.read())


def request_token(
    sha256: str, post: Post = http_post, authorities: Sequence[str] = AUTHORITIES
) -> tuple[bytes, str]:
    """Ask each authority in turn; return the first granted token and the authority that issued it."""
    query = timestamp_query(sha256)
    problems = []
    for url in authorities:
        try:
            reply = post(url, query)
        except (OSError, http.client.HTTPException) as error:
            problems.append(f"{url}: {type(error).__name__}")
            continue
        if granted(reply, sha256):
            return reply, url
        problems.append(f"{url}: not granted")
    raise ProofError(f"no timestamp authority granted a token ({'; '.join(problems)})")


def tag_name(edition_id: str) -> str:
    return f"issue/{edition_id}"


def tag_commands(edition_id: str, sha256: str, push: bool) -> list[list[str]]:
    """The git commands that sign a tag carrying the hash, and optionally publish it."""
    message = f"{edition_id} sha256 {_digest(sha256).hex()}"
    commands = [["git", "tag", "-s", tag_name(edition_id), "-m", message]]
    if push:
        commands.append(["git", "push", "origin", f"refs/tags/{tag_name(edition_id)}"])
    return commands


def post_text(edition_id: str, sha256: str, cutoff: datetime, reveal: datetime) -> str:
    """The public post: what was issued, when its inputs were cut off, and the hash."""
    when = "%a %d %b %Y %H:%M ET"
    return (
        f"Open Ranking Models: forecast {edition_id}\n"
        f"Inputs cut off {cutoff.astimezone(ET).strftime(when)}; "
        f"committee reveal {reveal.astimezone(ET).strftime(when)}.\n"
        f"SHA-256 {_digest(sha256).hex()}\n"
        f"Signed tag: {tag_name(edition_id)}"
    )
