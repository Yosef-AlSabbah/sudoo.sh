"""Talking to the hub: this installation's identity, and signed HTTP requests.

Identity
    On first use the panel makes an installation id (a UUID) and an Ed25519 key pair. The private key is kept in
    the panel's storage, encrypted with the vault key (core/vault.py); the public key is registered with the hub.
    Every request that must say which panel sends it is signed with that key (crypto.signed_headers).

Pinned hub keys
    The hub's public keys (GET /api/v1/keys) are fetched once, when the panel first registers with a hub, and kept
    ("pinned") with the identity. Leases and plugin packages are verified only with pinned keys; a hub that later
    answers with another key is not trusted until an administrator pins again (`sudoo.sh marketplace repin`).

Every failure to reach the hub (no network, timeout, a 5xx answer, an answer that is not JSON) raises
HubUnavailable, so callers can say "the marketplace cannot be reached" and carry on. A refusal (4xx) raises
HubRefused with the hub's message and code.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sudoo.config import PACKAGE_DIR, settings
from sudoo.core import vault
from sudoo.storage import storage

from . import crypto

COLLECTION = "marketplace"
TIMEOUT_SECONDS = 15
MAX_JSON_BYTES = 4 * 1024 * 1024
_LOCK = threading.RLock()


class HubUnavailable(Exception):
    """The hub cannot be reached right now."""


class HubRefused(Exception):
    """The hub answered with a refusal (4xx): `status`, `code` (when the hub gives one) and `detail`."""

    def __init__(self, status: int, detail: str, code: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


def hub_url() -> str:
    return settings.hub_url.rstrip("/")


# ---------------------------------------------------------------- identity


@dataclass(frozen=True)
class Identity:
    installation_id: str
    key: Ed25519PrivateKey
    public_key: str
    hub_url: str | None  # the hub the keys below are pinned for
    hub_keys: dict[str, str]  # key id -> base64url public key
    registered_at: float | None

    def pinned(self) -> dict[str, Ed25519PublicKey]:
        """The pinned hub keys, when they belong to the hub the panel uses now."""
        if self.hub_url != hub_url():
            return {}
        return {kid: crypto.public_key_from_b64url(raw) for kid, raw in self.hub_keys.items()}


def _label(installation_id: str) -> str:
    return f"hub-identity:{installation_id}"


def identity() -> Identity:
    """This installation's identity, made (and stored) the first time it is needed."""
    with _LOCK:
        doc = storage().get(COLLECTION, "identity")
        if doc is None:
            installation_id = str(uuid.uuid4())
            key = Ed25519PrivateKey.generate()
            doc = {
                "installation_id": installation_id,
                "public_key": crypto.public_key_b64url(key.public_key()),
                "private_key": vault.encrypt(crypto.private_key_bytes(key), _label(installation_id)),
                "created_at": time.time(),
                "hub_url": None,
                "hub_keys": {},
                "registered_at": None,
            }
            storage().put(COLLECTION, "identity", doc)
        raw = vault.decrypt_bytes(doc["private_key"], _label(doc["installation_id"]))
        return Identity(
            installation_id=doc["installation_id"],
            key=Ed25519PrivateKey.from_private_bytes(raw),
            public_key=doc["public_key"],
            hub_url=doc.get("hub_url"),
            hub_keys=dict(doc.get("hub_keys") or {}),
            registered_at=doc.get("registered_at"),
        )


def update_identity(**values: Any) -> None:
    def change(doc: dict[str, Any] | None) -> dict[str, Any]:
        if doc is None:
            raise RuntimeError("no identity yet")
        return {**doc, **values}

    with _LOCK:
        storage().change(COLLECTION, "identity", change)


def hardware_fingerprint(installation_id: str) -> str:
    """A hash that stays the same on one server (machine id when readable), never the machine id itself."""
    source = ""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            source = Path(path).read_text().strip()
            break
        except OSError:
            continue
    source = source or f"{platform.node()}:{installation_id}"
    return hashlib.sha256(f"sudoo-hardware:{source}".encode()).hexdigest()


