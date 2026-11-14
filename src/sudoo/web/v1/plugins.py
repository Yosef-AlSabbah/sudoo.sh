"""Plugins and the marketplace (docs/MARKETPLACE.md).

    GET    /api/v1/plugins                         installed plugins: status, licence, update available
    GET    /api/v1/plugins/notices                 banners: licences ending or ended, modified plugins
    POST   /api/v1/plugins                         install {"id", "version"?} -> 202 job (then the backend restarts)
    POST   /api/v1/plugins/<id>/update             install the newest version -> 202 job
    POST   /api/v1/plugins/<id>/disable|enable     switch off or on (the backend restarts) -> the plugin
    DELETE /api/v1/plugins/<id>                    uninstall {"confirm": "<id>"} after a backup -> 202 job
    GET    /api/v1/marketplace                     the connection to the hub: registered, linked, lease, errors
    POST   /api/v1/marketplace/link                {"code"}: link this panel to an app.sudoo.sh account
    POST   /api/v1/marketplace/heartbeat           send the heartbeat now
    GET    /api/v1/marketplace/catalog             the catalogue for this panel, with each plugin's action
    GET    /api/v1/marketplace/catalog/<id>        one plugin's public page: permissions, screenshots, plans
    GET    /api/v1/marketplace/categories          plugin types with counts
    GET    /api/v1/marketplace/billing             may this server buy, its limit, the card a purchase charges
    GET    /api/v1/marketplace/purchases           purchases asked for from this server (?format=csv for a file)
    POST   /api/v1/marketplace/purchases           buy {"plugin_id", "plan_id", "idempotency_key"}
    GET    /api/v1/marketplace/purchases/<id>      one purchase (the web app follows a Checkout with it)
    GET    /api/v1/marketplace/receipts            receipts of this server's plugins (?format=csv for a file)

Seeing needs "plugins.view" (super admins and administrators); installing, buying, switching and linking need
"settings.manage" (super admins). No endpoint returns a plugin's files or package.
"""

from __future__ import annotations

import csv
import io
import threading
import time
from typing import Any, NoReturn
from urllib.parse import urlsplit

from flask import Blueprint, Response, abort, g, request

from sudoo import accounts, plugin_manager
from sudoo.core import jobs
from sudoo.hub import HubRefused, HubUnavailable, marketplace

from .. import validation as check
from ..security import log, require
from .resources import job_resource
from .responses import PREFIX, iso, ok

blueprint = Blueprint("plugins", __name__)

UNREACHABLE = "The marketplace cannot be reached right now. Installed plugins keep working; try again later."
_LATEST: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}  # "installed" -> (when asked, the hub's view)
_LATEST_SECONDS = 600
_LATEST_LOCK = threading.Lock()


def _hub_error(error: Exception) -> NoReturn:
    """Turn a hub failure into an answer the web app shows (never 401, which would sign the person out)."""
    if isinstance(error, HubUnavailable):
        abort(503, UNREACHABLE)
    if isinstance(error, HubRefused):
        status = {404: 404, 422: 400, 429: 429}.get(error.status, 409)
        abort(status, plugin_manager._hub_message(error))
    raise error


def _marketplace_on() -> None:
    if not marketplace.enabled():
        abort(409, "The marketplace is switched off on this panel (Settings, Marketplace).")


# ---------------------------------------------------------------- installed plugins


def _hub_view() -> dict[str, dict[str, Any]]:
    """What the hub says about the installed plugins (action, compatible_version), asked at most every 10 minutes;
    the last answer when the hub cannot be reached."""
    with _LATEST_LOCK:
        cached = _LATEST.get("installed")
    if cached and time.time() - cached[0] < _LATEST_SECONDS:
        return cached[1]
    view = cached[1] if cached else {}
    if marketplace.enabled():
        try:
            items, _ = marketplace.catalog({"installed": "true", "limit": "100"})
            view = {str(item.get("id")): item for item in items}
        except (HubUnavailable, HubRefused):
            pass
    with _LATEST_LOCK:
        _LATEST["installed"] = (time.time(), view)
    return view


