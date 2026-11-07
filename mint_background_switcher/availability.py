"""Bounded reachability probing for picture-collection folders.

A picture collection that lives on an unresponsive mount (a dead SMB/CIFS or
NFS share, a disconnected network drive) makes ordinary Python filesystem
calls block in the kernel indefinitely: ``os.path.isdir``, ``os.walk``,
``Path.iterdir`` and friends never return, and no ``OSError`` is raised, so
the usual try/except handling cannot help. A thread that enters one of those
calls is stuck for the life of the process (Linux has no way to interrupt a
thread blocked in a D-state syscall), which makes the application appear
frozen.

The probe therefore performs every filesystem touch inside a short-lived
child process, and the parent bounds the wait with a wall-clock deadline.
Two things make the bound honest:

- the child writes its verdict to a temp file instead of a pipe, so the
  parent never reads a pipe that a stuck child might never close; and
- when the deadline passes the parent sends ``SIGKILL`` and *does not wait*
  for the child to be reaped. A child wedged in a D-state kernel syscall
  cannot be killed until the kernel releases the I/O, and waiting for that
  would reproduce the exact hang this module exists to prevent. Abandoned
  children are reaped by init once the kernel gives up on the I/O.

Probe statuses:

- ``ok``           every folder exists and its root listing succeeded.
- ``missing``      at least one folder (or single-image file) does not exist.
                   The filesystem answered promptly; callers keep their
                   established missing-folder fallback behavior.
- ``unresponsive`` a filesystem touch blocked past the deadline; the drive or
                   network share is dead. Callers must reject the operation.
- ``error``        the probe itself could not run (child spawn failed).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Iterable

#: How long a collection root may take to answer before it is declared dead.
#: Healthy local or network roots answer in milliseconds; five seconds leaves
#: ample margin for a slow-but-alive mount while bounding the worst-case UI
#: delay for a rejected switch.
PROBE_TIMEOUT_SECONDS = 5.0

#: Poll cadence while waiting for the probe child to finish.
_POLL_INTERVAL_SECONDS = 0.05

# Runs with ``python -I`` (isolated mode: fast startup, no site-packages).
# argv[1] is the status file to write; argv[2:] are the collection folders
# (directories or single image files). Each path is touched exactly as a
# scanner would touch it (symlinks are followed, matching ``scan_images``):
# a root listing for directories. Any kernel-level block happens in THIS
# process, which the parent abandons (never waits for) past the deadline.
# Verdict format: a single line, either "ok" or "missing <path>".
_PROBE_SNIPPET = (
    "import os, sys\n"
    "out = sys.argv[1]\n"
    "for raw in sys.argv[2:]:\n"
    "    d = os.path.abspath(os.path.expanduser(raw))\n"
    "    if os.path.isdir(d):\n"
    "        with os.scandir(d):\n"
    "            pass\n"
    "    elif not os.path.isfile(d):\n"
    "        with open(out, 'w') as f:\n"
    "            f.write('missing ' + d)\n"
    "        sys.exit(1)\n"
    "with open(out, 'w') as f:\n"
    "    f.write('ok')\n"
    "sys.exit(0)\n"
)


class CollectionUnavailableError(RuntimeError):
    """A profile's picture collection is unreachable and the switch is rejected.

    Raised by callers of :func:`probe_folders` when a profile switch would
    block forever on an unresponsive mount. The message is user-facing.
    """


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a bounded collection probe. See module docstring for statuses."""

    status: str  # "ok" | "missing" | "unresponsive" | "error"
    reason: str = ""  # human-readable detail; empty for "ok"


def probe_folders(folders: Iterable[str], timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    """Check that every collection folder is reachable and listable.

    ``folders`` may contain directories or single image files (both forms a
    profile supports). An empty list is trivially available; callers decide
    what an empty collection means. The check is bounded: it returns within
    ``timeout`` seconds (plus poll granularity) no matter how badly a mount
    is stuck, and it never waits on a child process that a dead mount wedged.
    """
    folder_list = [str(f).strip() for f in folders if str(f).strip()]
    if not folder_list:
        return ProbeResult(status="ok", reason="")

    fd, status_path = tempfile.mkstemp(prefix="mbs-probe-", suffix=".txt")
    os.close(fd)
    try:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-c", _PROBE_SNIPPET, status_path, *folder_list],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, ValueError) as exc:
            return ProbeResult(status="error", reason=f"the availability check itself failed: {exc}")

        deadline = time.monotonic() + max(float(timeout), 0.01)
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                # Kill best-effort and move on; do NOT wait() — a child stuck
                # in a D-state kernel syscall cannot die until the kernel
                # releases the I/O, and init will reap it.
                try:
                    proc.kill()
                except OSError:
                    pass
                return ProbeResult(
                    status="unresponsive",
                    reason=(
                        f"no response within {timeout:g} second(s); "
                        "the drive or network share is unresponsive"
                    ),
                )
            time.sleep(_POLL_INTERVAL_SECONDS)

        try:
            with open(status_path, "r") as f:
                verdict = f.read().strip()
        except OSError:
            verdict = ""
        if proc.returncode == 0 or verdict == "ok":
            return ProbeResult(status="ok", reason="")
        if verdict.startswith("missing "):
            return ProbeResult(status="missing", reason=verdict)
        detail = verdict or f"check exited with code {proc.returncode}"
        return ProbeResult(status="error", reason=detail)
    finally:
        try:
            os.unlink(status_path)
        except OSError:
            pass
