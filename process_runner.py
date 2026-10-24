"""Bounded generation processes with explicit POSIX process-group cleanup."""

from __future__ import annotations

from contextlib import contextmanager
import os
import signal
import subprocess
import threading


class TerminationRequested(Exception):
    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(f"Cancelled by signal {signum}")


@contextmanager
def cancellation_signals():
    """Only main-thread calls can handle signals; restore embedding caller handlers."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    def cancel(signum, frame):
        raise TerminationRequested(signum)
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        for signum in previous:
            signal.signal(signum, cancel)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _stop_group(process: subprocess.Popen) -> None:
    if os.name == "posix":
        # The group may contain grandchildren even if the direct child has exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        # Windows is a CPU development target, not the supported GPU deployment host.
        process.kill()
    process.wait()


def run_generation(command: list[str], *, env: dict, timeout: float | None):
    process = subprocess.Popen(command, env=env, start_new_session=os.name == "posix")
    try:
        code = process.wait(timeout=timeout)
        return subprocess.CompletedProcess(command, code)
    finally:
        # Cleanup also on timeout, cancellation, wait errors and normal child exit.
        # Do not orphan a spawned helper that outlives its owning generation job.
        _stop_group(process)