def plugin_resource(
    rec: dict[str, Any], now: float, lease_valid: bool, hub: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    licence = rec.get("licence") or {}
    seen = (hub or {}).get(rec["id"]) or {}
    compatible = seen.get("compatible_version")
    newest = compatible.get("version") if isinstance(compatible, dict) else None
    try:
        update = bool(newest and plugin_manager.semver_key(newest) > plugin_manager.semver_key(rec["version"]))
    except ValueError:
        update = False
    loaded = rec["id"] in (plugin_manager.LOADED or set())
    running = plugin_manager.allowed(rec, now, lease_valid)[0]
    return {
        "id": rec["id"],
        "name": rec.get("name", rec["id"]),
        "version": rec["version"],
        "type": rec.get("type"),
        "tier": rec.get("tier", "free"),
        "description": rec.get("description", ""),
        "publisher": rec.get("publisher"),
        "permissions": rec.get("permissions", []),
        "requires": rec.get("requires", []),
        "enabled": rec.get("enabled", True),
        # active, disabled, modified, blocked, switched_off (licence ended or no lease), unlicensed
        "status": plugin_manager.status_of(rec, now, lease_valid),
        "loaded": loaded,
        "restart_pending": loaded != running,
        "licence": (
            {
                "state": licence.get("state"),
                "standing": rec.get("standing"),
                "expires_at": iso(licence.get("expires_at")),
                "grace_until": iso(licence.get("grace_until")),
                "phase": plugin_manager.phase(rec, now, lease_valid),
            }
            if rec.get("tier") == "paid"
            else None
        ),
        "latest_version": newest,
        "update_available": update,
        "installed_at": iso(rec.get("installed_at")),
        "installed_by": rec.get("installed_by"),
        "updated_at": iso(rec.get("updated_at")),
    }


def _installed(plugin_id: str) -> dict[str, Any]:
    rec = plugin_manager.record(check.plugin_id(plugin_id))
    if rec is None:
        abort(404, "This plugin is not installed.")
    return rec


@blueprint.get("/plugins")
@require("plugins.view")
def installed() -> Response:
    now, lease_valid = marketplace.trusted_now(), marketplace.lease() is not None
    found = sorted(plugin_manager.records().values(), key=lambda r: str(r.get("name", r["id"])).lower())
    hub = _hub_view() if found else {}
    return ok(
        [plugin_resource(rec, now, lease_valid, hub) for rec in found],
        meta={"restart_pending": plugin_manager.restart_pending()},
    )


@blueprint.get("/plugins/notices")
@require("plugins.view")
def notices() -> Response:
    return ok([{**notice, "date": iso(notice.get("date"))} for notice in plugin_manager.notices()])


def _start_install(plugin_id: str, version: str | None, title: str) -> jobs.Job:
    if jobs.ACTIVE_JOB:
        running = ", ".join(sorted(j.instance for j in jobs.ACTIVE_JOB.values()))
        abort(409, f"Jobs are running ({running}). Install when they have finished: the panel restarts afterwards.")
    if plugin_manager.restart_pending():
        abort(409, "The panel is about to restart. Try again in a minute.")
    return jobs.start(
        plugin_manager.JOB_INSTANCE, title, "plugin-install", plugin_manager.install, plugin_id, version,
        g.user["name"], user=g.user["name"],
    )  # fmt: skip


def _accepted(job: jobs.Job) -> Response:
    response = ok(job_resource(job), status=202)
    response.headers["Location"] = f"{PREFIX}/jobs/{job.id}"
    return response


@blueprint.post("/plugins")
@require("settings.manage")
def install() -> Response:
    _marketplace_on()
    data = check.body()
    plugin_id = check.plugin_id(check.text(data, "id", max_length=128))
    version = check.text(data, "version", max_length=64) or None
    if version:
        check.plugin_version(version)
    current = plugin_manager.record(plugin_id)
    if current and current["version"] == version and not current.get("tampered"):
        abort(409, f"{plugin_id} {version} is already installed.")
    log("plugin install requested", detail=f"{plugin_id} {version or 'latest'}")
    return _accepted(_start_install(plugin_id, version, f"Install {plugin_id}"))


@blueprint.post("/plugins/<plugin_id>/update")
@require("settings.manage")
def update(plugin_id: str) -> Response:
    _marketplace_on()
    rec = _installed(plugin_id)
    log("plugin update requested", detail=plugin_id)
    return _accepted(_start_install(rec["id"], None, f"Update {rec.get('name', rec['id'])}"))


def _switch(plugin_id: str, value: bool) -> Response:
    rec = _installed(plugin_id)
    try:
        updated = plugin_manager.set_enabled(rec["id"], value, g.user["name"])
    except plugin_manager.PluginRefused as error:
        abort(409, str(error))
    return ok(plugin_resource(updated, marketplace.trusted_now(), marketplace.lease() is not None))


@blueprint.post("/plugins/<plugin_id>/disable")
@require("settings.manage")
def disable(plugin_id: str) -> Response:
    return _switch(plugin_id, False)


@blueprint.post("/plugins/<plugin_id>/enable")
@require("settings.manage")
def enable(plugin_id: str) -> Response:
    return _switch(plugin_id, True)


@blueprint.delete("/plugins/<plugin_id>")
@require("settings.manage")
def uninstall(plugin_id: str) -> Response:
    rec = _installed(plugin_id)
    if check.text(check.body(), "confirm", max_length=128) != rec["id"]:
        abort(400, f'To uninstall, send {{"confirm": "{rec["id"]}"}}.')
    if needed_by := plugin_manager.dependents(rec["id"]):
        abort(409, f"Uninstall {', '.join(needed_by)} first: it needs this plugin.")
    if jobs.ACTIVE_JOB:
        abort(409, "Jobs are running. Uninstall when they have finished: the panel restarts afterwards.")
    log("plugin uninstall requested", detail=rec["id"])
    job = jobs.start(
        plugin_manager.JOB_INSTANCE, f"Uninstall {rec.get('name', rec['id'])}", "plugin-uninstall",
        plugin_manager.uninstall, rec["id"], g.user["name"], user=g.user["name"],
    )  # fmt: skip
    return _accepted(job)


# ---------------------------------------------------------------- the marketplace


@blueprint.get("/marketplace")
@require("plugins.view")
def status() -> Response:
    current = marketplace.status()
    for key in ("last_heartbeat_at", "next_heartbeat_at", "lease_expires_at"):
        current[key] = iso(current[key])
    return ok(current)


@blueprint.post("/marketplace/link")
@require("settings.manage")
def link() -> Response:
    _marketplace_on()
    code = check.link_code(check.text(check.body(), "code", max_length=32).replace(" ", ""))
    try:
        linked = marketplace.link(code)
    except (HubUnavailable, HubRefused) as error:
        log("panel link refused", ok=False)
        _hub_error(error)
    log("panel linked to a Sudoo.sh account", detail=linked.get("account_name"))
    return ok(linked)


@blueprint.post("/marketplace/heartbeat")
@require("settings.manage")
def heartbeat() -> Response:
    _marketplace_on()
    try:
        marketplace.heartbeat()
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    return status()


_SORTS = ("popular", "rating", "newest", "name", "trusted")
_TIERS = ("free", "paid")


def _query() -> dict[str, str]:
    args = request.args
    query: dict[str, str] = {}
    q = check.text(args, "q", max_length=100)
    if q:
        query["q"] = q
    kind = check.text(args, "type", max_length=40)
    if kind:
        if not kind.replace("_", "").isalpha():
            abort(400, "Give a plugin type such as mailer.")
        query["type"] = kind
    for key, allowed in (("tier", _TIERS), ("installed", ("true", "false")), ("sort", _SORTS)):
        value = args.get(key, "")
        if value:
            query[key] = check.one_of(value, allowed, f"{key} must be one of: {', '.join(allowed)}.")
    query["limit"] = str(check.whole_number(args.get("limit", "50"), "limit", minimum=1, maximum=100))
    query["offset"] = str(check.whole_number(args.get("offset", "0"), "offset", maximum=100_000))
    return query


@blueprint.get("/marketplace/catalog")
@require("plugins.view")
def catalog() -> Response:
    _marketplace_on()
    try:
        items, meta = marketplace.catalog(_query())
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    installed_versions = {pid: rec["version"] for pid, rec in plugin_manager.records().items()}
    for item in items:  # what is on disk now (the hub knows what the last heartbeat reported)
        item["installed_version"] = installed_versions.get(str(item.get("id")))
    return ok(items, meta=meta)


@blueprint.get("/marketplace/catalog/<plugin_id>")
@require("plugins.view")
def catalog_plugin(plugin_id: str) -> Response:
    _marketplace_on()
    try:
        detail = marketplace.plugin(check.plugin_id(plugin_id))
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    rec = plugin_manager.record(plugin_id)
    detail["installed_version"] = rec["version"] if rec else None
    return ok(detail)


@blueprint.get("/marketplace/categories")
@require("plugins.view")
def categories() -> Response:
    _marketplace_on()
    try:
        return ok(marketplace.categories())
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)


