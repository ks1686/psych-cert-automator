#!/usr/bin/env python3
"""Path, process, and evidence guards for the Psych Cert Gen verification skill.

Run state is plain key=value text. This file never executes those values.
Tool paths and HOME are derived here from the state directory and the
process environment, not from run.env.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

STATE_KEY = re.compile(r"[A-Z][A-Z0-9_]*")
RUN_ID = re.compile(r"[A-Za-z0-9_-]+")
STATE_DIR_NAME = re.compile(r"state\.[A-Za-z0-9]+")
EVIDENCE_DIR_NAME = re.compile(r"evidence\.[A-Za-z0-9]+")
CAPTURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
LSTART_RE = re.compile(
    r"^(?P<lstart>[A-Z][a-z]{2} [A-Z][a-z]{2} [ 0-9][0-9] "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}) (?P<command>.+)$"
)
HELPER_NAMES = frozenset(
    {
        "run.env",
        "evidence-name",
        "evidence-inode",
        "before-manifest",
        "browser.sock",
        "browser.ready",
        "id-pointer",
        "harness.py",
        "lib.sh",
        "regress.sh",
        "verify-psych-cert-gen",
        "browser-server.mjs",
        "ax-check.mjs",
        "home",
        "tmp",
        "output",
        "logs",
        "pass",
    }
)
LABELS = ("API", "UI", "BROWSER")
STUBBED_SCHEMES = ("tel", "sms", "mailto", "payment")


def die(message: str, code: int = 1) -> None:
    sys.stderr.write(f"{message}\n")
    raise SystemExit(code)


def platform_name() -> str:
    assumed = os.environ.get("PSYCH_CERT_VERIFY_ASSUME_UNAME", "")
    if assumed:
        return assumed
    return os.uname().sysname


def require_platform() -> str:
    name = platform_name()
    if name not in ("Linux", "Darwin"):
        die(f"unsupported platform: {name}", 2)
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        die("unsupported platform: missing O_NOFOLLOW", 2)
    return name


def real_home() -> str:
    home = os.path.expanduser("~")
    # expanduser follows the passwd entry when HOME is unset, and HOME when set.
    # Prefer the passwd home so an inherited HOME cannot redirect prefs checks.
    try:
        import pwd

        home = pwd.getpwuid(os.getuid()).pw_dir
    except (ImportError, KeyError):
        pass
    if not home or home == "/":
        die("cannot resolve the real home directory")
    return home


def mode_of(path: str) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def assert_private(path: str) -> None:
    if os.path.islink(path):
        die(f"refusing symlink: {path}")
    if not os.path.isdir(path):
        die(f"not a directory: {path}")
    info = os.lstat(path)
    if info.st_uid != os.getuid():
        die(f"not owner: {path}")
    if mode_of(path) & 0o022:
        die(f"group or other can write: {path}")
    if mode_of(path) != 0o700:
        die(f"directory mode is {mode_of(path):04o}, want 0700: {path}")


def refuse_caller_dir(path: str) -> None:
    """Check a directory the caller passed in. Never chmod it."""
    if os.path.islink(path):
        die(f"refusing symlink: {path}")
    if not os.path.isdir(path):
        die(f"not a directory: {path}")
    info = os.lstat(path)
    if info.st_uid != os.getuid():
        die(f"not owner: {path}")
    if mode_of(path) & 0o022:
        die(f"group or other can write: {path}")


def tighten_created_dir(path: str) -> None:
    """Tighten a directory this process just created with mktemp. Not for caller paths."""
    if os.path.islink(path):
        die(f"refusing symlink: {path}")
    if not os.path.isdir(path):
        die(f"not a directory: {path}")
    info = os.lstat(path)
    if info.st_uid != os.getuid():
        die(f"not owner: {path}")
    if mode_of(path) != 0o700:
        os.chmod(path, 0o700)
    assert_private(path)


def temp_roots() -> list[str]:
    roots: list[str] = []
    for raw in ("/tmp", "/private/tmp"):
        roots.append(raw)
        if os.path.exists(raw):
            roots.append(os.path.realpath(raw))
    unique: list[str] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def full_realpath(path: str) -> str:
    return os.path.realpath(path)


def under_root(path: str, root: str) -> bool:
    resolved = full_realpath(path)
    root_resolved = full_realpath(root) if os.path.exists(root) else root
    if resolved == root_resolved or resolved.startswith(root_resolved.rstrip("/") + "/"):
        return True
    if resolved == root or resolved.startswith(root.rstrip("/") + "/"):
        return True
    return False


def under_any(path: str, roots: list[str]) -> bool:
    return any(under_root(path, root) for root in roots)


def require_temp_path(path: str) -> None:
    if not under_any(path, temp_roots()):
        die(f"path is outside /tmp and /private/tmp: {path}")


def require_inside(path: str, root: str) -> str:
    if os.path.islink(path):
        die(f"refusing symlink: {path}")
    resolved = full_realpath(path)
    if not under_root(resolved, root):
        die(f"path escapes {root}: {path}")
    return resolved


def registry_path() -> str:
    require_platform()
    override = os.environ.get("PSYCH_CERT_VERIFY_RUNTIME", "")
    if override:
        refuse_caller_dir(override)
        return full_realpath(override)
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    if xdg:
        refuse_caller_dir(xdg)
        path = os.path.join(xdg, "psych-cert-verify")
        if os.path.lexists(path):
            refuse_caller_dir(path)
            return full_realpath(path)
        os.mkdir(path, 0o700)
        tighten_created_dir(path)
        return full_realpath(path)
    tmp = os.environ.get("TMPDIR") or "/tmp"
    require_temp_path(tmp if os.path.exists(tmp) else "/tmp")
    base = full_realpath(tmp)
    path = os.path.join(base, f"psych-cert-verify-uid-{os.getuid()}")
    if os.path.lexists(path):
        if os.path.islink(path):
            die(f"refusing symlink registry: {path}")
        refuse_caller_dir(path)
        if mode_of(path) != 0o700:
            die(f"registry mode is not 0700: {path}")
        return full_realpath(path)
    os.mkdir(path, 0o700)
    tighten_created_dir(path)
    return full_realpath(path)


def valid_run_id(value: str) -> None:
    if value in (".", "..") or not RUN_ID.fullmatch(value or ""):
        die(f"invalid run id: {value!r}", 2)


def make_run_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    value = f"{stamp}-{os.getpid()}-{time.time_ns()}"
    valid_run_id(value)
    return value


def load_state(path: str) -> tuple[dict[str, str], list[str]]:
    if os.path.islink(path):
        die("refusing to read a symlink state file")
    if not os.path.isfile(path):
        die(f"missing state file: {path}")
    if mode_of(path) & 0o077:
        die("state file is group or world accessible")
    data: dict[str, str] = {}
    order: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw[:-1] if raw.endswith("\n") else raw
            if line.endswith("\r"):
                line = line[:-1]
            if line == "" or line.startswith("#"):
                continue
            if "=" not in line:
                die(f"bad state line {lineno}")
            key, value = line.split("=", 1)
            if not STATE_KEY.fullmatch(key):
                die(f"bad state key on line {lineno}")
            data[key] = value
            if key not in order:
                order.append(key)
    return data, order


def read_state(path: str, key: str) -> str:
    if not STATE_KEY.fullmatch(key):
        die(f"bad state key: {key}", 2)
    data, _order = load_state(path)
    if key not in data:
        die(f"missing state key: {key}")
    sys.stdout.write(data[key])
    return data[key]


def write_state(path: str, key: str, value: str) -> None:
    if not STATE_KEY.fullmatch(key):
        die(f"bad state key: {key}", 2)
    if "\n" in value or "\r" in value or "\0" in value:
        die("state value contains a newline")
    parent = os.path.dirname(path) or "."
    if os.path.lexists(path) and os.path.islink(path):
        die("refusing to write through a symlink")
    data: dict[str, str] = {}
    order: list[str] = []
    if os.path.exists(path):
        data, order = load_state(path)
    if key not in order:
        order.append(key)
    data[key] = value
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".state.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            for item in order:
                handle.write(f"{item}={data[item]}\n")
        os.chmod(tmp, 0o600)
        if os.path.lexists(path) and os.path.islink(path):
            die("state file became a symlink")
        os.replace(tmp, path)
        tmp = ""
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    os.chmod(path, 0o600)


def ps_env() -> dict[str, str]:
    env = os.environ.copy()
    env["TZ"] = "UTC0"
    env["LC_ALL"] = "C"
    return env


def run_ps(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["ps", *args],
            check=False,
            capture_output=True,
            text=True,
            env=ps_env(),
        )
    except OSError as exc:
        die(f"ps failed closed: {exc}")
        raise AssertionError("unreachable") from exc


def ps_alive(pid: int) -> str:
    proc = run_ps(["-p", str(pid), "-o", "pid="])
    if proc.returncode == 0 and proc.stdout.strip():
        return "alive"
    if proc.returncode == 1 and not proc.stdout.strip():
        return "dead"
    die(f"ps failed closed: status {proc.returncode} {proc.stderr.strip()}")
    return "dead"


def ps_identity(pid: int) -> dict[str, str]:
    if pid <= 0:
        die("invalid pid")
    if ps_alive(pid) != "alive":
        die(f"ps cannot confirm pid {pid}")
    proc = run_ps(["-o", "lstart=", "-o", "command=", "-p", str(pid)])
    if proc.returncode != 0:
        die(f"ps failed closed: status {proc.returncode}")
    line = proc.stdout.strip()
    match = LSTART_RE.match(line)
    if not match:
        die(f"ps identity is unreadable: {line!r}")
    uid_proc = run_ps(["-o", "uid=", "-p", str(pid)])
    if uid_proc.returncode != 0 or not uid_proc.stdout.strip().isdigit():
        die("ps failed closed while reading uid")
    return {
        "pid": str(pid),
        "lstart": match.group("lstart"),
        "command": match.group("command"),
        "uid": str(int(uid_proc.stdout.strip())),
    }


def live_pgid(pid: int) -> int:
    if ps_alive(pid) != "alive":
        die(f"ps cannot confirm pid {pid}")
    proc = run_ps(["-o", "pgid=", "-p", str(pid)])
    if proc.returncode != 0:
        die(f"ps failed closed: status {proc.returncode}")
    text = proc.stdout.strip()
    if not text.isdigit():
        die("ps returned no pgid")
    return int(text)


def write_identity(state_file: str, label: str, pid: int) -> None:
    if label not in LABELS:
        die(f"unknown process label: {label}", 2)
    ident = ps_identity(pid)
    write_state(state_file, f"{label}_PID", ident["pid"])
    write_state(state_file, f"{label}_LSTART", ident["lstart"])
    write_state(state_file, f"{label}_COMMAND", ident["command"])
    write_state(state_file, f"{label}_UID", ident["uid"])


def saved_identity(state_file: str, label: str) -> dict[str, str] | None:
    data, _order = load_state(state_file)
    pid = data.get(f"{label}_PID", "")
    if not pid:
        return None
    return {
        "pid": pid,
        "lstart": data.get(f"{label}_LSTART", ""),
        "command": data.get(f"{label}_COMMAND", ""),
        "uid": data.get(f"{label}_UID", ""),
    }


def identity_matches(saved: dict[str, str]) -> bool:
    if not saved["pid"].isdigit():
        return False
    live = ps_identity(int(saved["pid"]))
    return (
        live["lstart"] == saved["lstart"]
        and live["command"] == saved["command"]
        and live["uid"] == saved["uid"]
        and int(live["uid"]) == os.getuid()
    )


def confirm_label(state_file: str, label: str) -> str:
    """Return alive, dead, or absent. Mismatch and ps errors abort."""
    saved = saved_identity(state_file, label)
    if saved is None:
        return "absent"
    if not saved["pid"].isdigit():
        die(f"{label} pid is not numeric")
    kind = ps_alive(int(saved["pid"]))
    if kind == "dead":
        return "dead"
    if not identity_matches(saved):
        die(f"{label} identity mismatch; not signaling")
    return "alive"


def all_dead(state_file: str) -> None:
    for label in LABELS:
        saved = saved_identity(state_file, label)
        if saved is None:
            continue
        if not saved["pid"].isdigit():
            die(f"{label} pid is not numeric")
        if ps_alive(int(saved["pid"])) != "dead":
            die(f"{label} is still running")


def signal_confirmed(state_file: str) -> None:
    plans: list[tuple[str, int, int]] = []
    for label in LABELS:
        kind = confirm_label(state_file, label)
        if kind != "alive":
            continue
        saved = saved_identity(state_file, label)
        if saved is None:
            die(f"{label} disappeared")
        pid = int(saved["pid"])
        first = live_pgid(pid)
        second = live_pgid(pid)
        if first != second or first <= 1:
            die(f"{label} pgid is unstable or unsafe")
        if not identity_matches(saved):
            die(f"{label} identity changed; not signaling")
        plans.append((label, pid, first))
    for label, pid, pgid in plans:
        saved = saved_identity(state_file, label)
        if saved is None or not identity_matches(saved):
            die(f"{label} identity changed; not signaling")
        if live_pgid(pid) != pgid:
            die(f"{label} pgid changed; not signaling")
    for label, pid, pgid in plans:
        if live_pgid(pid) != pgid:
            die(f"{label} pgid changed at signal time; not signaling")
        os.kill(-pgid, signal.SIGTERM)
    deadline = time.time() + 5
    for _label, pid, pgid in plans:
        while time.time() < deadline and ps_alive(pid) == "alive":
            time.sleep(0.1)
        if ps_alive(pid) == "alive":
            if live_pgid(pid) != pgid:
                die("pgid changed before kill; not signaling")
            os.kill(-pgid, signal.SIGKILL)


def signal_launch_group(pid: int) -> None:
    """Kill the session group of a process this launch just spawned.

    The caller also kills the raw pid. This only signals when the live pgid
    equals that pid, which is the setsid leader we started.
    """
    if pid <= 1:
        die("refusing to signal a system pid")
    kind = ps_alive(pid)
    if kind == "dead":
        return
    proc = run_ps(["-o", "uid=", "-p", str(pid)])
    if proc.returncode != 0 or not proc.stdout.strip().isdigit():
        die("ps failed closed while checking launch owner")
    if int(proc.stdout.strip()) != os.getuid():
        die("launch pid owner mismatch; not signaling")
    first = live_pgid(pid)
    second = live_pgid(pid)
    if first != second or first != pid or first <= 1:
        die("launch pid is not its own process group; not signaling the group")
    os.kill(-first, signal.SIGTERM)


def exec_setsid(argv: list[str]) -> None:
    if not argv:
        die("exec-setsid missing command", 2)
    os.setsid()
    os.execvp(argv[0], argv)


def on_walk_error(err: OSError) -> None:
    raise err


def walk_entries(root: str):
    try:
        yield from os.walk(root, onerror=on_walk_error, followlinks=False)
    except OSError as exc:
        die(f"unreadable: {root}: {exc}")


def hash_tree(root: str) -> str:
    if os.path.islink(root) or not os.path.isdir(root):
        die(f"hash target is not a real directory: {root}")
    digest = hashlib.sha256()
    saw_root = False
    for dirpath, dirnames, filenames in walk_entries(root):
        saw_root = True
        dirnames.sort()
        filenames.sort()
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            try:
                info = os.lstat(path)
            except OSError as exc:
                die(f"unreadable: {path}: {exc}")
            rel = os.path.relpath(path, root)
            digest.update(rel.encode("utf-8", "surrogateescape"))
            digest.update(b"\0")
            digest.update(str(info.st_mode).encode("ascii"))
            digest.update(b"\0")
            if stat.S_ISLNK(info.st_mode):
                try:
                    digest.update(os.readlink(path).encode("utf-8", "surrogateescape"))
                except OSError as exc:
                    die(f"unreadable: {path}: {exc}")
            elif stat.S_ISREG(info.st_mode):
                try:
                    with open(path, "rb") as handle:
                        while True:
                            chunk = handle.read(1024 * 1024)
                            if not chunk:
                                break
                            digest.update(chunk)
                except OSError as exc:
                    die(f"unreadable: {path}: {exc}")
            elif stat.S_ISDIR(info.st_mode):
                digest.update(b"D")
            else:
                die(f"unreadable special file: {path}")
            digest.update(b"\0")
    if not saw_root:
        die(f"unreadable: {root}")
    return digest.hexdigest()


def fingerprint_path(path: str) -> str:
    if not os.path.lexists(path):
        return f"ABSENT {path}"
    try:
        info = os.lstat(path)
    except OSError as exc:
        die(f"unreadable: {path}: {exc}")
    if stat.S_ISLNK(info.st_mode):
        try:
            target = os.readlink(path)
        except OSError as exc:
            die(f"unreadable: {path}: {exc}")
        return f"LINK {target} {path}"
    if stat.S_ISDIR(info.st_mode):
        return f"DIR {hash_tree(path)} {path}"
    if stat.S_ISREG(info.st_mode):
        try:
            with open(path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        except OSError as exc:
            die(f"unreadable: {path}: {exc}")
        return f"FILE {digest} {path}"
    die(f"unreadable special file: {path}")
    return ""


def prefs_paths(extra: list[str]) -> list[str]:
    home = real_home()
    paths = [os.path.join(home, ".psych-cert-gen")]
    if platform_name() == "Darwin":
        library = os.path.join(home, "Library", "Preferences")
        paths.append(os.path.join(library, "edu.rutgers.gsapp.psych-cert-gen.plist"))
        paths.append(
            os.path.join(
                library,
                "com.apple.LaunchServices",
                "com.apple.launchservices.secure.plist",
            )
        )
    for item in extra:
        if item:
            paths.append(item)
    return paths


def record_before(dest: str, extra: list[str]) -> None:
    lines = [fingerprint_path(path) for path in prefs_paths(extra)]
    parent = os.path.dirname(dest)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".before.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            for line in lines:
                handle.write(line + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
        tmp = ""
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    os.chmod(dest, 0o600)


def compare_before(manifest: str, extra: list[str]) -> None:
    if os.path.islink(manifest):
        die("before-manifest is a symlink")
    try:
        recorded = Path(manifest).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        die(f"unreadable manifest: {exc}")
    current = [fingerprint_path(path) for path in prefs_paths(extra)]
    if recorded != current:
        die("before-state changed:\n" + "\n".join(current))


def new_since(root: str, epoch_ns: int) -> list[str]:
    if os.path.islink(root) or not os.path.isdir(root):
        die(f"watch root is not a real directory: {root}")
    found: list[str] = []
    for dirpath, _dirnames, filenames in walk_entries(root):
        for name in filenames:
            if name == ".DS_Store":
                continue
            path = os.path.join(dirpath, name)
            try:
                info = os.lstat(path)
            except OSError as exc:
                die(f"unreadable: {path}: {exc}")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                continue
            if info.st_mtime_ns >= epoch_ns:
                found.append(path)
    return sorted(found)


def evidence_dir(state: str) -> str:
    assert_private(state)
    name_path = os.path.join(state, "evidence-name")
    inode_path = os.path.join(state, "evidence-inode")
    if os.path.islink(name_path) or os.path.islink(inode_path):
        die("evidence pointer is a symlink")
    name = Path(name_path).read_text(encoding="utf-8").strip()
    if not EVIDENCE_DIR_NAME.fullmatch(name):
        die("bad evidence directory name")
    evidence = os.path.join(state, name)
    if os.path.islink(evidence) or not os.path.isdir(evidence):
        die("evidence dir is not a real directory")
    info = os.lstat(evidence)
    saved = Path(inode_path).read_text(encoding="utf-8").strip()
    if saved != f"{info.st_dev}:{info.st_ino}":
        die("evidence directory was swapped")
    resolved = full_realpath(evidence)
    if not under_root(resolved, state):
        die("evidence directory escapes the state dir")
    if os.path.dirname(resolved) != full_realpath(state):
        die("evidence directory is not a direct child of the state dir")
    return evidence


def _strict_ancestor(ancestor: str, descendant: str) -> bool:
    ancestor = ancestor.rstrip("/") or "/"
    descendant = descendant.rstrip("/") or "/"
    if ancestor == "/":
        return descendant != "/"
    return descendant.startswith(ancestor + "/")


def _inside(path: str, root: str) -> bool:
    root = root.rstrip("/") or "/"
    path = path.rstrip("/") or "/"
    return path == root or path.startswith(root + "/")


def _realpath_dir(path: str) -> str:
    if os.path.islink(path):
        die(f"refusing symlink: {path}")
    if not os.path.isdir(path):
        die(f"not a directory: {path}")
    return os.path.realpath(path)


def guard_dest(state: str, dest: str) -> str:
    """Resolve a file a tool is about to write.

    Rejects ``..`` and ``.`` segments before realpath. A symlink is allowed
    only when it is a strict ancestor of this run's state or evidence
    directory (for example ``/tmp`` on macOS). Every other symlink is refused.
    A missing final component is resolved from its real parent. The result
    must sit inside the state directory or the evidence directory.
    """
    if not dest or "\x00" in dest or "\n" in dest:
        die("refusing destination")
    if not dest.startswith("/"):
        die("refusing relative destination")
    parts = dest.split("/")[1:]
    if any(part in ("", ".", "..") for part in parts):
        die("refusing . or .. in destination")
    state_real = _realpath_dir(state)
    evidence_real = _realpath_dir(evidence_dir(state))
    roots = (state_real, evidence_real)
    literal = "/"
    resolved = ""
    for index, part in enumerate(parts):
        literal = "/" + part if literal == "/" else literal + "/" + part
        last = index == len(parts) - 1
        if os.path.islink(literal):
            link_real = os.path.realpath(literal)
            if any(_strict_ancestor(link_real, root) for root in roots):
                continue
            die(f"refusing symlink: {literal}")
        if last and not os.path.lexists(literal):
            parent = os.path.dirname(literal)
            if os.path.islink(parent) or not os.path.isdir(parent):
                die("destination parent is not a real directory")
            parent_real = os.path.realpath(parent)
            if not any(_inside(parent_real, root) for root in roots):
                die("destination escapes the run")
            resolved = parent_real + "/" + part
            break
        if not os.path.exists(literal):
            die("destination parent is missing")
    if not resolved:
        if os.path.islink(literal):
            die(f"refusing symlink: {literal}")
        resolved = os.path.realpath(literal)
    if not any(_inside(resolved, root) for root in roots):
        die("destination escapes the run")
    if resolved in roots:
        die("refusing to write the directory itself")
    if os.path.dirname(resolved) == state_real and os.path.basename(resolved) in HELPER_NAMES:
        die(f"refusing helper file: {os.path.basename(resolved)}")
    return resolved


def capture_destination(state: str, name: str) -> tuple[str, str]:
    if name in (".", "..") or name in HELPER_NAMES or not CAPTURE_NAME.fullmatch(name):
        die(f"refusing capture name: {name}")
    if "/" in name or "\\" in name:
        die("capture name contains a path separator")
    evidence = evidence_dir(state)
    candidate = full_realpath(os.path.join(evidence, name))
    parent = full_realpath(evidence)
    if os.path.dirname(candidate) != parent:
        die("capture path escapes the evidence dir")
    if not under_root(candidate, evidence):
        die("capture path escapes the evidence dir")
    dest = os.path.join(evidence, name)
    if os.path.lexists(dest):
        if os.path.islink(dest):
            die("refusing symlink at capture path")
    return evidence, name


def write_evidence(state: str, name: str, payload: bytes) -> None:
    evidence, leaf = capture_destination(state, name)
    dest = os.path.join(evidence, leaf)
    if os.path.lexists(dest):
        die("refusing to overwrite evidence")
    directory = os.open(evidence, os.O_RDONLY | os.O_DIRECTORY)
    try:
        info = os.fstat(directory)
        expected = Path(os.path.join(state, "evidence-inode")).read_text(encoding="utf-8").strip()
        if expected != f"{info.st_dev}:{info.st_ino}":
            die("evidence directory was swapped")
        fd = os.open(
            leaf,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    try:
        view = payload
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    if mode_of(dest) != 0o600 or os.path.islink(dest):
        die("evidence file mode is not 0600")


def append_evidence(state: str, name: str, payload: bytes) -> None:
    evidence, leaf = capture_destination(state, name)
    dest = os.path.join(evidence, leaf)
    if os.path.lexists(dest) and os.path.islink(dest):
        die("refusing symlink at capture path")
    directory = os.open(evidence, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = os.open(
            leaf,
            os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    try:
        view = payload
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def make_writable_tree(path: str) -> None:
    if os.path.islink(path):
        return
    info = os.lstat(path)
    os.chmod(path, info.st_mode | stat.S_IWUSR | stat.S_IXUSR)
    if not stat.S_ISDIR(info.st_mode):
        return
    for dirpath, dirnames, filenames in walk_entries(path):
        for name in dirnames + filenames:
            entry = os.path.join(dirpath, name)
            if os.path.islink(entry):
                continue
            try:
                current = os.lstat(entry)
            except OSError as exc:
                die(f"unreadable: {entry}: {exc}")
            os.chmod(entry, current.st_mode | stat.S_IWUSR | stat.S_IXUSR)


def wipe(path: str, state_root: str) -> None:
    if not under_root(path, state_root):
        die("refuse wipe outside state")
    if os.path.islink(path):
        os.unlink(path)
        return
    if not os.path.exists(path):
        return
    root_info = os.lstat(state_root)
    if root_info.st_uid != os.getuid():
        die("refuse wipe of a state dir we do not own")
    make_writable_tree(path)
    shutil.rmtree(path)


def wipe_scratch(state: str) -> None:
    assert_private(state)
    for name in ("home", "tmp", "output", "logs", "pass"):
        path = os.path.join(state, name)
        if os.path.lexists(path):
            wipe(path, state)
    sock = os.path.join(state, "browser.sock")
    ready = os.path.join(state, "browser.ready")
    for path in (sock, ready):
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.exists(path):
            os.unlink(path)


def copy_tracked(src: str, dest: str) -> None:
    if os.path.exists(dest):
        die(f"sandbox dest exists: {dest}")
    os.mkdir(dest, 0o700)
    try:
        listing = subprocess.run(
            ["git", "-C", src, "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        die(f"git ls-files failed: {exc}")
    for raw in listing.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        if rel.startswith("/") or rel.startswith("../") or "/../" in rel or rel == "..":
            die(f"refusing tracked path: {rel}")
        parts = rel.split("/")
        if "node_modules" in parts:
            continue
        source = os.path.join(src, rel)
        target = os.path.join(dest, rel)
        if os.path.islink(source):
            continue
        if not os.path.isfile(source):
            continue
        os.makedirs(os.path.dirname(target), 0o700, exist_ok=True)
        with open(source, "rb") as handle:
            payload = handle.read()
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)


def side_effect(log_path: str, scheme: str, target: str) -> None:
    if scheme not in STUBBED_SCHEMES:
        die(f"not a stubbed scheme: {scheme}", 2)
    if "\n" in target or "\r" in target:
        die("side-effect target contains a newline")
    parent = os.path.dirname(log_path) or "."
    if os.path.lexists(log_path) and os.path.islink(log_path):
        die("side-effect log is a symlink")
    line = f"{scheme} {target}\n".encode("utf-8")
    fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, line)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    # Names are recorded in order. Nothing is opened, dialed, or sent.
    del parent


def side_effect_names(log_path: str) -> None:
    if os.path.islink(log_path):
        die("side-effect log is a symlink")
    text = Path(log_path).read_text(encoding="utf-8")
    for line in text.splitlines():
        scheme, _sep, _target = line.partition(" ")
        sys.stdout.write(scheme + "\n")


def url_exact(url: str, expected_path: str) -> None:
    parts = urlsplit(url)
    if parts.path != expected_path:
        die(f"path {parts.path!r} != {expected_path!r}")


def http_exact(url: str, expected_path: str, timeout: float = 2) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1":
        die(f"refusing URL host: {url}")
    if parts.path != expected_path:
        die(f"path {parts.path!r} != {expected_path!r}")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = urlsplit(response.geturl())
            if final.scheme != "http" or final.hostname != "127.0.0.1":
                die(f"redirected off loopback: {response.geturl()}")
            if final.path != expected_path:
                die(f"redirected path {final.path!r} != {expected_path!r}")
            if response.status != 200:
                die(f"HTTP {response.status}")
            return response.read()
    except urllib.error.URLError as exc:
        die(f"request failed: {exc}")
    return b""


def health_ok(url: str, expect_pid: int) -> None:
    body = http_exact(url, "/health")
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        die(f"health body is not JSON: {exc}")
    if payload.get("status") != "healthy":
        die(f"health status is {payload.get('status')!r}")
    if int(payload.get("pid", -1)) != expect_pid:
        die(f"health pid {payload.get('pid')!r} != {expect_pid}")


def find_exe(name: str) -> str:
    path_env = os.environ.get("PATH", "")
    for directory in path_env.split(":"):
        if not directory:
            continue
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK) and not os.path.islink(candidate):
            return full_realpath(candidate)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return full_realpath(candidate)
    home = real_home()
    extras: list[str] = []
    if name == "uv":
        extras.append(os.path.join(home, ".local", "bin", "uv"))
    elif name == "bun":
        extras.append(os.path.join(home, ".bun", "bin", "bun"))
    elif name == "node":
        extras.append("/usr/local/bin/node")
    elif name == "pdftotext":
        extras.extend(
            [
                "/usr/bin/pdftotext",
                "/usr/local/bin/pdftotext",
                "/opt/homebrew/bin/pdftotext",
            ]
        )
    for candidate in extras:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return full_realpath(candidate)
    die(f"{name} not found")
    return ""


def _pass_or_sandbox(env_key: str, current: str, fallback: str, sandbox: str) -> str:
    if current:
        return current
    if os.path.exists(fallback):
        return fallback
    return sandbox


def child_env(state: str) -> None:
    require_platform()
    assert_private(state)
    home = os.path.join(state, "home")
    if os.path.islink(home) or not os.path.isdir(home):
        die("isolated HOME is missing")
    real = real_home()
    values: list[tuple[str, str]] = []

    def add(key: str, value: str) -> None:
        if "\n" in value or "\0" in value:
            die(f"unsafe environment value for {key}")
        values.append((key, value))

    add("HOME", home)
    add("TMPDIR", os.path.join(state, "tmp"))
    add("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    add("USER", os.environ.get("USER", ""))
    add("LOGNAME", os.environ.get("LOGNAME", os.environ.get("USER", "")))
    add("LANG", os.environ.get("LANG", "C.UTF-8"))
    add("LC_ALL", "C")
    add("TZ", "UTC0")
    add("GOTELEMETRY", "off")
    add(
        "GOMODCACHE",
        _pass_or_sandbox(
            "GOMODCACHE",
            os.environ.get("GOMODCACHE", ""),
            os.path.join(real, "go", "pkg", "mod"),
            os.path.join(state, "pass", "gomodcache"),
        ),
    )
    add(
        "GOENV",
        _pass_or_sandbox(
            "GOENV",
            os.environ.get("GOENV", ""),
            os.path.join(real, ".config", "go", "env"),
            os.path.join(state, "pass", "goenv"),
        ),
    )
    playwright_default = (
        os.path.join(real, "Library", "Caches", "ms-playwright")
        if platform_name() == "Darwin"
        else os.path.join(real, ".cache", "ms-playwright")
    )
    add(
        "PLAYWRIGHT_BROWSERS_PATH",
        _pass_or_sandbox(
            "PLAYWRIGHT_BROWSERS_PATH",
            os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
            playwright_default,
            os.path.join(state, "pass", "playwright"),
        ),
    )
    npm_cache = os.environ.get("NPM_CONFIG_CACHE", "")
    if not npm_cache:
        npm = shutil.which("npm")
        if npm:
            probe = subprocess.run(
                [npm, "config", "get", "cache"],
                check=False,
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0 and probe.stdout.strip() and probe.stdout.strip() != "undefined":
                npm_cache = probe.stdout.strip()
    if not npm_cache:
        npm_cache = os.path.join(real, ".npm") if os.path.isdir(os.path.join(real, ".npm")) else os.path.join(state, "pass", "npm")
    add("NPM_CONFIG_CACHE", npm_cache)
    userconfig = os.path.join(real, ".npmrc")
    if os.path.isfile(userconfig) and not os.path.islink(userconfig):
        add("NPM_CONFIG_USERCONFIG", userconfig)
    uv_cache = os.environ.get("UV_CACHE_DIR", "")
    if not uv_cache and os.path.isdir(os.path.join(real, ".cache", "uv")):
        uv_cache = os.path.join(real, ".cache", "uv")
    if uv_cache:
        add("UV_CACHE_DIR", uv_cache)
    bun_cache = os.path.join(real, ".bun", "install", "cache")
    if os.path.isdir(bun_cache):
        add("BUN_INSTALL_CACHE_DIR", bun_cache)
    add("XDG_CONFIG_HOME", os.path.join(home, ".config"))
    add("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
    add("XDG_CACHE_HOME", os.path.join(home, ".cache"))
    add("PYTHONUNBUFFERED", "1")
    if platform_name() == "Darwin":
        add("CFFIXED_USER_HOME", home)
    for key, value in values:
        sys.stdout.write(f"{key}={value}\n")


def versions_agree(repo: str) -> str:
    package = json.loads(Path(repo, "package.json").read_text(encoding="utf-8"))
    pkg_version = str(package.get("version", ""))
    pyproject = Path(repo, "pyproject.toml").read_text(encoding="utf-8")
    py_version = ""
    for line in pyproject.splitlines():
        if line.startswith("version = "):
            py_version = line.split("=", 1)[1].strip().strip('"')
            break
    tauri = json.loads(Path(repo, "src-tauri", "tauri.conf.json").read_text(encoding="utf-8"))
    tauri_version = str(tauri.get("version", ""))
    if not pkg_version or pkg_version != py_version or pkg_version != tauri_version:
        die(
            "version files disagree: "
            f"package.json={pkg_version} pyproject={py_version} tauri={tauri_version}"
        )
    return pkg_version


def prove_pdfs(output: str, epoch_ns: int, evidence_state: str) -> None:
    files = new_since(output, epoch_ns)
    pdfs: list[str] = []
    reports: list[str] = []
    unexpected: list[str] = []
    for path in files:
        name = os.path.basename(path)
        if name.lower().endswith(".pdf"):
            pdfs.append(path)
        elif name == "ineligibility_report.xlsx":
            reports.append(path)
        else:
            unexpected.append(path)
    if unexpected:
        die("unexpected output files: " + ", ".join(unexpected))
    if len(pdfs) != 8:
        die(f"expected exactly 8 new PDFs, found {len(pdfs)}: {pdfs}")
    if len(reports) != 1:
        die("expected exactly one ineligibility_report.xlsx")
    pdftotext = find_exe("pdftotext")
    chunks: list[str] = []
    for pdf in pdfs:
        proc = subprocess.run(
            [pdftotext, "-layout", pdf, "-"],
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            die(f"pdftotext failed for {pdf}: {proc.stderr.decode('utf-8', 'replace')}")
        chunks.append(proc.stdout.decode("utf-8", "replace"))
    combined = "\n".join(chunks)
    folded = re.sub(r"\s+", " ", combined)
    required = (
        "Avery Chen",
        "October 6, 2026",
        "Amira Solano",
        "Ethics and Practice in School-Based Mental Health",
    )
    missing = [item for item in required if item not in folded]
    if missing:
        die("PDF text missing: " + ", ".join(missing))
    if "CE CREDITS: 3" not in folded and "CE CREDIT HOURS: 3" not in folded:
        die("PDF text missing credit hours")
    if "Morgan Hale" in folded:
        die("host Morgan Hale was printed on a certificate")
    append_evidence(evidence_state, "pdf-text.txt", combined.encode("utf-8"))
    names = "\n".join(os.path.basename(path) for path in pdfs) + "\n"
    append_evidence(evidence_state, "pdf-names.txt", names.encode("utf-8"))


def doctor(state: str, repo: str) -> None:
    state_file = os.path.join(state, "run.env")
    version = versions_agree(repo)
    api = saved_identity(state_file, "API")
    if api is None:
        die("API identity is not recorded")
    if not identity_matches(api):
        die("API identity mismatch")
    health_ok("http://127.0.0.1:8008/health", int(api["pid"]))
    http_exact("http://127.0.0.1:1420/", "/")
    ui = saved_identity(state_file, "UI")
    if ui is None or not identity_matches(ui):
        die("UI identity mismatch")
    browser = saved_identity(state_file, "BROWSER")
    if browser is not None and not identity_matches(browser):
        die("browser identity mismatch")
    evidence = evidence_dir(state)
    sys.stdout.write(f"version={version}\n")
    sys.stdout.write(f"api_pid={api['pid']}\n")
    sys.stdout.write(f"ui_pid={ui['pid']}\n")
    sys.stdout.write("ui=http://127.0.0.1:1420/\n")
    sys.stdout.write("api=http://127.0.0.1:8008/health\n")
    sys.stdout.write(f"evidence={evidence}\n")


def rpc(sock_path: str, op: str, args: list[str]) -> None:
    if os.path.islink(sock_path):
        die("browser socket is a symlink")
    payload = json.dumps({"op": op, "args": args}).encode("utf-8") + b"\n"
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(180)
    try:
        client.connect(sock_path)
        client.sendall(payload)
        buf = b""
        while b"\n" not in buf:
            chunk = client.recv(1 << 20)
            if not chunk:
                break
            buf += chunk
            if len(buf) > 8 << 20:
                die("rpc response too large")
    except OSError as exc:
        die(f"browser rpc failed: {exc}")
    finally:
        client.close()
    if not buf:
        die("empty browser rpc response")
    message = json.loads(buf.decode("utf-8"))
    if not message.get("ok"):
        die(str(message.get("error", "browser command failed")))
    data = message.get("data")
    if data:
        sys.stdout.write(str(data))
        if not str(data).endswith("\n"):
            sys.stdout.write("\n")


def port_free(port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    except OSError:
        die(f"127.0.0.1:{port} is already in use")
    finally:
        probe.close()


def read_pointer(path: str) -> str:
    if os.path.islink(path):
        die("run pointer is a symlink")
    name = Path(path).read_text(encoding="utf-8").strip()
    if not STATE_DIR_NAME.fullmatch(name):
        die("run pointer is not a state directory name")
    return name


def resolve_run(run_id: str) -> str:
    valid_run_id(run_id)
    root = registry_path()
    pointer = os.path.join(root, f"id-{run_id}")
    if not os.path.isfile(pointer):
        die(f"unknown run id: {run_id}")
    name = read_pointer(pointer)
    state = os.path.join(root, name)
    resolved = full_realpath(state)
    if os.path.dirname(resolved) != full_realpath(root):
        die("state dir escapes the registry")
    assert_private(resolved)
    return resolved


def init_evidence(state: str, evidence: str) -> None:
    tighten_created_dir(evidence)
    name = os.path.basename(evidence)
    if not EVIDENCE_DIR_NAME.fullmatch(name):
        die("unexpected evidence directory name")
    info = os.lstat(evidence)
    name_path = os.path.join(state, "evidence-name")
    inode_path = os.path.join(state, "evidence-inode")
    fd = os.open(name_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, (name + "\n").encode("ascii"))
    os.close(fd)
    fd = os.open(inode_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, f"{info.st_dev}:{info.st_ino}\n".encode("ascii"))
    os.close(fd)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        die("missing command", 2)
    command = argv[1]
    args = argv[2:]
    if command == "platform":
        if args:
            os.environ["PSYCH_CERT_VERIFY_ASSUME_UNAME"] = args[0]
        sys.stdout.write(require_platform() + "\n")
        return 0
    if command == "assert-private":
        assert_private(args[0])
        return 0
    if command == "refuse-caller":
        refuse_caller_dir(args[0])
        return 0
    if command == "tighten-created":
        tighten_created_dir(args[0])
        return 0
    if command == "mode":
        sys.stdout.write(f"{mode_of(args[0]):04o}\n")
        return 0
    if command == "temp-ok":
        require_temp_path(args[0])
        return 0
    if command == "guard":
        require_inside(args[0], args[1])
        return 0
    if command == "guard-dest":
        sys.stdout.write(guard_dest(args[0], args[1]) + "\n")
        return 0
    if command == "registry":
        sys.stdout.write(registry_path() + "\n")
        return 0
    if command == "make-run-id":
        sys.stdout.write(make_run_id() + "\n")
        return 0
    if command == "valid-id":
        valid_run_id(args[0] if args else "")
        return 0
    if command == "read-state":
        read_state(args[0], args[1])
        return 0
    if command == "write-state":
        write_state(args[0], args[1], args[2])
        return 0
    if command == "ps-identity":
        ident = ps_identity(int(args[0]))
        sys.stdout.write(json.dumps(ident) + "\n")
        return 0
    if command == "write-identity":
        write_identity(args[0], args[1], int(args[2]))
        return 0
    if command == "all-dead":
        all_dead(os.path.join(args[0], "run.env"))
        return 0
    if command == "confirm-all":
        state_file = os.path.join(args[0], "run.env")
        saw_alive = False
        for label in LABELS:
            kind = confirm_label(state_file, label)
            if kind == "alive":
                saw_alive = True
            if kind == "dead":
                die(f"{label} is not running; identity cannot be confirmed")
        if not saw_alive:
            die("no processes to confirm")
        return 0
    if command == "signal-confirmed":
        signal_confirmed(os.path.join(args[0], "run.env"))
        return 0
    if command == "signal-launch-group":
        signal_launch_group(int(args[0]))
        return 0
    if command == "exec-setsid":
        if args and args[0] == "--":
            args = args[1:]
        exec_setsid(args)
        return 0
    if command == "hash-tree":
        sys.stdout.write(hash_tree(args[0]) + "\n")
        return 0
    if command == "record-before":
        record_before(args[0], args[1:])
        return 0
    if command == "compare-before":
        compare_before(args[0], args[1:])
        return 0
    if command == "new-since":
        for path in new_since(args[0], int(args[1])):
            sys.stdout.write(path + "\n")
        return 0
    if command == "write-evidence":
        write_evidence(args[0], args[1], sys.stdin.buffer.read())
        return 0
    if command == "append-evidence":
        append_evidence(args[0], args[1], sys.stdin.buffer.read())
        return 0
    if command == "evidence-dir":
        sys.stdout.write(evidence_dir(args[0]) + "\n")
        return 0
    if command == "init-evidence":
        init_evidence(args[0], args[1])
        return 0
    if command == "wipe":
        wipe(args[0], args[1])
        return 0
    if command == "wipe-scratch":
        wipe_scratch(args[0])
        return 0
    if command == "copy-tracked":
        copy_tracked(args[0], args[1])
        return 0
    if command == "side-effect":
        side_effect(args[0], args[1], args[2])
        return 0
    if command == "side-effect-names":
        side_effect_names(args[0])
        return 0
    if command == "url-exact":
        url_exact(args[0], args[1])
        return 0
    if command == "health-ok":
        health_ok(args[0], int(args[1]))
        return 0
    if command == "http-exact":
        http_exact(args[0], args[1])
        return 0
    if command == "find-exe":
        sys.stdout.write(find_exe(args[0]) + "\n")
        return 0
    if command == "child-env":
        child_env(args[0])
        return 0
    if command == "versions":
        sys.stdout.write(versions_agree(args[0]) + "\n")
        return 0
    if command == "prove-pdfs":
        prove_pdfs(args[0], int(args[1]), args[2])
        return 0
    if command == "doctor":
        doctor(args[0], args[1])
        return 0
    if command == "rpc":
        rpc(args[0], args[1], args[2:])
        return 0
    if command == "port-free":
        port_free(int(args[0]))
        return 0
    if command == "read-pointer":
        sys.stdout.write(read_pointer(args[0]) + "\n")
        return 0
    if command == "resolve-run":
        sys.stdout.write(resolve_run(args[0]) + "\n")
        return 0
    if command == "now-ns":
        sys.stdout.write(str(time.time_ns()) + "\n")
        return 0
    if command == "prefs-extra":
        extra = os.environ.get("PSYCH_CERT_VERIFY_PREFS_EXTRA", "")
        if extra:
            sys.stdout.write(extra + "\n")
        return 0
    die(f"unknown command: {command}", 2)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except BrokenPipeError:
        raise SystemExit(0) from None
