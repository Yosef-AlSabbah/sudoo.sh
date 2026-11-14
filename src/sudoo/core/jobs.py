"""Background actions ("jobs") such as creating, restarting or updating an instance.

Every action runs in its own thread. Actions on the same instance run one after another (a lock per instance);
actions on different instances run in parallel. A job records user-facing steps, notes and the full technical
log, which the panel shows while it runs and afterwards (the last 300 jobs are kept in memory).

Every change of a job is published as a live event (core/events.py): "job" when it starts, moves to another step,
adds a note or ends, and "job.output" with new log text at most twice a second.
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from typing import Any

from sudoo.core import events
from sudoo.core.hints import friendly_hint

JOBS: OrderedDict[str, Job] = OrderedDict()
_JOBS_LOCK = threading.Lock()
INSTANCE_LOCKS: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
ACTIVE_JOB: dict[str, Job] = {}  # instance name -> the job currently running on it
_KEEP = 300
_OUTPUT_EVERY_SECONDS = 0.5


class JobError(Exception):
    """A step failed; the message is shown to the user."""


class Job:
    def __init__(self, instance: str, action: str, kind: str, user: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.instance = instance
        self.action = action  # title shown to the user, e.g. "Restart"
        self.kind = kind  # machine name, e.g. "restart"
        self.user = user  # account name, or "visitor" / "system" for automatic jobs
        self.status = "queued"
        self.steps: list[dict[str, str]] = []
        self.notes: list[dict[str, str]] = []
        self.log: list[str] = []
        self.result: dict[str, Any] = {}
        self.hint: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        self._published_lines = 0  # log lines already sent as "job.output" events
        self.expected_steps: int | None = None  # set by operations that know how many steps they take

    def expect(self, steps: int) -> None:
        """Announce how many steps this job will take, so its progress can be shown as a percentage."""
        self.expected_steps = steps

    def progress_percent(self) -> int | None:
        """Finished steps out of the expected ones (a running job stays below 100); None when unknown."""
        if self.status == "success":
            return 100
        if self.status == "queued":
            return 0
        if not self.expected_steps:
            return None
        done = sum(1 for step in self.steps if step["status"] == "done")
        return min(99, round(100 * done / max(self.expected_steps, len(self.steps))))

    def changed(self) -> None:
        """Tell connected clients that this job changed."""
        events.publish("job", self.id)

    def publish_output(self) -> None:
        """Send the log lines written since the last call as one "job.output" event."""
        end = len(self.log)
        if end > self._published_lines:
            text = "".join(self.log[self._published_lines : end])
            events.publish(
                "job.output",
                self.id,
                {"job": self.id, "offset": self._published_lines, "next_offset": end, "text": text},
            )
            self._published_lines = end

    def write(self, text: str) -> None:
        self.log.append(text)

    def step(self, title: str) -> None:
        """Start a new user-facing step; the previous one is marked done."""
        for step in self.steps:
            if step["status"] == "running":
                step["status"] = "done"
        self.steps.append({"title": title, "status": "running"})
        self.write(f"\n== {title}\n")
        self.changed()

    def note(self, text: str, level: str = "info") -> None:
        """A message for the user that does not stop the job ("info" or "warning")."""
        self.notes.append({"text": text, "level": level})
        self.write(f"[{level}] {text}\n")
        self.changed()

    def run(self, cmd: list[str], timeout: float | None = None, input: str | None = None) -> None:
        """Run a command, stream its output into the log, raise JobError when it fails."""
        if self.run_unchecked(cmd, timeout, input) != 0:
            raise JobError(f"command failed: {' '.join(cmd[:4])} ...")

    def run_unchecked(self, cmd: list[str], timeout: float | None = None, input: str | None = None) -> int:
        """Run a command, stream its output into the log, return its exit code."""
        self.write(f"$ {' '.join(cmd)}\n")
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if input:
            assert proc.stdin is not None
            proc.stdin.write(input)
            proc.stdin.close()
        deadline = time.time() + timeout if timeout else None
        assert proc.stdout is not None
        for line in proc.stdout:
            self.write(line)
            if deadline and time.time() > deadline:
                proc.kill()
                raise JobError("this step took too long and was stopped")
        return proc.wait()

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instance": self.instance,
            "action": self.action,
            "kind": self.kind,
            "user": self.user,
            "status": self.status,
            "started": self.started,
            "finished": self.finished,
            "steps": self.steps,
        }


def is_panel_job(instance: str) -> bool:
    """Jobs of the panel itself (plugins) use an "instance" with a colon, which no instance name can have."""
    return ":" in instance


def start(instance: str, action: str, kind: str, fn: Callable[..., object], *args: Any, user: str = "system") -> Job:
    """Run fn(job, *args) in the background for `instance` and return the Job."""
    job = Job(instance, action, kind, user)
    with _JOBS_LOCK:
        JOBS[job.id] = job
        while len(JOBS) > _KEEP:
            JOBS.popitem(last=False)
    _start_output_publisher()
    job.changed()
    threading.Thread(target=_run, args=(job, fn, args), daemon=True).start()
    return job


def _run(job: Job, fn: Callable[..., object], args: tuple[Any, ...]) -> None:
    with INSTANCE_LOCKS[job.instance]:
        ACTIVE_JOB[job.instance] = job
        job.status = "running"
        job.changed()
        if not is_panel_job(job.instance):
            events.publish("instance", job.instance)
        try:
            fn(job, *args)
            for step in job.steps:
                step["status"] = "done"
            job.status = "success"
        except Exception as exc:  # noqa: BLE001 - every failure is reported to the user in the job
            for step in job.steps:
                if step["status"] == "running":
                    step["status"] = "failed"
            job.status = "failed"
            job.write(f"\nERROR: {exc}\n")
            job.hint = friendly_hint("".join(job.log))
        finally:
            job.finished = time.time()
            ACTIVE_JOB.pop(job.instance, None)
            job.publish_output()
            job.changed()
            if job.kind == "delete" and job.status == "success":
                events.publish("instance.deleted", job.instance, {"name": job.instance})
            elif not is_panel_job(job.instance):
                events.publish("instance", job.instance)


_publisher_started = threading.Event()


def _start_output_publisher() -> None:
    """Once: a thread that sends the new log text of running jobs as live events."""
    if _publisher_started.is_set():
        return
    _publisher_started.set()

    def publish_forever() -> None:
        while True:
            time.sleep(_OUTPUT_EVERY_SECONDS)
            for job in list(ACTIVE_JOB.values()):
                job.publish_output()

    threading.Thread(target=publish_forever, daemon=True, name="job-output").start()


def busy(instance: str) -> bool:
    return INSTANCE_LOCKS[instance].locked()


def recent(instance: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    """Summaries of the most recent jobs, optionally for one instance only."""
    with _JOBS_LOCK:
        jobs = [j for j in reversed(JOBS.values()) if instance is None or j.instance == instance]
    return [j.summary() for j in jobs[:limit]]
