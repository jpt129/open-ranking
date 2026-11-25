# .claude/hooks/guard.py — exit code 2 blocks the call; stderr tells Claude why.
#
# Differs from the pack's version (docs/DECISIONS.md, 2026-11-25): paths are
# anchored to the project root, so ts/src/ is not mistaken for src/, and
# read-only shell commands that mention frozen/ are allowed.
import json
import os
import re
import sys

ROOT = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
IMMUTABLE = ("lake/editions", "frozen")
# Shell tokens that can change a file. Editions and frozen params are written
# only by the `cfp` CLI, whose command line never names these paths.
MUTATORS = re.compile(
    r"(>|\b(rm|mv|cp|tee|touch|truncate|chmod|chown|ln|dd|install|rsync|sed\s+-i|perl\s+-[a-z]*i"
    r"|git\s+(checkout|restore|rm|mv|clean|stash)|python3?|uv\s+run\s+python|node|sh|bash|zsh)\b)"
)


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def rel(path: str) -> str | None:
    """Project-relative form of a path, or None if it is outside the project."""
    if not path:
        return None
    full = os.path.realpath(path if os.path.isabs(path) else os.path.join(ROOT, path))
    if full == ROOT:
        return ""
    return full[len(ROOT) + 1:] if full.startswith(ROOT + os.sep) else None


def under(relpath: str | None, top: str) -> bool:
    return relpath is not None and (relpath == top or relpath.startswith(top + "/"))


def shell_mentions(command: str, top: str) -> bool:
    """True if a shell command names project-root `top/`, relative or absolute."""
    anchored = r"(?:^|[\s\"'=(;|&<>])(?:\./)?" + re.escape(top) + r"(?:/|\b)"
    return bool(re.search(anchored, command)) or (ROOT + "/" + top) in command


d = json.load(sys.stdin)
tool = d.get("tool_name", "")
ti = d.get("tool_input", {}) or {}
path = rel(str(ti.get("file_path") or ti.get("path") or ""))
command = str(ti.get("command", "")) if tool == "Bash" else ""

if tool in ("Edit", "Write") and any(under(path, top) for top in IMMUTABLE):
    block("Published editions and frozen parameters are immutable; create a new edition via the cfp CLI.")
if command and MUTATORS.search(command) and any(shell_mentions(command, top) for top in IMMUTABLE):
    block("Published editions and frozen parameters are immutable; create a new edition via the cfp CLI.")

if os.environ.get("CFP_CLEANROOM") == "1":
    if under(path, "src") or (tool in ("Grep", "Glob") and (path == "" or not ti.get("path"))) or (command and shell_mentions(command, "src")):
        block("Clean-room session: src/ is off limits; work from docs/SPEC.md.")

sys.exit(0)
