"""The panel's side of the marketplace: registration, the signed heartbeat, the lease, linking and purchases.

Heartbeat
    Every 6 hours (sooner when the lease asks for it) the panel sends the hub its version, the hash of its core
    files and the installed plugins, signed with the installation key. The hub answers with a lease (crypto.Lease):
    the standing of each plugin and the licence dates of the paid ones. The lease is verified with the pinned hub
    key and kept in storage, together with the dates, so the panel can act on them while offline.

When the hub cannot be reached
    Nothing stops: instances, free plugins and the panel keep working; the Plugins page says the marketplace cannot
    be reached. Paid plugins keep running until the lease the panel holds expires (7 days after the last heartbeat
    that passed) or their licence's grace period ends, whichever comes first (plugin_manager.py).

Clock
    Licences are compared with `trusted_now()`: the later of the server's clock, the signed issue time of the last
    lease plus the time measured since (monotonic), and the latest time the panel has seen, kept in storage. Turning
    the clock back does not extend a licence.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any
from urllib.parse import urlencode

from sudoo.config import settings
from sudoo.storage import storage

from . import client, crypto
from .client import COLLECTION, HubRefused, HubUnavailable

log = logging.getLogger("sudoo.hub")

HEARTBEAT_HOURS = 6
RETRY_MINUTES = 15
LEASE_WARNING_DAYS = 2
BLOCKING = ("integrity_violation", "installation_suspended")  # hub answers that switch every plugin off
PANEL = "/api/v1/installations"  # the hub's panel contract (sudoo-hub README, "Panel contract"), all signed

_LOCK = threading.Lock()
_LEASE_SEEN: dict[str, float] = {}  # "iat" of the lease received in this process -> time.monotonic() then
_WAKE = threading.Event()


def state() -> dict[str, Any]:
    return storage().get(COLLECTION, "state") or {}


def _save(**values: Any) -> dict[str, Any]:
    def change(doc: dict[str, Any] | None) -> dict[str, Any]:
        return {**(doc or {}), **values}

    with _LOCK:
        return storage().change(COLLECTION, "state", change) or {}


def enabled() -> bool:
    return bool(settings.marketplace)


# ---------------------------------------------------------------- time


def trusted_now() -> float:
    """Now, never earlier than what the panel already saw (see the module's description)."""
    current = state()
    candidates = [time.time(), float(current.get("high_water") or 0)]
    iat = current.get("lease_iat")
    if iat and str(iat) in _LEASE_SEEN:
        candidates.append(float(iat) + time.monotonic() - _LEASE_SEEN[str(iat)])
    elif iat:
        candidates.append(float(iat))
    return max(candidates)


def remember_time() -> None:
    """Keep the latest time seen (called now and then by the watchdog)."""
    now = trusted_now()
    if now > float(state().get("high_water") or 0):
        _save(high_water=now)


# ---------------------------------------------------------------- lease


def lease() -> crypto.Lease | None:
    """The stored lease while it verifies with the pinned keys and has not expired; None otherwise."""
    token = state().get("lease")
    if not token:
        return None
    try:
        me = client.identity()
        return crypto.read_lease(token, me.pinned(), client.hub_url(), me.installation_id, trusted_now())
    except (crypto.LeaseError, ValueError):
        return None


def blocked() -> str | None:
    """integrity_violation or installation_suspended while the hub's last answer said so; None otherwise."""
    status = state().get("hub_status")
    return status if status in BLOCKING else None


# ---------------------------------------------------------------- registration and heartbeat


def _pin_keys(me: client.Identity) -> client.Identity:
    """Fetch and pin the hub's keys the first time the panel registers with this hub."""
    if me.pinned():
        return me
    keys = client.get("/api/v1/keys")
    if not isinstance(keys, list) or not keys:
        raise HubUnavailable("The marketplace did not send its keys.")
    pinned: dict[str, str] = {}
    for item in keys:
        if isinstance(item, dict) and item.get("algorithm", "Ed25519") == "Ed25519":
            key = crypto.public_key_from_b64url(str(item.get("public_key", "")))
            kid = crypto.key_id(key)
            if item.get("key_id") not in (None, kid):
                raise HubUnavailable("The marketplace sent a key whose id does not match it.")
            pinned[kid] = crypto.public_key_b64url(key)
    client.update_identity(hub_url=client.hub_url(), hub_keys=pinned, registered_at=None)
    return client.identity()


def register() -> client.Identity:
    """Register this installation with the hub (once per hub); returns the identity with the pinned keys."""
    me = _pin_keys(client.identity())
    if me.registered_at and me.hub_url == client.hub_url():
        return me
    body = {
        "installation_id": me.installation_id,
        "public_key": me.public_key,
        "hardware_fingerprint": client.hardware_fingerprint(me.installation_id),
        "sudoo_version": client.sudoo_version(),
        "core_hash": client.core_hash(),
    }
    answer = client.request("POST", "/api/v1/register", body).data or {}
    hub_key = (answer.get("hub_key") or {}) if isinstance(answer, dict) else {}
    if hub_key.get("key_id") not in me.hub_keys:
        raise HubRefused(409, "The marketplace answered with a key this panel has not pinned.", "key_mismatch")
    client.update_identity(registered_at=time.time())
    return client.identity()


def installed_report() -> list[dict[str, str]]:
    from sudoo import plugin_manager

    return [{"id": r["id"], "version": r["version"]} for r in plugin_manager.records().values()]


def heartbeat() -> dict[str, Any]:
    """Register when needed, send the heartbeat, keep the lease. Raises HubUnavailable or HubRefused; the state
    records the outcome either way."""
    _save(last_attempt_at=time.time())
    try:
        me = register()
        body = {
            "sudoo_version": client.sudoo_version(),
            "core_hash": client.core_hash(),
            "hardware_fingerprint": client.hardware_fingerprint(me.installation_id),
            "plugins": installed_report(),
        }
        answer = client.request("POST", "/api/v1/heartbeat", body).data or {}
        token = answer.get("lease") if isinstance(answer, dict) else None
        if not isinstance(token, str):
            raise HubUnavailable("The marketplace's answer had no lease.")
        try:
            verified = crypto.read_lease(token, me.pinned(), client.hub_url(), me.installation_id, trusted_now())
        except crypto.LeaseError as error:
            raise HubRefused(502, f"The marketplace's lease was refused: {error}.", "bad_lease") from error
    except HubRefused as error:
        values: dict[str, Any] = {"error": error.detail, "error_code": error.code}
        if error.code in BLOCKING or error.code == "unknown_version":
            values["hub_status"] = error.code
        _save(**values)
        _changed()
        raise
    except HubUnavailable as error:
        _save(error=str(error), error_code="unreachable")
        _changed()
        raise
    _LEASE_SEEN[str(verified.issued_at)] = time.monotonic()
    next_at = verified.claims.get("next_heartbeat")
    current = _save(
        lease=token,
        lease_iat=verified.issued_at,
        lease_exp=verified.expires_at,
        last_heartbeat_at=time.time(),
        next_heartbeat_at=float(next_at) if isinstance(next_at, int | float) else time.time() + HEARTBEAT_HOURS * 3600,
        integrity=answer.get("integrity"),
        hub_status=str(verified.claims.get("status") or "active"),
        error=None,
        error_code=None,
        high_water=max(float(state().get("high_water") or 0), float(verified.issued_at)),
    )
    from sudoo import plugin_manager

    plugin_manager.apply_lease(verified)
    _changed()
    return current


def _changed() -> None:
    from sudoo.core import events

    events.publish("marketplace", "status", {"changed": True})


def heartbeat_forever() -> None:
    """Background loop: heartbeat at start, then when the lease asks (6 hours), retrying every 15 minutes while
    the hub cannot be reached. Never raises."""
    while True:
        wait = RETRY_MINUTES * 60.0
        if enabled():
            try:
                current = heartbeat()
                wait = max(60.0, float(current.get("next_heartbeat_at") or 0) - time.time())
                wait = min(wait, HEARTBEAT_HOURS * 3600)
            except HubRefused as error:
                log.warning("marketplace heartbeat refused: %s", error.detail)
            except HubUnavailable as error:
                log.info("marketplace heartbeat: %s", error)
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("marketplace heartbeat failed")
        _WAKE.wait(wait)
        _WAKE.clear()


def wake() -> None:
    """Send a heartbeat soon (after a plugin was installed or removed)."""
    _WAKE.set()


# ---------------------------------------------------------------- linking, catalogue, purchases


def link(code: str) -> dict[str, Any]:
    """Link this panel to the app.sudoo.sh account that made the one-time code (sent signed)."""
    register()
    answer = client.request("POST", "/api/v1/link", {"code": code}).data or {}
    linked = {"account_name": answer.get("account_name"), "linked_at": answer.get("linked_at")}
    _save(linked=linked)
    _changed()
    return linked


def _for_panel(method: str, path: str, body: Any = None) -> client.Answer:
    """A signed call of the panel contract. The hub serves it only with a current lease: when it says the lease
    expired, send a heartbeat and try once more."""
    register()
    try:
        return client.request(method, path, body)
    except HubRefused as error:
        if error.code != "lease_expired":
            raise
    heartbeat()
    return client.request(method, path, body)


def _object(answer: client.Answer) -> dict[str, Any]:
    if not isinstance(answer.data, dict):
        raise HubUnavailable("The marketplace sent an answer the panel does not understand.")
    return answer.data


def _list(answer: client.Answer) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = answer.headers.get("x-sudoo-meta")
    items = [item for item in answer.data if isinstance(item, dict)] if isinstance(answer.data, list) else []
    return items, (json.loads(meta) if meta else {})


def catalog(query: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The catalogue for this panel: each plugin with `plans`, `latest_version`, `compatible_version`,
    `installed_version`, `license` and `action` (install, update, installed, buy, renew, incompatible)."""
    path = f"{PANEL}/catalog?{urlencode(query)}" if query else f"{PANEL}/catalog"
    return _list(_for_panel("GET", path))


def plugin(plugin_id: str) -> dict[str, Any]:
    """The public page of one plugin: permissions, screenshots, plans (no signature needed)."""
    data = client.get(f"/api/v1/catalog/{plugin_id}")
    if not isinstance(data, dict):
        raise HubUnavailable("The marketplace sent an answer the panel does not understand.")
    return data


def categories() -> list[dict[str, Any]]:
    data = client.get("/api/v1/categories")
    return data if isinstance(data, list) else []


def billing() -> dict[str, Any]:
    """Whether this server may buy: linked, purchases_allowed, the monthly limit, the card a purchase charges."""
    return _object(_for_panel("GET", f"{PANEL}/billing"))


def install_info(plugin_id: str, version: str | None) -> dict[str, Any]:
    """May this plugin be installed, and the package to download: download_path, package_sha256, signature,
    signing_key_id, version, tier, requires, license."""
    body: dict[str, Any] = {"plugin_id": plugin_id}
    if version:
        body["version"] = version
    return _object(_for_panel("POST", f"{PANEL}/install", body))


def buy(plugin_id: str, plan_id: str, idempotency_key: str, requested_by: dict[str, str]) -> dict[str, Any]:
    """Buy a paid plugin for this server. The answer is a purchase: `succeeded` (the saved card was charged; install
    now), `checkout_required` (open `checkout_url`), `processing` (follow it), `failed` or `expired` (`reason`).
    The same idempotency key always answers the same purchase, so a retried request never charges twice."""
    body = {
        "plugin_id": plugin_id,
        "plan_id": plan_id,
        "idempotency_key": idempotency_key,
        "requested_by": requested_by,
    }
    return _object(_for_panel("POST", f"{PANEL}/purchase", body))


def purchase(purchase_id: str) -> dict[str, Any]:
    return _object(_for_panel("GET", f"{PANEL}/purchases/{purchase_id}"))


def purchases(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return _list(_for_panel("GET", f"{PANEL}/purchases?limit={limit}&offset={offset}"))[0]


def receipts(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return _list(_for_panel("GET", f"{PANEL}/receipts?limit={limit}&offset={offset}"))[0]


# ---------------------------------------------------------------- what the web app shows


def status() -> dict[str, Any]:
    """The marketplace as the Plugins page and Settings → Marketplace show it."""
    current = state()
    held = lease()
    try:
        me = client.identity()
        installation_id: str | None = me.installation_id
        registered = bool(me.registered_at and me.hub_url == client.hub_url())
    except Exception:  # noqa: BLE001 - the vault key may be missing on a broken install; the page still opens
        installation_id, registered = None, False
    lease_exp = float(held.expires_at) if held else None
    return {
        "enabled": enabled(),
        "hub_url": client.hub_url(),
        "installation_id": installation_id,
        "registered": registered,
        "reachable": current.get("error_code") != "unreachable" if current.get("last_attempt_at") else None,
        "error": current.get("error"),
        "error_code": current.get("error_code"),
        "hub_status": current.get("hub_status"),
        "linked": current.get("linked"),
        "last_heartbeat_at": current.get("last_heartbeat_at"),
        "next_heartbeat_at": current.get("next_heartbeat_at"),
        "lease_expires_at": lease_exp,
        "lease_valid": held is not None,
        "lease_ending_soon": bool(lease_exp and lease_exp - trusted_now() < LEASE_WARNING_DAYS * 86400),
    }
