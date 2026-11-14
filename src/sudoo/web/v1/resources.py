"""The resources of /api/v1 as JSON documents: the same shapes in answers and in live events.

No resource contains a password, a key or a port; the instance's credentials are a separate resource that only
roles with "instances.credentials" can read (GET /api/v1/instances/<name>/credentials).
"""

from __future__ import annotations

from typing import Any

from sudoo import exposure
from sudoo.config import settings
from sudoo.core import jobs
from sudoo.core.state import STATE
from sudoo.instances import backups, gateway, metrics, monitor, operations, store
from sudoo.repos.gitrepo import commits, submodules

from .responses import PREFIX, iso


def job_reference(job: jobs.Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "action": job.action,
        "status": job.status,
        "progress_percent": job.progress_percent(),
        "links": {"self": f"{PREFIX}/jobs/{job.id}"},
    }


def job_resource(job: jobs.Job, include_log: bool = False) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "id": job.id,
        "instance": job.instance,
        "action": job.action,
        "kind": job.kind,
        "status": job.status,  # queued, running, success, failed
        "progress_percent": job.progress_percent(),  # None when the number of steps is not known in advance
        "requested_by": job.user,
        "started_at": iso(job.started),
        "finished_at": iso(job.finished),
        "steps": [{"title": step["title"], "status": step["status"]} for step in job.steps],
        "notes": job.notes,
        "error": job.hint if job.status == "failed" else None,
        "links": {
            "self": f"{PREFIX}/jobs/{job.id}",
            "instance": None if jobs.is_panel_job(job.instance) else f"{PREFIX}/instances/{job.instance}",
        },
    }
    if include_log:
        resource["log"] = "".join(job.log)
    return resource


def _usage(name: str) -> dict[str, Any]:
    figures = metrics.INSTANCES.get(name)
    if figures:
        return {key: value for key, value in figures.items() if key != "running"}
    measured = monitor.STATUS.get(name, {})
    return {"cpu_percent": measured.get("cpu", 0), "memory_bytes": measured.get("memory", 0)}


def instance_resource(name: str, full: bool = False) -> dict[str, Any]:
    """An instance as the API shows it: grouped, ISO times, no passwords or ports."""
    env, measured, state = store.read_env(name), monitor.STATUS.get(name, {}), STATE.get(name)
    status = monitor.status(name)
    commit = (measured.get("commit") or "").split("|")
    last_visit = state.get("last_visit")
    pausing = env["AUTO_PAUSE"] == "true" and settings.idle_hours > 0 and status == "online" and last_visit
    current = jobs.ACTIVE_JOB.get(name)
    resource: dict[str, Any] = {
        "name": name,
        "status": status,  # online, starting, busy, paused, switched_off, stopped, unknown
        "url": exposure.address(name),
        "odoo": {"version": env["ODOO_VERSION"], "edition": env["EDITION"], "database": env["DB_NAME"]},
        "git": {
            "repository": measured.get("repo") or None,
            "branch": env["GIT_BRANCH"],
            "branch_deleted_on_github": bool(state.get("branch_missing")),
            "commit": (
                dict(zip(("sha", "subject", "age", "author"), commit, strict=True)) if len(commit) == 4 else None
            ),
        },
        "settings": {
            "auto_update": env["AUTO_UPDATE"] == "true",
            "auto_upgrade": env["AUTO_UPGRADE"] == "true",
            "auto_pause": env["AUTO_PAUSE"] == "true",
            "delete_after_days": int(env["DELETE_AFTER_DAYS"]),
        },
        "usage": _usage(name),
        "uptime": measured.get("uptime") or None,
        "gateway_error": gateway.LISTENER_ERRORS.get(name),
        "created_at": iso(env["CREATED_AT"]),
        "created_by": env.get("CREATED_BY") or None,
        "last_visit_at": iso(last_visit),
        "pauses_at": iso(float(last_visit or 0) + settings.idle_hours * 3600) if pausing else None,
        "expires_at": iso(operations.expires_at(env)),
        "current_job": job_reference(current) if current else None,
        "links": {"self": f"{PREFIX}/instances/{name}"},
    }
    if full:
        addons_dir = store.addons_dir(name)
        disk = monitor.disk_usage(name)
        latest = backups.latest(name)
        resource |= {
            "disk": {"database_bytes": disk.get("db"), "files_bytes": disk.get("files")},
            "recent_commits": commits(addons_dir),
            "submodules": submodules(addons_dir),
            "backups": [
                {
                    "file": b["file"],
                    "kind": b["kind"],
                    "database": b["db"],
                    "size_bytes": b["size"],
                    "created_at": iso(b["created"]),
                }
                for b in backups.of_instance(name)
            ],
            "restorable_backup": (latest or {}).get("file"),
            "recent_jobs": [
                job_reference(job)
                for job in reversed(jobs.JOBS.values())
                if job.instance == name
            ][:15],  # fmt: skip
        }
    return resource