def _https(value: Any) -> str | None:
    """Only https links from the hub reach the browser."""
    return value if isinstance(value, str) and urlsplit(value).scheme == "https" else None


@blueprint.get("/marketplace/billing")
@require("plugins.view")
def billing() -> Response:
    _marketplace_on()
    try:
        found = marketplace.billing()
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    keys = ("payments_enabled", "linked", "account_name", "purchases_allowed", "monthly_limit_cents",
            "spent_this_month_cents", "remaining_cents", "currency", "card")  # fmt: skip
    return ok({**{key: found.get(key) for key in keys}, "manage_url": _https(found.get("manage_url"))})


def purchase_resource(item: dict[str, Any]) -> dict[str, Any]:
    """A purchase as the hub's panel contract shows it, with only https links."""
    requested: dict[str, Any] = item["requested_by"] if isinstance(item.get("requested_by"), dict) else {}
    return {
        "id": str(item.get("id", "")),
        "plugin_id": item.get("plugin_id"),
        "plugin_name": item.get("plugin_name") or item.get("plugin_id"),
        "plan_id": item.get("plan_id"),
        "plan_kind": item.get("plan_kind"),
        "amount_cents": item.get("amount_cents"),
        "currency": item.get("currency"),
        "status": item.get("status"),  # succeeded, processing, checkout_required, failed, expired
        "method": item.get("method"),  # saved_card or checkout
        "reason": item.get("reason"),
        "checkout_url": _https(item.get("checkout_url")),
        "license": item.get("license"),
        "receipt_number": item.get("receipt_number"),
        "requested_by": {"name": requested.get("name"), "email": requested.get("email")},
        "created_at": item.get("created_at"),
        "completed_at": item.get("completed_at"),
    }


