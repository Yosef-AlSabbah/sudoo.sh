"""Plugins from the marketplace: install, update, disable, enable, uninstall, and keep them honest.

Install (a job, docs/MARKETPLACE.md)
    1. The package is downloaded from the hub with a signed request into a private folder.
    2. Its SHA-256 must be the one the hub states, and the hub's Ed25519 signature over
       "sudoo-plugin-v1\\n<id>\\n<version>\\n<sha256>" must verify with a pinned hub key.
    3. Its manifest.json must name the same plugin and version, suit this panel (min/max Sudoo version, SDK
       version), and every plugin it `requires` must be installed and enabled in a matching version.
    4. Packages that need third-party Python packages are refused in this version (no dependency installer), as
       are compiled files (native extensions, .pyc), links, absolute paths and archive bombs.
    5. It is unpacked into <ODOO_ROOT>/manager/plugins/<id>/<version>/ (folders 700, files 600, readable by root
       only; the web container does not mount that folder), the package file is deleted, the entry points are
       written as a small dist-info so `plugins.load` finds them, and a hash of every unpacked file is recorded.
    6. The backend restarts (once no job runs) and loads the plugin.

Integrity
    At start, and every few minutes, the files of each installed plugin are hashed again. A plugin whose files
    changed is not loaded, is marked "modified" and the super admins are told. No API returns a plugin's files.

Licences of paid plugins
    The signed lease of the last heartbeat gives each paid plugin's licence dates; they are copied into the
    plugin's record. A paid plugin runs while the lease is valid and its licence has not passed its grace date.
    When the grace ends, the panel backs up its own data and the instances the plugin may change, then switches
    the plugin off (its data and settings are kept) and e-mails the super admins. A renewal switches it on again.

Records are kept in the panel's storage, collection "plugins", one document per plugin id.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import stat
import sys
import threading
import time
import tomllib
import zipfile
from collections.abc import Callable, Iterable
from importlib.metadata import entry_points
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from sudoo.config import settings
from sudoo.core import audit, events, jobs
from sudoo.core.jobs import Job, JobError
from sudoo.hub import HubRefused, HubUnavailable, client, crypto, marketplace
from sudoo.storage import storage

log = logging.getLogger("sudoo.plugins")

COLLECTION = "plugins"
JOB_INSTANCE = "panel:plugins"  # the job "instance" of plugin work: one plugin job at a time, never a real name
SDK_VERSION = "0.1.0"  # the plugin SDK contract this panel implements (manifest "sdk_version")
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000
MAX_RATIO = 100
EXPIRY_NOTICE_DAYS = 7
WATCH_SECONDS = 600
REFUSED_SUFFIXES = (".so", ".pyd", ".dll", ".dylib", ".exe", ".pyc", ".pyo")
RESERVED_GROUPS = ("sudoo.storage",)  # installed plugins are recorded in storage: it must be built in
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*){2,6}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$"
)
_CLAUSE_RE = re.compile(r"^\s*(>=|<=|==|!=|~=|>|<)\s*(\S+)\s*$")

_LOCK = threading.RLock()
LOADED: set[str] | None = None  # ids of the plugins this process put on sys.path (None: not activated yet)
_RESTART_PENDING = threading.Event()
_WATCH_WAKE = threading.Event()


class PluginRefused(Exception):
    """The plugin cannot be installed or changed; the message says why, for the person who asked."""


def plugins_dir() -> Path:
    return settings.manager_dir / "plugins"


# ---------------------------------------------------------------- versions


def semver_key(version: str) -> tuple[Any, ...]:
    match = SEMVER_RE.match(version)
    if match is None:
        raise ValueError(f"{version!r} is not a version such as 1.2.0")
    major, minor, patch, pre = int(match[1]), int(match[2]), int(match[3]), match[4]
    if pre is None:
        return (major, minor, patch, 1, ())
    return (major, minor, patch, 0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")))


def satisfies(version: str, specifier: str | None) -> bool:
    """Whether `version` meets ">=1.0.0,<2.0.0" (None or empty: any). "~=1.4.2" means ">=1.4.2,<1.5.0"."""
    if not specifier or not specifier.strip():
        return True
    have = semver_key(version)
    for clause in specifier.split(","):
        match = _CLAUSE_RE.match(clause)
        if match is None:
            raise ValueError(f"{specifier!r} is not a version specifier")
        op, other = match[1], match[2]
        want = semver_key(other)
        if op == "~=":
            upper = (want[0], want[1] + 1, 0, 0, ())
            ok = want <= have < upper
        else:
            ok = {
                ">=": have >= want,
                "<=": have <= want,
                ">": have > want,
                "<": have < want,
                "==": have == want,
                "!=": have != want,
            }[op]
        if not ok:
            return False
    return True


# ---------------------------------------------------------------- records


def records() -> dict[str, dict[str, Any]]:
    return storage().all(COLLECTION)


def record(plugin_id: str) -> dict[str, Any] | None:
    return storage().get(COLLECTION, plugin_id)


def _update(plugin_id: str, **values: Any) -> dict[str, Any] | None:
    def change(doc: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if doc is None else {**doc, **values}

    return storage().change(COLLECTION, plugin_id, change)


def folder(rec: dict[str, Any]) -> Path:
    return plugins_dir() / rec["id"] / rec["version"]


def tree_hash(root: Path) -> str:
    """SHA-256 over every file under `root` (relative path and content), ignoring __pycache__.
    Links make the hash differ from any recorded one."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts:
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            digest.update(b"link:" + relative.as_posix().encode() + b"\0")
        elif stat.S_ISREG(info.st_mode):
            digest.update(relative.as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _paid(rec: dict[str, Any]) -> bool:
    return rec.get("tier") == "paid"


def licence_end(rec: dict[str, Any]) -> float | None:
    """When a paid plugin stops: the licence's grace date, or its expiry when it has no grace."""
    licence = rec.get("licence") or {}
    end = licence.get("grace_until") or licence.get("expires_at")
    return float(end) if end else None


def allowed(rec: dict[str, Any], now: float | None = None, lease_valid: bool | None = None) -> tuple[bool, str]:
    """Whether the plugin should run now, and why not: disabled, modified, blocked, no_lease, unlicensed or
    licence_ended."""
    if rec.get("tampered"):
        return False, "modified"
    if not rec.get("enabled", True):
        return False, "disabled"
    if marketplace.blocked():
        return False, "blocked"
    if not _paid(rec):
        return True, "ok"
    now = marketplace.trusted_now() if now is None else now
    if lease_valid is None:
        lease_valid = marketplace.lease() is not None
    if not lease_valid:
        return False, "no_lease"
    if rec.get("standing") not in ("licensed", "grace"):
        return False, "unlicensed" if rec.get("standing") in (None, "unlicensed", "unknown") else "licence_ended"
    end = licence_end(rec)
    if end is not None and now >= end:
        return False, "licence_ended"
    return True, "ok"


def allowed_ids() -> set[str]:
    now, lease_valid = marketplace.trusted_now(), marketplace.lease() is not None
    return {pid for pid, rec in records().items() if allowed(rec, now, lease_valid)[0]}


# ---------------------------------------------------------------- loading


def _paths(rec: dict[str, Any]) -> list[Path]:
    base = folder(rec)
    package = base / "package"
    found = [base / "meta", package]
    if (package / "src").is_dir():
        found.append(package / "src")
    return found


def _wipe_bytecode(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def activate() -> set[str]:
    """Once per process, before plugins are loaded: check every installed plugin's files and put the ones that
    may run on sys.path, where `plugins.load` finds their entry points. Returns the ids put on the path."""
    global LOADED
    with _LOCK:
        if LOADED is not None:
            return LOADED
        LOADED = set()
        try:
            installed = records()
        except Exception:  # noqa: BLE001 - a panel without readable storage still starts, without plugins
            log.exception("plugins: cannot read the installed plugins")
            return LOADED
        for plugin_id, rec in installed.items():
            if not verify_files(rec):
                continue
            if not allowed(rec)[0]:
                continue
            _wipe_bytecode(folder(rec))
            for path in _paths(rec):
                if str(path) not in sys.path:
                    sys.path.append(str(path))  # last: a plugin never shadows the panel or its libraries
            LOADED.add(plugin_id)
        importlib.invalidate_caches()
        return LOADED


def verify_files(rec: dict[str, Any]) -> bool:
    """Whether the plugin's files are those installed; a changed plugin is marked and reported (once)."""
    if rec.get("tampered"):
        return False
    base = folder(rec)
    actual = tree_hash(base) if base.is_dir() else "missing"
    if actual == rec.get("tree_hash"):
        return True
    _update(rec["id"], tampered=True, tampered_at=time.time())
    audit.record("system", None, "plugin files modified; plugin not loaded", ok=False, detail=rec["id"])
    _mail_super_admins(
        f"{rec.get('name', rec['id'])} was switched off: its files were changed",
        "A plugin's files were changed",
        f"The files of the plugin {rec.get('name', rec['id'])} ({rec['id']} {rec['version']}) are not the ones that "
        "were installed, so the panel no longer loads it. Install it again from the Plugins page to repair it.",
    )
    events.publish("plugins", rec["id"], {"changed": True})
    return False


# ---------------------------------------------------------------- restarting the backend


def stop_backend() -> None:
    """Stop gunicorn's main process; Docker starts the backend again (restart: unless-stopped)."""
    os.kill(os.getppid(), signal.SIGTERM)


def schedule_restart(reason: str) -> bool:
    """Restart the backend as soon as no job runs (so the plugin changes take effect). False when one is already
    waiting."""
    with _LOCK:
        if _RESTART_PENDING.is_set():
            return False
        _RESTART_PENDING.set()

    def wait_and_stop() -> None:
        time.sleep(2)
        while jobs.ACTIVE_JOB:
            time.sleep(2)
        audit.record("system", None, "panel restarted", detail=reason)
        stop_backend()

    threading.Thread(target=wait_and_stop, daemon=True, name="plugin-restart").start()
    return True


def restart_pending() -> bool:
    return _RESTART_PENDING.is_set()


# ---------------------------------------------------------------- package checks


def _safe_name(name: str) -> bool:
    """A relative path inside the package: no leading /, no "..", no backslashes, drive letters or control
    characters."""
    stripped = name[:-1] if name.endswith("/") else name
    parts = stripped.split("/")
    return (
        bool(stripped)
        and len(name) <= 300
        and not name.startswith("/")
        and "\\" not in name
        and ":" not in parts[0]
        and not any(part in ("", ".", "..") for part in parts)
        and not any(ord(c) < 32 for c in name)
    )


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """The archive's entries, after checking paths, links, compiled files and sizes (no archive bombs)."""
    infos = archive.infolist()
    if len(infos) > MAX_FILES:
        raise PluginRefused(f"The package has more than {MAX_FILES} files.")
    total = 0
    for info in infos:
        name = info.filename
        if not _safe_name(name):
            raise PluginRefused(f"The package contains a file outside its folder ({name[:80]!r}).")
        kind = stat.S_IFMT(info.external_attr >> 16)  # 0 when the archive does not say (plain files)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise PluginRefused(f"The package contains a link or a special file ({name[:80]!r}).")
        if info.flag_bits & 0x1:
            raise PluginRefused("The package is encrypted.")
        if name.lower().endswith(REFUSED_SUFFIXES):
            raise PluginRefused(f"The package contains compiled code ({name[:80]!r}); only Python source is accepted.")
        total += info.file_size
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 1024 * 1024:
            raise PluginRefused("The package is compressed suspiciously well (an archive bomb?).")
    if total > MAX_UNPACKED_BYTES:
        raise PluginRefused("The package is too large once unpacked.")
    return infos


def _manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except KeyError:
        raise PluginRefused("The package has no manifest.json.") from None
    except ValueError:
        raise PluginRefused("The package's manifest.json is not valid JSON.") from None
    if not isinstance(manifest, dict):
        raise PluginRefused("The package's manifest.json is not an object.")
    return manifest


def _requirements(manifest: dict[str, Any]) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    for item in manifest.get("requires") or []:
        if isinstance(item, str):
            found.append((item, None))
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            found.append((item["id"], item.get("version")))
    return found


def _has_dependencies(archive: zipfile.ZipFile) -> bool:
    names = set(archive.namelist())
    if "pyproject.toml" in names:
        try:
            project = tomllib.loads(archive.read("pyproject.toml").decode()).get("project", {})
        except (ValueError, UnicodeDecodeError):
            raise PluginRefused("The package's pyproject.toml cannot be read.") from None
        if project.get("dependencies") or project.get("optional-dependencies"):
            return True
    for name in names:
        if "/" not in name and name.startswith("requirements") and name.endswith(".txt"):
            lines = archive.read(name).decode(errors="replace").splitlines()
            if any(line.strip() and not line.strip().startswith("#") for line in lines):
                return True
    return False


def check_package(archive: zipfile.ZipFile, plugin_id: str, version: str) -> dict[str, Any]:
    """The manifest of a package that this panel can install as `plugin_id` `version`; PluginRefused otherwise."""
    from sudoo.hub.client import sudoo_version

    infos = _members(archive)
    manifest = _manifest(archive)
    if manifest.get("id") != plugin_id or manifest.get("version") != version:
        raise PluginRefused("The package's manifest names another plugin or version than the one downloaded.")
    panel = sudoo_version()
    try:
        if semver_key(panel) < semver_key(str(manifest.get("min_sudoo_version", "0.0.0"))):
            raise PluginRefused(
                f"This plugin needs Sudoo.sh {manifest['min_sudoo_version']} or newer (this is {panel})."
            )
        newest = manifest.get("max_sudoo_version")
        if newest and semver_key(panel) > semver_key(str(newest)):
            raise PluginRefused(f"This plugin works up to Sudoo.sh {newest} (this is {panel}).")
        if not satisfies(SDK_VERSION, str(manifest.get("sdk_version") or "")):
            raise PluginRefused(
                f"This plugin needs plugin SDK {manifest['sdk_version']}; this panel offers {SDK_VERSION}."
            )
    except ValueError as error:
        raise PluginRefused(f"The manifest has a version this panel cannot read: {error}.") from None
    for required, specifier in _requirements(manifest):
        other = record(required)
        if other is None or not other.get("enabled", True) or other.get("tampered"):
            raise PluginRefused(f"Install and enable {required} first: this plugin needs it.")
        try:
            ok = satisfies(other["version"], specifier)
        except ValueError:
            ok = False
        if not ok:
            raise PluginRefused(f"This plugin needs {required} {specifier}; {other['version']} is installed.")
    if _has_dependencies(archive):
        raise PluginRefused(
            "This plugin needs other Python packages. Plugins with dependencies are not supported yet; ask its "
            "publisher for a version without them."
        )
    groups = manifest.get("entry_points")
    if not isinstance(groups, dict) or not groups:
        raise PluginRefused("The manifest declares no entry points.")
    for group, entries in groups.items():
        if not isinstance(group, str) or not group.startswith("sudoo.") or not isinstance(entries, dict):
            raise PluginRefused(f"The entry point group {str(group)[:60]!r} is not a Sudoo.sh group.")
        if group in RESERVED_GROUPS:
            raise PluginRefused(f"Plugins for {group} cannot be installed from the marketplace.")
        taken = {
            e.name for e in entry_points(group=group) if not _belongs_to(e, plugin_id)
        }  # names of other plugins of the group
        for name, target in entries.items():
            if not isinstance(target, str) or ":" not in target:
                raise PluginRefused(f"The entry point {str(name)[:40]!r} is not module:Object.")
            if name in taken:
                raise PluginRefused(f"Another plugin already provides {name!r} in {group}.")
    for top in _top_level_modules(infos):
        if top == "sudoo" or (top not in _own_modules(plugin_id) and find_spec(top) is not None):
            raise PluginRefused(f"The package's module {top!r} would clash with one the panel already has.")
    return manifest


def _belongs_to(entry: Any, plugin_id: str) -> bool:
    dist = getattr(entry, "dist", None)
    name = getattr(getattr(dist, "metadata", None), "get", lambda _k, _d=None: None)("Name", None)
    return name == _dist_name(plugin_id)


def _own_modules(plugin_id: str) -> set[str]:
    rec = record(plugin_id)
    return set(rec.get("modules") or []) if rec else set()


def _top_level_modules(infos: Iterable[zipfile.ZipInfo]) -> set[str]:
    found = set()
    for info in infos:
        parts = info.filename.split("/")
        if parts[0] == "src" and len(parts) > 2:
            parts = parts[1:]
        if len(parts) > 1 and parts[1] == "__init__.py":
            found.add(parts[0])
        elif len(parts) == 1 and parts[0].endswith(".py"):
            found.add(parts[0][:-3])
    return {name for name in found if name.isidentifier()}


def _dist_name(plugin_id: str) -> str:
    return "sudoo-plugin-" + plugin_id.replace(".", "-")


def _write_meta(meta: Path, manifest: dict[str, Any]) -> None:
    """A dist-info folder, so importlib.metadata (and so plugins.load) finds the plugin's entry points."""
    name = _dist_name(manifest["id"])
    info = meta / f"{name.replace('-', '_')}-{manifest['version']}.dist-info"
    info.mkdir(parents=True, mode=0o700)
    lines = []
    for group, entries in manifest["entry_points"].items():
        lines.append(f"[{group}]")
        lines.extend(f"{key} = {value}" for key, value in entries.items())
        lines.append("")
    (info / "entry_points.txt").write_text("\n".join(lines))
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {manifest['version']}\n")


def _lock_down(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o600)


def _extract(archive: zipfile.ZipFile, target: Path) -> None:
    for info in archive.infolist():
        destination = (target / info.filename).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise PluginRefused("The package contains a file outside its folder.")
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with archive.open(info) as source, destination.open("wb") as out:
            shutil.copyfileobj(source, out, 256 * 1024)


# ---------------------------------------------------------------- install, update, uninstall (jobs)


def _hub_message(error: HubRefused) -> str:
    """The hub's refusal in the person's words (codes from the hub's panel contract)."""
    return {
        "link_required": "Link this panel to your Sudoo.sh account first (Settings, Marketplace).",
        "license_required": "This panel has no licence for this plugin yet. Buy it first.",
        "lease_expired": "The marketplace has not heard from this panel recently. Try again in a minute.",
        "integrity_violation": "The marketplace refuses this panel: its core files differ from the released ones.",
        "installation_suspended": "This panel is suspended on the marketplace. Contact Sudoo.sh support.",
        "incompatible": "No version of this plugin runs on this panel's version of Sudoo.sh yet.",
        "purchases_not_allowed": "The account owner has not allowed purchases from this server (app.sudoo.sh, Servers).",
        "spending_limit": f"This server's monthly spending limit is reached. {error.detail}",
        "already_licensed": "This server already has a licence for this plugin: install it.",
        "not_for_sale": "This plugin is free: install it.",
        "developer_not_payable": "This plugin cannot be bought right now (its publisher cannot receive payments).",
        "purchase_in_progress": "A purchase of this plugin with another plan is under way. Finish or cancel it first.",
        "payments_disabled": "Payments are switched off on the marketplace right now. Try again later.",
    }.get(error.code or "", error.detail)


def install(job: Job, plugin_id: str, version: str | None, user: str) -> None:
    """Ask the hub for the package, download, verify, check and unpack it, then restart the backend (a job)."""
    job.expect(6)
    job.step("Asking the marketplace about the plugin")
    try:
        info = marketplace.install_info(plugin_id, version)
        version = str(info.get("version") or "")
        path = str(info.get("download_path") or "")
        if info.get("plugin_id", plugin_id) != plugin_id or not SEMVER_RE.match(version):
            raise PluginRefused("The marketplace answered about another plugin, or without a version.")
        if not path.startswith("/api/v1/") or "://" in path or ".." in path:
            raise PluginRefused("The marketplace gave a download address the panel does not accept.")
        try:
            detail = marketplace.plugin(plugin_id)  # name, publisher (the public page)
        except (HubRefused, HubUnavailable):
            detail = {}
        downloads = plugins_dir() / ".downloads"
        downloads.mkdir(parents=True, exist_ok=True, mode=0o700)
        package = downloads / f"{plugin_id}-{version}.sudoo"
        try:
            job.step(f"Downloading {plugin_id} {version}")
            headers = client.download(path, package, MAX_PACKAGE_BYTES)
            job.write(f"Downloaded {package.stat().st_size} bytes\n")
            job.step("Checking the signature")
            _verify_download(job, package, plugin_id, version, info, headers)
            job.step("Checking that it suits this panel")
            with zipfile.ZipFile(package) as archive:
                manifest = check_package(archive, plugin_id, version)
                job.step("Installing")
                _unpack(job, archive, manifest, {**detail, "tier": info.get("tier") or detail.get("tier")}, user)
        finally:
            package.unlink(missing_ok=True)  # the package itself is never kept
    except PluginRefused as error:
        raise JobError(str(error)) from None
    except HubRefused as error:
        raise JobError(_hub_message(error)) from None
    except HubUnavailable as error:
        raise JobError(f"{error} Try again when the server can reach the marketplace.") from None
    except zipfile.BadZipFile:
        raise JobError("The package is not a valid archive.") from None
    if (record(plugin_id) or {}).get("tier") == "paid":
        try:  # the lease now covers the new plugin: its licence dates are known before the restart
            marketplace.heartbeat()
        except (HubRefused, HubUnavailable) as error:
            job.note(f"The licence could not be confirmed yet ({error}); the panel retries on its own.", "warning")
    job.step("Restarting the panel to load it")
    job.note("The panel restarts in a few seconds; instances keep running.")
    marketplace.wake()
    schedule_restart(f"plugin {plugin_id} {version} installed")


def _verify_download(
    job: Job, package: Path, plugin_id: str, version: str, info: dict[str, Any], headers: dict[str, str]
) -> None:
    """The package must have the SHA-256 the hub stated and carry the hub's signature for this plugin and version,
    made with a pinned key. The install answer is authoritative; the download's headers, when present, must agree."""
    if (
        headers.get("x-sudoo-plugin-id", plugin_id) != plugin_id
        or headers.get("x-sudoo-plugin-version", version) != version
    ):
        raise PluginRefused("The marketplace sent another plugin or version than the one asked for.")
    stated = str(info.get("package_sha256") or headers.get("x-sudoo-package-sha256") or "").lower()
    signature = str(info.get("signature") or headers.get("x-sudoo-signature") or "")
    key_id = str(info.get("signing_key_id") or headers.get("x-sudoo-signing-key") or "")
    for header, value in (("x-sudoo-package-sha256", stated), ("x-sudoo-signature", signature)):
        if headers.get(header) and headers[header].lower() != value.lower():
            raise PluginRefused("The download does not match what the marketplace stated; not installed.")
    with package.open("rb") as fh:
        actual = hashlib.file_digest(fh, "sha256").hexdigest()
    if not stated or actual != stated:
        raise PluginRefused("The package's SHA-256 does not match the one the marketplace states; not installed.")
    key = client.identity().pinned().get(key_id)
    if key is None:
        raise PluginRefused("The package is signed with a key this panel does not trust; not installed.")
    if not crypto.verify_package(key, plugin_id, version, actual, signature):
        raise PluginRefused("The package's signature is not valid (it was changed or is not from the marketplace).")
    job.write(f"SHA-256 {actual}\nSignature verified with hub key {key_id}\n")


def _unpack(job: Job, archive: zipfile.ZipFile, manifest: dict[str, Any], detail: dict[str, Any], user: str) -> None:
    plugin_id, version = manifest["id"], manifest["version"]
    base = plugins_dir() / plugin_id
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    plugins_dir().chmod(0o700)
    partial = base / f".{version}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    (partial / "package").mkdir(parents=True, mode=0o700)
    _extract(archive, partial / "package")
    _write_meta(partial / "meta", manifest)
    _lock_down(partial)
    final = base / version
    previous = record(plugin_id)
    shutil.rmtree(final, ignore_errors=True)
    partial.rename(final)
    now = time.time()
    rec = {
        "id": plugin_id,
        "name": str(manifest.get("name") or detail.get("name") or plugin_id),
        "version": version,
        "type": manifest.get("type") or detail.get("type"),
        "tier": detail.get("tier") or manifest.get("tier") or "free",
        "description": str(manifest.get("description") or detail.get("description") or ""),
        "publisher": detail.get("publisher"),
        "permissions": list(manifest.get("permissions") or []),
        "requires": [{"id": i, "version": v} for i, v in _requirements(manifest)],
        "entry_points": manifest["entry_points"],
        "modules": sorted(_top_level_modules(archive.infolist())),
        "enabled": previous.get("enabled", True) if previous else True,
        "tampered": False,
        "standing": (previous or {}).get("standing"),
        "licence": (previous or {}).get("licence"),
        "switched_off": (previous or {}).get("switched_off"),
        "notified": (previous or {}).get("notified") or {},
        "tree_hash": tree_hash(final),
        "installed_at": (previous or {}).get("installed_at") or now,
        "installed_by": (previous or {}).get("installed_by") or user,
        "updated_at": now,
    }
    storage().put(COLLECTION, plugin_id, rec)
    if previous and previous.get("version") != version:
        shutil.rmtree(base / previous["version"], ignore_errors=True)
        job.write(f"Removed version {previous['version']}\n")
    audit.record(user, None, "plugin installed" if not previous else "plugin updated", detail=f"{plugin_id} {version}")
    events.publish("plugins", plugin_id, {"changed": True})


def uninstall(job: Job, plugin_id: str, user: str) -> None:
    """Back up the panel's data, then remove the plugin's files and record, and restart."""
    rec = record(plugin_id)
    if rec is None:
        raise JobError("This plugin is not installed.")
    job.expect(3)
    job.step("Backing up the panel's data")
    saved = panel_backup(f"before-uninstall-{plugin_id}")
    job.note(f"Panel data saved: {saved.name}")
    job.step("Removing the plugin")
    shutil.rmtree(plugins_dir() / plugin_id, ignore_errors=True)
    storage().delete(COLLECTION, plugin_id)
    audit.record(user, None, "plugin uninstalled", detail=f"{plugin_id} {rec['version']}")
    events.publish("plugins", plugin_id, {"changed": True})
    job.step("Restarting the panel")
    marketplace.wake()
    schedule_restart(f"plugin {plugin_id} uninstalled")


def dependents(plugin_id: str) -> list[str]:
    return sorted(pid for pid, rec in records().items() if any(r["id"] == plugin_id for r in rec.get("requires", [])))


def set_enabled(plugin_id: str, value: bool, user: str) -> dict[str, Any]:
    rec = record(plugin_id)
    if rec is None:
        raise PluginRefused("This plugin is not installed.")
    if not value and (needed_by := [p for p in dependents(plugin_id) if (record(p) or {}).get("enabled", True)]):
        raise PluginRefused(f"Disable {', '.join(needed_by)} first: it needs this plugin.")
    if value and rec.get("tampered"):
        raise PluginRefused("Its files were changed. Install it again to repair it.")
    updated = _update(plugin_id, enabled=value) or rec
    audit.record(user, None, "plugin enabled" if value else "plugin disabled", detail=plugin_id)
    events.publish("plugins", plugin_id, {"changed": True})
    apply_changes(f"plugin {plugin_id} {'enabled' if value else 'disabled'}")
    return updated


def apply_changes(reason: str) -> bool:
    """Restart (once no job runs) when the plugins that should run differ from those loaded."""
    loaded = activate()
    if allowed_ids() != loaded:
        return schedule_restart(reason)
    return False


# ---------------------------------------------------------------- panel data backup


def panel_backups_dir() -> Path:
    return settings.backups_dir / "panel"


def panel_backup(reason: str) -> Path:
    """A zip of the panel's own data (the SQLite database, consistent, and settings.json) in
    <ODOO_ROOT>/backups/panel/, mode 600. The vault key is not included: keep it safe separately."""
    target_dir = panel_backups_dir()
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe = re.sub(r"[^a-z0-9.-]+", "-", reason.lower())[:80]
    target = target_dir / f"panel__{time.strftime('%Y%m%d-%H%M%S')}__{safe}.zip"
    tmp_db = target_dir / f".{target.stem}.db"
    try:
        database = getattr(storage(), "path", None)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
            if isinstance(database, Path) and database.exists():
                with sqlite3.connect(database) as source, sqlite3.connect(tmp_db) as copy:
                    source.backup(copy)
                archive.write(tmp_db, "sudoo.db")
            else:  # another storage plugin: every document of the collections the panel knows
                archive.writestr("documents.json", json.dumps(_known_documents()))
            settings_file = settings.manager_dir / "settings.json"
            if settings_file.exists():
                archive.write(settings_file, "settings.json")
    finally:
        tmp_db.unlink(missing_ok=True)
    return target


def _known_documents() -> dict[str, Any]:
    names = ("users", "api_tokens", "instance_state", "creations", COLLECTION, "marketplace")
    return {name: storage().all(name) for name in names}


# ---------------------------------------------------------------- licences


def apply_lease(lease: crypto.Lease) -> None:
    """Copy the signed standing and licence dates of each installed plugin into its record."""
    standing, licences = lease.plugins, lease.licences
    for plugin_id in records():
        if plugin_id in standing:
            _update(plugin_id, standing=standing[plugin_id], licence=licences.get(plugin_id))
    _WATCH_WAKE.set()


def touches_instances(rec: dict[str, Any]) -> bool:
    """Whether the plugin may change instances (manifest permission instances.write or docker)."""
    return bool({"instances.write", "docker"} & set(rec.get("permissions") or []))


def _licence_ended(job: Job, plugin_id: str) -> None:
    """At the end of a paid plugin's grace: back up, switch it off (keeping data), tell the super admins."""
    from sudoo.instances import operations, store

    rec = record(plugin_id) or {}
    name = rec.get("name", plugin_id)
    job.expect(3)
    problems: list[str] = []
    job.step("Backing up the panel's data")
    try:
        saved = panel_backup(f"before-{plugin_id}-stops")
        job.note(f"Panel data saved: {saved.name}")
    except Exception as error:  # noqa: BLE001 - the licence ended: the plugin stops even if the backup fails
        problems.append(f"the panel's data ({error})")
        job.note(f"The panel's data could not be backed up: {error}", "warning")
    if touches_instances(rec):
        job.step("Backing up the instances the plugin can change")
        started = [jobs.start(n, f"Back up before {name} stops", "backup", operations.backup, n) for n in store.names()]
        for backup_job in started:
            while backup_job.finished is None:
                time.sleep(2)
            if backup_job.status != "success":
                problems.append(f"instance {backup_job.instance} (job {backup_job.id})")
    job.step("Switching the plugin off")
    _update(plugin_id, switched_off={"at": time.time(), "reason": "licence", "backup_problems": problems})
    audit.record("system", None, "plugin switched off (licence ended)", detail=plugin_id)
    text = (
        f"The licence of {name} ended and its grace period is over, so the panel switched it off. Its data and "
        "settings are kept: renew it on app.sudoo.sh and the panel switches it back on by itself."
    )
    if problems:
        text += " Some backups taken before switching it off failed: " + "; ".join(problems) + "."
    _mail_super_admins(f"{name} was switched off", f"{name} was switched off", text)
    events.publish("plugins", plugin_id, {"changed": True})
    schedule_restart(f"plugin {plugin_id} switched off (licence ended)")


def watch(start_job: Callable[..., Job] = jobs.start) -> None:
    """One pass of the watchdog: files, licence reminders, switching off at the end of grace, switching back on
    after a renewal, and a restart when what should run differs from what runs."""
    activate()
    marketplace.remember_time()
    now = marketplace.trusted_now()
    lease_valid = marketplace.lease() is not None
    ending = False
    for plugin_id, rec in records().items():
        if plugin_id in (LOADED or set()) and not verify_files(rec):
            continue
        ok, reason = allowed(rec, now, lease_valid)
        if not _paid(rec):
            continue
        licence = rec.get("licence") or {}
        expires = licence.get("expires_at")
        if ok and expires and 0 < float(expires) - now <= EXPIRY_NOTICE_DAYS * 86400:
            _notify_once(rec, f"expiring:{expires}", f"{rec['name']} ends soon",
                         f"The licence of {rec['name']} ends on {_date(expires)}. Renew it on app.sudoo.sh to keep it "
                         "running; if it is not renewed, the panel switches it off at the end of its grace period.")  # fmt: skip
        if ok and rec.get("switched_off"):
            _update(plugin_id, switched_off=None)
            audit.record("system", None, "plugin switched back on (licence renewed)", detail=plugin_id)
            _mail_super_admins(f"{rec['name']} is back on", f"{rec['name']} is back on",
                               f"The licence of {rec['name']} was renewed; the panel switched it back on.")  # fmt: skip
        if (
            reason in ("licence_ended", "no_lease")
            and rec.get("enabled", True)
            and not rec.get("switched_off")
            and not _job_running(plugin_id)
        ):
            ending = True
            start_job(JOB_INSTANCE, f"Switch off {rec['name']} (licence ended)", "plugin-expired",
                      _licence_ended, plugin_id)  # fmt: skip
    if not ending and allowed_ids() != (LOADED or set()):
        schedule_restart("plugins changed (licences or marketplace)")


def _job_running(plugin_id: str) -> bool:
    current = jobs.ACTIVE_JOB.get(JOB_INSTANCE)
    return current is not None and current.kind == "plugin-expired" and plugin_id in current.action


def watch_forever() -> None:
    while True:
        _WATCH_WAKE.wait(WATCH_SECONDS)
        _WATCH_WAKE.clear()
        try:
            watch()
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("plugin watchdog failed")


def _date(timestamp: float | int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(float(timestamp)))


def _notify_once(rec: dict[str, Any], key: str, subject: str, text: str) -> None:
    if key in (rec.get("notified") or {}):
        return
    _update(rec["id"], notified={**(rec.get("notified") or {}), key: time.time()})
    _mail_super_admins(subject, subject, text)


def _mail_super_admins(subject: str, title: str, text: str) -> None:
    """E-mail every super admin with an address, through the panel's mailer; never raises."""
    try:
        from sudoo import accounts
        from sudoo.mail import mailer, send_template

        if not mailer().ready:
            return
        for user in accounts.all_users().values():
            if user.get("role") == "super_admin" and user.get("email"):
                send_template(user["email"], "notice", subject, preheader=text[:90], kicker="Plugins",
                              title=title, text=text)  # fmt: skip
    except Exception:  # noqa: BLE001 - a missing e-mail never stops plugin work
        log.exception("plugins: could not e-mail the super admins")


# ---------------------------------------------------------------- what the API shows


def phase(rec: dict[str, Any], now: float, lease_valid: bool) -> str | None:
    """Licence phase of a paid plugin: active, expiring (7 days before), grace, ended, no_lease, unlicensed."""
    if not _paid(rec):
        return None
    ok, reason = allowed({**rec, "enabled": True, "tampered": False}, now, lease_valid)
    if not ok:
        return {"licence_ended": "ended", "no_lease": "no_lease", "unlicensed": "unlicensed"}.get(reason, reason)
    licence = rec.get("licence") or {}
    expires = licence.get("expires_at")
    if expires and now >= float(expires):
        return "grace"
    if expires and float(expires) - now <= EXPIRY_NOTICE_DAYS * 86400:
        return "expiring"
    return "active"


def status_of(rec: dict[str, Any], now: float, lease_valid: bool) -> str:
    ok, reason = allowed(rec, now, lease_valid)
    if ok:
        return "active"
    return {"licence_ended": "switched_off", "no_lease": "switched_off"}.get(reason, reason)


def notices() -> list[dict[str, Any]]:
    """Banners for the web app: licences ending, in grace, ended; modified plugins; the marketplace refusing."""
    now, lease_valid = marketplace.trusted_now(), marketplace.lease() is not None
    found: list[dict[str, Any]] = []
    if blocked := marketplace.blocked():
        found.append({"plugin": None, "kind": blocked, "level": "danger",
                      "text": "The marketplace refuses this panel, so every plugin is switched off: "
                      + ("its core files differ from the released version." if blocked == "integrity_violation"
                         else "the installation is suspended. Contact Sudoo.sh support.")})  # fmt: skip
    for rec in records().values():
        name = rec.get("name", rec["id"])
        if rec.get("tampered"):
            found.append({"plugin": rec["id"], "kind": "modified", "level": "danger",
                          "text": f"{name} is switched off: its files were changed. Install it again to repair it."})  # fmt: skip
            continue
        if not rec.get("enabled", True):
            continue
        current = phase(rec, now, lease_valid)
        licence = rec.get("licence") or {}
        if current == "expiring":
            found.append({"plugin": rec["id"], "kind": "expiring", "level": "warning", "date": licence["expires_at"],
                          "text": f"The licence of {name} ends on {_date(licence['expires_at'])}. Renew it on app.sudoo.sh."})  # fmt: skip
        elif current == "grace":
            end = licence_end(rec)
            found.append({"plugin": rec["id"], "kind": "grace", "level": "warning", "date": end,
                          "text": f"The licence of {name} has ended. It stops on {_date(end or now)} unless it is renewed."})  # fmt: skip
        elif current == "ended":
            found.append({"plugin": rec["id"], "kind": "ended", "level": "danger",
                          "text": f"{name} is switched off: its licence ended. Renew it and it comes back on by itself; its data is kept."})  # fmt: skip
        elif current == "no_lease":
            found.append({"plugin": rec["id"], "kind": "no_lease", "level": "danger",
                          "text": f"{name} is switched off: the panel has not reached the marketplace for 7 days."})  # fmt: skip
    return found