def core_hash() -> str:
    """SHA-256 over the panel's own Python files (relative path and content of each, in path order): what the hub
    compares with the hash of the released version."""
    digest = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(PACKAGE_DIR).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def sudoo_version() -> str:
    return version("sudoo")


# ---------------------------------------------------------------- HTTP


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect is handled by the caller, who decides what to send where


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass(frozen=True)
class Answer:
    status: int
    headers: Mapping[str, str]
    data: Any


def _problem(status: int, body: bytes) -> HubRefused:
    try:
        problem = json.loads(body)
    except ValueError:
        problem = {}
    if not isinstance(problem, dict):
        problem = {}
    detail = str(problem.get("detail") or problem.get("title") or f"The marketplace refused the request ({status}).")
    code = problem.get("code")
    return HubRefused(status, detail[:500], str(code) if code else None)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    try:
        return _OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        return error  # an HTTPError is also the response (status, headers, body)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise HubUnavailable(f"The marketplace ({urlsplit(hub_url()).netloc}) cannot be reached.") from error


def request(
    method: str, path: str, body: Any = None, *, signed: bool = True, timeout: float = TIMEOUT_SECONDS
) -> Answer:
    """Call the hub (`path` starts with /api/v1); JSON in and out. Raises HubUnavailable or HubRefused."""
    data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
    headers = {"Accept": "application/json", "User-Agent": f"sudoo/{sudoo_version()}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if signed:
        me = identity()
        headers |= crypto.signed_headers(me.key, me.installation_id, method, path, data, int(time.time()))
    req = urllib.request.Request(hub_url() + path, data=data if body is not None else None, method=method)
    for name, value in headers.items():
        req.add_header(name, value)
    with _open(req, timeout) as response:
        status = response.status
        raw = response.read(MAX_JSON_BYTES + 1)
        answer_headers = {k.lower(): v for k, v in response.headers.items()}
    if status >= 500 or len(raw) > MAX_JSON_BYTES:
        raise HubUnavailable("The marketplace is not answering properly right now. Try again later.")
    if status >= 400:
        raise _problem(status, raw)
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError as error:
        raise HubUnavailable("The marketplace sent an answer the panel does not understand.") from error
    payload = parsed.get("data") if isinstance(parsed, dict) and "data" in parsed else parsed
    if isinstance(parsed, dict) and "meta" in parsed:
        answer_headers = {**answer_headers, "x-sudoo-meta": json.dumps(parsed["meta"])}
    return Answer(status, answer_headers, payload)


def get(path: str, *, signed: bool = False) -> Any:
    return request("GET", path, signed=signed).data


def download(path: str, target: Path, max_bytes: int, timeout: float = 120) -> dict[str, str]:
    """A signed GET of a package into `target` (created mode 600). Follows one redirect to a short-lived storage
    link (https only, without the signature headers); returns the hub's headers (lower-case names)."""
    me = identity()
    headers = crypto.signed_headers(me.key, me.installation_id, "GET", path, b"", int(time.time()))
    req = urllib.request.Request(hub_url() + path, method="GET")
    for name, value in {**headers, "User-Agent": f"sudoo/{sudoo_version()}"}.items():
        req.add_header(name, value)
    response = _open(req, timeout)
    status = response.status
    hub_headers = {k.lower(): v for k, v in response.headers.items()}
    if status in (301, 302, 303, 307, 308):
        location = hub_headers.get("location", "")
        response.close()
        if urlsplit(location).scheme != "https" and urlsplit(hub_url()).scheme == "https":
            raise HubUnavailable("The marketplace sent the package from an address that is not https.")
        response = _open(urllib.request.Request(location, method="GET"), timeout)
        status = response.status
    with response:
        if status >= 500:
            raise HubUnavailable("The marketplace is not answering properly right now. Try again later.")
        if status >= 400:
            raise _problem(status, response.read(MAX_JSON_BYTES))
        written = 0
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as fd:
            while chunk := response.read(256 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HubRefused(413, "The package is larger than the panel accepts.")
                fd.write(chunk)
    return hub_headers