def receipt_resource(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "kind", "number", "issued_at", "plugin_id", "plugin_name", "plan_kind", "payment_kind",
            "total_cents", "currency", "requested_by_name")  # fmt: skip
    return {key: item.get(key) for key in keys}


def _csv(rows: list[dict[str, Any]], columns: list[str], filename: str) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    response = Response(out.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _cell(value: Any) -> str:
    """A CSV cell that a spreadsheet will not run as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@blueprint.get("/marketplace/purchases")
@require("plugins.view")
def purchases() -> Response:
    _marketplace_on()
    try:
        found = [purchase_resource(p) for p in marketplace.purchases()]
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    if request.args.get("format") == "csv":
        rows = [{**p, "requested_by": p["requested_by"]["name"]} for p in found]
        columns = ["created_at", "plugin_name", "plugin_id", "plan_kind", "amount_cents", "currency", "status",
                   "method", "reason", "receipt_number", "requested_by"]  # fmt: skip
        return _csv(rows, columns, "sudoo-purchases.csv")
    return ok(found)


@blueprint.get("/marketplace/receipts")
@require("plugins.view")
def receipts() -> Response:
    _marketplace_on()
    try:
        found = [receipt_resource(r) for r in marketplace.receipts()]
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    if request.args.get("format") == "csv":
        columns = ["number", "kind", "issued_at", "plugin_name", "plugin_id", "plan_kind", "payment_kind",
                   "total_cents", "currency", "requested_by_name"]  # fmt: skip
        return _csv(found, columns, "sudoo-receipts.csv")
    return ok(found)


def _requested_by() -> dict[str, str]:
    """Who pressed Buy: kept with the purchase and printed on the receipt."""
    account = accounts.get(g.user["name"]) or {}
    email = account.get("email") or ""
    if not email:
        abort(400, "Your account has no e-mail address; add one under My account before buying.")
    name = accounts.display_name(g.user["name"], account) if account else g.user["name"]
    return {"name": "".join(c for c in name if c not in "<>")[:120] or g.user["name"], "email": email}


@blueprint.post("/marketplace/purchases")
@require("settings.manage")
def buy() -> Response:
    _marketplace_on()
    data = check.body()
    plugin_id = check.plugin_id(check.text(data, "plugin_id", max_length=128))
    plan_id = check.hub_reference(check.text(data, "plan_id", max_length=64), "plan")
    key = check.idempotency_key(check.text(data, "idempotency_key", max_length=64))
    try:
        bought = purchase_resource(marketplace.buy(plugin_id, plan_id, key, _requested_by()))
    except (HubUnavailable, HubRefused) as error:
        log("plugin purchase refused", ok=False, detail=plugin_id)
        _hub_error(error)
    log("plugin purchase", detail=f"{plugin_id} {bought['status']} {bought['method'] or ''}".strip())
    if bought["status"] == "succeeded":  # the saved card was charged: install at once
        job = _start_install(plugin_id, None, f"Install {plugin_id}")
        return ok({"purchase": bought, "job": job_resource(job)}, status=202)
    return ok({"purchase": bought, "job": None})


@blueprint.get("/marketplace/purchases/<purchase_id>")
@require("settings.manage")
def purchase(purchase_id: str) -> Response:
    _marketplace_on()
    try:
        found = marketplace.purchase(check.hub_reference(purchase_id, "purchase"))
    except (HubUnavailable, HubRefused) as error:
        _hub_error(error)
    return ok(purchase_resource(found))
