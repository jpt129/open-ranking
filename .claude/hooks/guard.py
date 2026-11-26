# .claude/hooks/guard.py — exit code 2 blocks the call; stderr tells Claude why.
#
# Differs from the pack's version (docs/DECISIONS.md, 2026-11-25): paths are
# anchored to the project root, so ts/src/ is not mistaken for src/, and
# read-only shell commands that mention frozen/ are allowed.
#
# This is a backstop, not the enforcement: the tests and the release gate are.
import json
import os
import re
import shlex
import sys

ROOT = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
IMMUTABLE = ("lake/editions", "lake/scorecards", "lake/gaps", "frozen")
IMMUTABLE_MSG = (
    "Published editions and frozen parameters are immutable; create a new edition via the cfp CLI."
)
# Shell tokens that can change a file. Editions and frozen params are written
# only by the `cfp` CLI, whose command line never names these paths.
MUTATORS = re.compile(
    r"(>|\b(rm|mv|cp|tee|touch|truncate|chmod|chown|ln|dd|install|rsync|find|sed\s+-i|perl\s+-[a-z]*i"
    r"|git\s+(checkout|restore|rm|mv|clean|stash)|python3?|uv\s+run\s+python|node|sh|bash|zsh)\b)"
)
# Commands whose path arguments are changed or removed.
DESTRUCTIVE = {"rm", "rmdir", "mv", "cp", "tee", "touch", "truncate", "chmod", "chown", "ln", "dd", "install"}
DESTRUCTIVE |= {"rsync", "find", "unlink", "shred"}
GIT_DESTRUCTIVE = {"checkout", "restore", "rm", "mv", "clean", "stash"}


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def rel(path: str, cwd: str = ROOT) -> str | None:
    """Project-relative form of a path, or None if it is outside the project."""
    if not path:
        return None
    full = os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd, path))
    if full == ROOT:
        return ""
    return full[len(ROOT) + 1 :] if full.startswith(ROOT + os.sep) else None


def under(relpath: str | None, top: str) -> bool:
    return relpath is not None and (relpath == top or relpath.startswith(top + "/"))


def touches(relpath: str | None, top: str) -> bool:
    """True if the path is inside `top`, or is a parent whose removal would take `top` with it."""
    return under(relpath, top) or (relpath is not None and (relpath == "" or top.startswith(relpath + "/")))


def shell_mentions(command: str, top: str) -> bool:
    """True if a shell command names project-root `top/` (with the slash), relative or absolute.

    The bare word in prose or code (`frozen=True`, "frozen parameters") is not treated as a path;
    bare folder names passed as arguments are handled by destructive_args.
    """
    anchored = r"(?:^|[\s\"'=(;|&<>])(?:\./)?" + re.escape(top) + r"/"
    return bool(re.search(anchored, command)) or (ROOT + "/" + top) in command


def destructive_args(command: str) -> bool:
    """True if a destructive command is given an immutable path as an argument, following `cd`."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    cwd, segment = ROOT, []
    for token in [*tokens, ";"]:
        if token and not set(token) - set(";|&()"):
            if segment:
                words = [w for w in segment if "=" not in w or w.startswith(("-", "/", "."))]
                head = os.path.basename(words[0]) if words else ""
                args = words[1:]
                if head in ("sudo", "command", "xargs", "env", "time") and args:
                    head, args = os.path.basename(args[0]), args[1:]
                if head == "cd" and args:
                    cwd = os.path.realpath(os.path.join(cwd, os.path.expanduser(args[0])))
                elif head in DESTRUCTIVE or (head == "git" and args and args[0] in GIT_DESTRUCTIVE):
                    paths = [a for a in args if not a.startswith("-")]
                    if any(touches(rel(p.rstrip("*"), cwd), top) for p in paths for top in IMMUTABLE):
                        return True
            segment = []
        else:
            segment.append(token)
    return False


d = json.load(sys.stdin)
tool = d.get("tool_name", "")
ti = d.get("tool_input", {}) or {}
path = rel(str(ti.get("file_path") or ti.get("path") or ""))
command = str(ti.get("command", "")) if tool == "Bash" else ""

if tool in ("Edit", "Write") and any(under(path, top) for top in IMMUTABLE):
    block(IMMUTABLE_MSG)
if command and MUTATORS.search(command) and any(shell_mentions(command, top) for top in IMMUTABLE):
    block(IMMUTABLE_MSG)
if command and destructive_args(command):
    block(IMMUTABLE_MSG)

if os.environ.get("CFP_CLEANROOM") == "1":
    whole_repo_search = tool in ("Grep", "Glob") and (path == "" or not ti.get("path"))
    if under(path, "src") or whole_repo_search or (command and shell_mentions(command, "src")):
        block("Clean-room session: src/ is off limits; work from docs/SPEC.md.")

sys.exit(0)
