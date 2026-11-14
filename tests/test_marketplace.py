"""The marketplace, against a fake hub (fake_hub.py): signatures and leases in the hub's formats, registration and
heartbeat, installing (free and paid), tampered packages, compatibility, integrity, licences (expiry, grace,
renewal), purchases, linking, and a hub that cannot be reached."""

from __future__ import annotations

import base64
import io
import json
import shutil
import stat
import time
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask
from flask.testing import FlaskClient

from conftest import RESTARTS, sign_in
from fake_hub import FakeHub, Listing, make_package
from sudoo import accounts, plugin_manager, plugins
from sudoo.config import settings
from sudoo.core import jobs
from sudoo.hub import HubRefused, HubUnavailable, client, crypto, marketplace
from sudoo.storage import storage

Client = tuple[FlaskClient, dict[str, str]]
FREE = "com.example.hello"
PAID = "com.example.paid"


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeHub]:
    """A running fake hub, and a panel that has never talked to a hub and has no plugins."""
    fake = FakeHub().start()
    monkeypatch.setattr(client, "hub_url", lambda: fake.url)
    for collection in (plugin_manager.COLLECTION, client.COLLECTION):
        for key in storage().all(collection):
            storage().delete(collection, key)
    shutil.rmtree(plugin_manager.plugins_dir(), ignore_errors=True)
    plugin_manager.LOADED = set()
    plugin_manager._RESTART_PENDING.clear()
    from sudoo.web.v1 import plugins as api

    api._LATEST.clear()
    RESTARTS.clear()
    yield fake
    fake.stop()
    plugin_manager._RESTART_PENDING.clear()


def wait(job_id: str, seconds: float = 20) -> jobs.Job:
    job = jobs.JOBS[job_id]
    deadline = time.time() + seconds
    while job.finished is None and time.time() < deadline:
        time.sleep(0.05)
    assert job.finished is not None, "the job did not finish"
    return job


def install(admin: Client, plugin_id: str, **body: Any) -> jobs.Job:
    web, headers = admin
    answer = web.post("/api/v1/plugins", json={"id": plugin_id, **body}, headers=headers)
    assert answer.status_code == 202, answer.get_json()
    return wait(answer.get_json()["data"]["id"])


def free_listing(fake: FakeHub, version: str = "1.0.0", **kwargs: Any) -> Listing:
    return fake.publish(Listing(FREE, "Hello mailer", versions={version: make_package(FREE, version, **kwargs)}))


# ---------------------------------------------------------------- the hub's formats (vectors made by sudoo-hub)

HUB_PUBLIC = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
HUB_KID = "56475aa75463474c"
LEASE = (
    "eyJhbGciOiJFZERTQSIsImtpZCI6IjU2NDc1YWE3NTQ2MzQ3NGMiLCJ0eXAiOiJzdWRvby1sZWFzZStqd3QifQ.eyJpc3MiOiJodHRwczovL2h1Yi5zdWRvby5zaCIsImF1ZCI6InN1ZG9vLXBhbmVsOjEyMzQ1Njc4LTEyMzQtNDIzNC05MjM0LTEyMzQ1Njc4OWFiYyIsInN1YiI6IjEyMzQ1Njc4LTEyMzQtNDIzNC05MjM0LTEyMzQ1Njc4OWFiYyIsImlhdCI6MTc5MzUzNDQwMCwibmJmIjoxNzkzNTM0NDAwLCJleHAiOjE3OTQxMzkyMDAsImp0aSI6IjRuSm44V2xhUU11S1RrZ28iLCJzdGF0dXMiOiJhY3RpdmUiLCJwbHVnaW5zIjp7ImNvbS5leGFtcGxlLnBhaWQiOiJsaWNlbnNlZCIsImNvbS5leGFtcGxlLmZyZWUiOiJmcmVlIn0sImxpY2Vuc2VzIjp7ImNvbS5leGFtcGxlLnBhaWQiOnsic3RhdGUiOiJhY3RpdmUiLCJleHBpcmVzX2F0IjoxNzk1MDAwMDAwLCJncmFjZV91bnRpbCI6MTc5NTYwNDgwMH19LCJuZXh0X2hlYXJ0YmVhdCI6MTc5MzU1NjAwMH0"
    ".UTJDgOzqQJjLXDv67B52WZjVIdSHbmGfkZMWoxdM8wqqNGZUOQBLun_fiG9-W8zj7bKhh0eEb-MuUggZ9WLjDA"
)
INSTALLATION = "12345678-1234-4234-9234-123456789abc"


def test_package_signature_made_by_the_hub_verifies() -> None:
    key = crypto.public_key_from_b64url(HUB_PUBLIC)
    assert crypto.key_id(key) == HUB_KID
    sha = "07531963baeda377d96af8e056cb8d13b9f6e20eba0349410c0026df1b9c6053"
    signature = "ekEmUZINboxfJbHPHQB8X9-v7qqQM64dgdc-efPr-qHhWYW45-PkbFBKyhECVl0BNO_XpvRSBa0LA0jFRNT3Cw"
    assert crypto.verify_package(key, "com.example.hello", "1.2.3", sha, signature)
    # bound to the plugin, the version and the bytes
    assert not crypto.verify_package(key, "com.example.other", "1.2.3", sha, signature)
    assert not crypto.verify_package(key, "com.example.hello", "1.2.2", sha, signature)
    assert not crypto.verify_package(key, "com.example.hello", "1.2.3", "0" * 64, signature)
    assert not crypto.verify_package(key, "com.example.hello", "1.2.3", sha, "not-a-signature")


def test_request_signature_matches_the_hub_format() -> None:
    message = crypto.request_message(
        "POST", "/api/v1/heartbeat", INSTALLATION, 1790000000, "abcdefghijklmnop", b'{"a":1}'
    )
    hub_made = bytes.fromhex(  # hub.services.panels.signing_message with the same values
        "7375646f6f2d6875622d726571756573742d76310a504f53540a2f6170692f76312f6865617274626561740a313233343536"
        "37382d313233342d343233342d393233342d3132333435363738396162630a313739303030303030300a6162636465666768"
        "696a6b6c6d6e6f700a3031356162643766356363353761326464393462373539306630346164383038343237333930356565"
        "3333656335636562656165363232373661393766383632"
        ""
    )
    assert message == hub_made
    key = Ed25519PrivateKey.generate()
    headers = crypto.signed_headers(key, INSTALLATION, "POST", "/api/v1/heartbeat", b"{}", 1790000000)
    signed = crypto.request_message(
        "POST", "/api/v1/heartbeat", INSTALLATION, 1790000000, headers["X-Sudoo-Nonce"], b"{}"
    )
    key.public_key().verify(crypto.from_b64url(headers["X-Sudoo-Signature"]), signed)


def test_lease_made_by_the_hub_verifies() -> None:
    keys = {HUB_KID: crypto.public_key_from_b64url(HUB_PUBLIC)}
    lease = crypto.read_lease(LEASE, keys, "https://hub.sudoo.sh", INSTALLATION, now=1793534500)
    assert lease.plugins == {"com.example.paid": "licensed", "com.example.free": "free"}
    assert lease.licences["com.example.paid"] == {
        "state": "active",
        "expires_at": 1795000000,
        "grace_until": 1795604800,
    }
    assert lease.expires_at - lease.issued_at == 7 * 86400


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("expired", "expired"),
        ("other-installation", "another installation"),
        ("other-hub", "another hub"),
        ("unknown-key", "does not trust"),
        ("tampered", "signature"),
        ("alg-none", "Ed25519"),
    ],
)
def test_bad_leases_are_refused(change: str, message: str) -> None:
    keys = {HUB_KID: crypto.public_key_from_b64url(HUB_PUBLIC)}
    token, issuer, installation, now = LEASE, "https://hub.sudoo.sh", INSTALLATION, 1793534500.0
    head, body, signature = token.split(".")
    if change == "expired":
        now = 1794139200 + 1
    elif change == "other-installation":
        installation = "87654321-1234-4234-9234-123456789abc"
    elif change == "other-hub":
        issuer = "https://evil.example.com"
    elif change == "unknown-key":
        keys = {"0000000000000000": keys[HUB_KID]}
    elif change == "tampered":
        claims = json.loads(crypto.from_b64url(body))
        claims["licenses"]["com.example.paid"]["grace_until"] = 2_000_000_000
        token = f"{head}.{crypto.b64url(json.dumps(claims).encode())}.{signature}"
    elif change == "alg-none":
        header = crypto.b64url(json.dumps({"alg": "none", "kid": HUB_KID}).encode())
        token = f"{header}.{body}.{signature}"
    with pytest.raises(crypto.LeaseError, match=message):
        crypto.read_lease(token, keys, issuer, installation, now)


def test_versions_and_specifiers() -> None:
    assert plugin_manager.satisfies("1.4.5", ">=1.0.0,<2.0.0")
    assert not plugin_manager.satisfies("2.0.0", ">=1.0.0,<2.0.0")
    assert plugin_manager.satisfies("1.4.9", "~=1.4.2") and not plugin_manager.satisfies("1.5.0", "~=1.4.2")
    assert plugin_manager.semver_key("1.0.0-rc.1") < plugin_manager.semver_key("1.0.0")
    assert plugin_manager.satisfies("0.1.0", None)


# ---------------------------------------------------------------- identity, registration, heartbeat


def test_register_and_heartbeat(hub: FakeHub) -> None:
    current = marketplace.heartbeat()
    me = client.identity()
    stored = storage().get(client.COLLECTION, "identity")
    assert stored is not None and stored["private_key"].startswith("enc:v1:")  # encrypted with the vault key
    assert me.installation_id in hub.installations
    assert set(me.pinned()) == {hub.key_id}  # the hub's key, pinned at registration
    assert current["lease"] and marketplace.lease() is not None
    report = hub.heartbeats[-1]
    assert len(report["core_hash"]) == 64 and report["plugins"] == []
    assert report["sudoo_version"] == client.sudoo_version()
    # a second heartbeat does not register again
    marketplace.heartbeat()
    assert sum(1 for r in hub.requests if r == "POST /api/v1/register") == 1


def test_a_lease_from_another_key_is_refused(hub: FakeHub) -> None:
    marketplace.heartbeat()
    hub.key = Ed25519PrivateKey.generate()  # the hub (or someone in between) now signs with another key
    with pytest.raises(HubRefused, match="lease was refused"):
        marketplace.heartbeat()
    assert marketplace.state()["error_code"] == "bad_lease"


def test_hub_unreachable_degrades(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    hub.stop()
    web, _ = admin
    with pytest.raises(HubUnavailable):
        marketplace.heartbeat()
    answer = web.get("/api/v1/marketplace/catalog")
    assert answer.status_code == 503
    assert "cannot be reached" in answer.get_json()["detail"]
    assert web.get("/api/v1/plugins").status_code == 200  # installed plugins still listed
    status = web.get("/api/v1/marketplace").get_json()["data"]
    assert status["reachable"] is False and status["lease_valid"] is False
    hub.start = lambda: hub  # type: ignore[method-assign]  # already stopped; the fixture stops it again
    hub.stop = lambda: None  # type: ignore[method-assign]


def test_marketplace_off(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    from sudoo.config import live

    live.change({"marketplace": False})
    try:
        web, headers = admin
        assert web.get("/api/v1/marketplace/catalog").status_code == 409
        assert web.post("/api/v1/plugins", json={"id": FREE}, headers=headers).status_code == 409
        assert web.get("/api/v1/marketplace").get_json()["data"]["enabled"] is False
    finally:
        live.change({"marketplace": None})


# ---------------------------------------------------------------- installing


def test_install_a_free_plugin(hub: FakeHub, admin: Client) -> None:
    free_listing(hub)
    job = install(admin, FREE)
    assert job.status == "success", "".join(job.log)
    rec = plugin_manager.record(FREE)
    assert rec is not None and rec["version"] == "1.0.0" and rec["enabled"]
    folder = plugin_manager.folder(rec)
    # private: folders 700, files 600, the package file is gone
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) in (0o700, 0o600) for p in folder.rglob("*"))
    assert not any((plugin_manager.plugins_dir() / ".downloads").iterdir())
    assert stat.S_IMODE(plugin_manager.plugins_dir().stat().st_mode) == 0o700
    # the backend restarts once the job has finished
    deadline = time.time() + 10
    while not RESTARTS and time.time() < deadline:
        time.sleep(0.1)
    assert RESTARTS
    # after the restart: the plugin's entry point is found by plugins.load
    plugin_manager.LOADED = None
    assert FREE in plugin_manager.activate()
    loaded = plugins.load("sudoo.mailers", "hello-mail", settings)
    assert type(loaded).__name__ == "Hello" and loaded.version == "1.0.0"
    # the API lists it without any file or path
    web, _ = admin
    listed = web.get("/api/v1/plugins").get_json()["data"]
    assert [p["id"] for p in listed] == [FREE] and listed[0]["status"] == "active"
    assert "package" not in json.dumps(listed) and str(folder) not in json.dumps(listed)
    # the next heartbeat reports it
    marketplace.heartbeat()
    assert hub.heartbeats[-1]["plugins"] == [{"id": FREE, "version": "1.0.0"}]


def test_install_through_a_storage_redirect_and_update(hub: FakeHub, admin: Client) -> None:
    hub.redirect_downloads = True
    listing = free_listing(hub, module="hello_redirect", entry="hello-redirect")
    assert install(admin, FREE).status == "success"
    listing.versions["1.1.0"] = make_package(FREE, "1.1.0", module="hello_redirect", entry="hello-redirect")
    plugin_manager._RESTART_PENDING.clear()
    marketplace.heartbeat()  # the hub now knows 1.0.0 is installed and offers 1.1.0
    web, headers = admin
    listed = web.get("/api/v1/plugins").get_json()["data"][0]
    assert listed["update_available"] is True and listed["latest_version"] == "1.1.0"
    item = web.get("/api/v1/marketplace/catalog?installed=true").get_json()["data"][0]
    assert item["action"] == "update"
    answer = web.post(f"/api/v1/plugins/{FREE}/update", headers=headers)
    assert wait(answer.get_json()["data"]["id"]).status == "success"
    rec = plugin_manager.record(FREE)
    assert rec is not None and rec["version"] == "1.1.0"
    assert not (plugin_manager.plugins_dir() / FREE / "1.0.0").exists()


def test_a_tampered_package_is_refused(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_tampered", entry="hello-tampered")
    hub.tamper_downloads = True
    job = install(admin, FREE)
    assert job.status == "failed"
    assert "SHA-256 does not match" in "".join(job.log)
    assert plugin_manager.record(FREE) is None
    assert not (plugin_manager.plugins_dir() / FREE / "1.0.0").exists()
    assert not any((plugin_manager.plugins_dir() / ".downloads").iterdir())  # the download is deleted too
    assert not RESTARTS


def test_a_package_signed_with_another_key_is_refused(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_otherkey", entry="hello-otherkey")
    marketplace.heartbeat()  # registers and pins the hub's key
    hub.key = Ed25519PrivateKey.generate()  # the same key id, another key: as if someone forged packages
    job = install(admin, FREE)
    assert job.status == "failed"
    assert plugin_manager.record(FREE) is None


def test_modified_files_are_detected(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_modified", entry="hello-modified")
    assert install(admin, FREE).status == "success"
    rec = plugin_manager.record(FREE)
    assert rec is not None
    target = plugin_manager.folder(rec) / "package" / "hello_modified" / "plugin.py"
    target.write_text("print('changed')\n")
    plugin_manager.LOADED = None
    assert FREE not in plugin_manager.activate()
    rec = plugin_manager.record(FREE)
    assert rec is not None and rec["tampered"]
    assert any(n["kind"] == "modified" for n in plugin_manager.notices())
    web, headers = admin
    assert web.post(f"/api/v1/plugins/{FREE}/enable", headers=headers).status_code == 409


def _zip(files: dict[str, bytes | str]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


def _package(**manifest: Any) -> dict[str, bytes | str]:
    return dict(_entries(make_package(FREE, "1.0.0", manifest=manifest)))


def _entries(package: bytes) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        for name in archive.namelist():
            yield name, archive.read(name)


@pytest.mark.parametrize(
    ("files", "message"),
    [
        (_package(min_sudoo_version="99.0.0"), "needs Sudoo.sh 99.0.0"),
        (_package(max_sudoo_version="0.0.1"), "works up to Sudoo.sh 0.0.1"),
        (_package(sdk_version=">=9.0.0"), "plugin SDK"),
        (_package(requires=["com.example.missing"]), "Install and enable com.example.missing first"),
        (_package(entry_points={"sudoo.storage": {"x": "hello_plugin.plugin:Hello"}}), "cannot be installed"),
        (_package(entry_points={"sudoo.mailers": {"smtp": "hello_plugin.plugin:Hello"}}), "already provides"),
        ({**_package(), "pyproject.toml": '[project]\nname="x"\ndependencies=["requests"]\n'}, "other Python packages"),
        ({**_package(), "requirements.txt": "requests==2.0\n"}, "other Python packages"),
        ({**_package(), "hello_plugin/fast.so": b"\x7fELF"}, "compiled code"),
        ({**_package(), "../evil.py": "x"}, "outside its folder"),
        ({**_package(), "/etc/evil.py": "x"}, "outside its folder"),
        ({**_package(), "flask/__init__.py": ""}, "would clash"),
        ({k: v for k, v in _package().items() if k != "manifest.json"}, "no manifest.json"),
        (_package(id="com.example.other"), "another plugin or version"),
    ],
)
def test_packages_that_do_not_suit_are_refused(files: dict[str, bytes | str], message: str) -> None:
    with pytest.raises(plugin_manager.PluginRefused, match=message):
        plugin_manager.check_package(_zip(files), FREE, "1.0.0")


def test_links_in_a_package_are_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in _package().items():
            archive.writestr(name, content)
        link = zipfile.ZipInfo("hello_plugin/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    with pytest.raises(plugin_manager.PluginRefused, match="link"):
        plugin_manager.check_package(zipfile.ZipFile(io.BytesIO(buffer.getvalue())), FREE, "1.0.0")


def test_installing_is_refused_while_jobs_run(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(jobs.ACTIVE_JOB, "demo", jobs.Job("demo", "Restart", "restart", "x"))
    web, headers = admin
    answer = web.post("/api/v1/plugins", json={"id": FREE}, headers=headers)
    assert answer.status_code == 409 and "Jobs are running" in answer.get_json()["detail"]


# ---------------------------------------------------------------- disable, enable, uninstall, permissions


def test_disable_enable_and_uninstall(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_switch", entry="hello-switch")
    assert install(admin, FREE).status == "success"
    plugin_manager.LOADED = None
    plugin_manager.activate()
    plugin_manager._RESTART_PENDING.clear()
    web, headers = admin
    off = web.post(f"/api/v1/plugins/{FREE}/disable", headers=headers).get_json()["data"]
    assert off["enabled"] is False and off["status"] == "disabled" and off["restart_pending"] is True
    plugin_manager._RESTART_PENDING.clear()
    on = web.post(f"/api/v1/plugins/{FREE}/enable", headers=headers).get_json()["data"]
    assert on["enabled"] is True and on["status"] == "active"
    plugin_manager._RESTART_PENDING.clear()
    assert web.delete(f"/api/v1/plugins/{FREE}", json={}, headers=headers).status_code == 400  # confirm needed
    answer = web.delete(f"/api/v1/plugins/{FREE}", json={"confirm": FREE}, headers=headers)
    job = wait(answer.get_json()["data"]["id"])
    assert job.status == "success", "".join(job.log)
    assert plugin_manager.record(FREE) is None
    assert not (plugin_manager.plugins_dir() / FREE).exists()
    backups = list(plugin_manager.panel_backups_dir().glob(f"panel__*__before-uninstall-{FREE}.zip"))
    assert backups and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    with zipfile.ZipFile(backups[0]) as archive:
        assert "sudoo.db" in archive.namelist()


def test_permissions(hub: FakeHub, app: Flask, admin: Client, operator: Client) -> None:
    web, _ = operator  # a developer sees nothing of plugins
    assert web.get("/api/v1/plugins").status_code == 403
    if not accounts.get("admin2"):
        accounts.create("admin2", "admin", "harbour-candle-orbit-58", email="admin2@example.com")
    viewer, headers = sign_in(app, "admin2", "harbour-candle-orbit-58")  # an administrator sees, cannot install
    assert viewer.get("/api/v1/plugins").status_code == 200
    assert viewer.post("/api/v1/plugins", json={"id": FREE}, headers=headers).status_code == 403
    assert viewer.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers).status_code == 403


# ---------------------------------------------------------------- linking and purchases


def paid_listing(fake: FakeHub) -> Listing:
    plan = {"id": "plan-monthly", "kind": "monthly", "price_cents": 500, "currency": "usd", "period_days": None}
    package = make_package(PAID, "2.0.0", module="paid_plugin", entry="paid-mail", tier="paid",
                           manifest={"name": "Paid plugin"})  # fmt: skip
    return fake.publish(Listing(PAID, "Paid plugin", tier="paid", versions={"2.0.0": package}, plans=[plan]))


def test_link_with_a_one_time_code(hub: FakeHub, admin: Client) -> None:
    web, headers = admin
    wrong = web.post("/api/v1/marketplace/link", json={"code": "WRONGCODE1"}, headers=headers)
    assert wrong.status_code == 404 and "not valid" in wrong.get_json()["detail"]
    right = web.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers)
    assert right.status_code == 200 and right.get_json()["data"]["account_name"] == "Ada's company"
    assert web.get("/api/v1/marketplace").get_json()["data"]["linked"]["account_name"] == "Ada's company"


def buy(web: FlaskClient, headers: dict[str, str], key: str = "press-0001-abcdefgh") -> Any:
    body = {"plugin_id": PAID, "plan_id": "plan-monthly", "idempotency_key": key}
    return web.post("/api/v1/marketplace/purchases", json=body, headers=headers)


def test_buy_with_the_saved_card_installs_at_once(hub: FakeHub, admin: Client) -> None:
    paid_listing(hub)
    web, headers = admin
    refused = buy(web, headers)
    assert refused.status_code == 409 and "Link this panel" in refused.get_json()["detail"]
    web.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers)
    billing = web.get("/api/v1/marketplace/billing").get_json()["data"]
    assert billing["linked"] and billing["purchases_allowed"] and billing["card"]["last4"] == "4242"
    assert billing["manage_url"].startswith("https://")
    answer = buy(web, headers)
    assert answer.status_code == 202
    data = answer.get_json()["data"]
    assert data["purchase"]["status"] == "succeeded" and data["purchase"]["method"] == "saved_card"
    assert data["purchase"]["receipt_number"] == "SR-000001"
    sent = next(iter(hub.purchases.values()))["requested_by"]  # who pressed Buy, for the receipt
    assert sent["email"] == "ada@example.com" and sent["name"]
    job = wait(data["job"]["id"])
    assert job.status == "success", "".join(job.log)
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["tier"] == "paid"
    assert rec["standing"] == "licensed" and rec["licence"]["grace_until"]  # dates from the signed lease
    listed = web.get("/api/v1/plugins").get_json()["data"][0]
    assert listed["licence"]["phase"] == "active" and listed["status"] == "active"
    # pressing again with the same key answers the same purchase: nothing is charged twice
    plugin_manager._RESTART_PENDING.clear()
    again = buy(web, headers)
    assert again.get_json()["data"]["purchase"]["id"] == data["purchase"]["id"]
    assert len(hub.receipts) == 1


def test_buy_through_checkout_then_install(hub: FakeHub, admin: Client) -> None:
    paid_listing(hub)
    hub.charge_saved_card = False
    web, headers = admin
    web.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers)
    assert web.get("/api/v1/marketplace/billing").get_json()["data"]["card"] is None
    answer = buy(web, headers)
    assert answer.status_code == 200
    purchase = answer.get_json()["data"]["purchase"]
    assert purchase["status"] == "checkout_required"
    assert purchase["checkout_url"].startswith("https://checkout.stripe.com/")
    # before paying, the hub does not hand out the package
    job = install(admin, PAID)
    assert job.status == "failed" and "no licence" in "".join(job.log)
    plugin_manager._RESTART_PENDING.clear()
    poll = f"/api/v1/marketplace/purchases/{purchase['id']}"
    assert web.get(poll).get_json()["data"]["status"] == "checkout_required"
    hub.complete_checkout(purchase["id"])
    paid = web.get(poll).get_json()["data"]
    assert paid["status"] == "succeeded" and paid["checkout_url"] is None
    # the next lease lists the licence even before the plugin is installed
    marketplace.heartbeat()
    lease = marketplace.lease()
    assert lease is not None and PAID in lease.licences and plugin_manager.record(PAID) is None
    assert install(admin, PAID).status == "success"
    history = web.get("/api/v1/marketplace/purchases").get_json()["data"]
    assert [(p["status"], p["receipt_number"]) for p in history] == [("succeeded", "SR-000001")]
    receipts = web.get("/api/v1/marketplace/receipts").get_json()["data"]
    assert receipts[0]["number"] == "SR-000001" and receipts[0]["total_cents"] == 500
    csv = web.get("/api/v1/marketplace/receipts?format=csv")
    assert csv.mimetype == "text/csv" and csv.text.splitlines()[0].startswith("number,kind,issued_at")
    assert web.get("/api/v1/marketplace/purchases?format=csv").text.startswith("created_at,plugin_name")


def test_a_purchase_needs_an_idempotency_key(hub: FakeHub, admin: Client) -> None:
    web, headers = admin
    body = {"plugin_id": PAID, "plan_id": "plan-monthly"}
    assert web.post("/api/v1/marketplace/purchases", json=body, headers=headers).status_code == 400


# ---------------------------------------------------------------- licences: expiry, grace, end, renewal


def _paid_installed(hub: FakeHub, admin: Client) -> dict[str, Any]:
    paid_listing(hub)
    web, headers = admin
    web.post("/api/v1/marketplace/link", json={"code": "LINKCODE42"}, headers=headers)
    hub.licences[PAID] = {"state": "active", "expires_at": int(time.time()) + 20 * 86400,
                          "grace_until": int(time.time()) + 27 * 86400}  # fmt: skip
    assert install(admin, PAID).status == "success"
    plugin_manager._RESTART_PENDING.clear()
    marketplace.heartbeat()
    plugin_manager.LOADED = {PAID}
    rec = plugin_manager.record(PAID)
    assert rec is not None
    return rec


def test_expiry_grace_and_end(hub: FakeHub, admin: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _paid_installed(hub, admin)
    expires, grace = rec["licence"]["expires_at"], rec["licence"]["grace_until"]
    assert plugin_manager.phase(rec, time.time(), True) == "active"
    assert plugin_manager.phase(rec, expires - 3 * 86400, True) == "expiring"
    assert plugin_manager.phase(rec, expires + 86400, True) == "grace"
    assert plugin_manager.phase(rec, grace + 1, True) == "ended"
    assert plugin_manager.allowed(rec, grace - 1, True) == (True, "ok")
    assert plugin_manager.allowed(rec, grace + 1, True) == (False, "licence_ended")
    assert plugin_manager.allowed(rec, time.time(), False) == (False, "no_lease")  # 7 days without a heartbeat

    mails: list[str] = []
    monkeypatch.setattr(plugin_manager, "_mail_super_admins", lambda subject, title, text: mails.append(subject))
    started: list[jobs.Job] = []

    def run_now(instance: str, action: str, kind: str, fn: Any, *args: Any, user: str = "system") -> jobs.Job:
        job = jobs.Job(instance, action, kind, user)
        fn(job, *args)
        started.append(job)
        return job

    def travel(to: float) -> None:
        """The panel and the hub at another time; the panel's heartbeat keeps its lease current."""
        monkeypatch.setattr(marketplace, "trusted_now", lambda: float(to))
        hub.now = float(to)
        marketplace.heartbeat()

    # 3 days before: a reminder, once
    travel(expires - 3 * 86400)
    plugin_manager.watch(start_job=run_now)
    plugin_manager.watch(start_job=run_now)
    assert mails == ["Paid plugin ends soon"]
    assert [n["kind"] for n in plugin_manager.notices()] == ["expiring"]
    # in the grace period: still running, a banner says when it stops
    travel(expires + 86400)
    plugin_manager.watch(start_job=run_now)
    assert not started and [n["kind"] for n in plugin_manager.notices()] == ["grace"]
    # the grace is over: back up, switch off (data kept), tell the super admins, restart
    travel(grace + 60)  # the hub's lease now says expired
    plugin_manager.watch(start_job=run_now)
    assert len(started) == 1 and started[0].kind == "plugin-expired"
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["switched_off"]["reason"] == "licence" and rec["enabled"] is True
    assert plugin_manager.folder(rec).exists()  # nothing deleted
    assert list(plugin_manager.panel_backups_dir().glob(f"panel__*__before-{PAID}-stops.zip"))
    assert mails[-1] == "Paid plugin was switched off"
    assert plugin_manager.restart_pending()
    assert [n["kind"] for n in plugin_manager.notices()] == ["ended"]
    plugin_manager.watch(start_job=run_now)
    assert len(started) == 1  # switched off once
    # renewed: the next lease says licensed again, the plugin comes back on by itself
    plugin_manager._RESTART_PENDING.clear()
    plugin_manager.LOADED = set()
    hub.licences[PAID] = {
        "state": "active",
        "expires_at": int(grace + 30 * 86400),
        "grace_until": int(grace + 37 * 86400),
    }
    travel(grace + 120)
    plugin_manager.watch(start_job=run_now)
    rec = plugin_manager.record(PAID)
    assert rec is not None and rec["switched_off"] is None
    assert mails[-1] == "Paid plugin is back on"
    assert plugin_manager.restart_pending()  # to load it again


def test_turning_the_clock_back_does_not_extend_a_licence(hub: FakeHub, admin: Client) -> None:
    _paid_installed(hub, admin)
    marketplace._save(high_water=time.time() + 400 * 86400)  # the panel saw a later time before
    assert marketplace.trusted_now() > time.time() + 399 * 86400
    rec = plugin_manager.record(PAID)
    assert rec is not None and plugin_manager.allowed(rec)[0] is False


def test_integrity_violation_switches_every_plugin_off(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_blocked", entry="hello-blocked")
    assert install(admin, FREE).status == "success"
    hub.heartbeat_refusal = "integrity_violation"
    with pytest.raises(HubRefused):
        marketplace.heartbeat()
    rec = plugin_manager.record(FREE)
    assert rec is not None and plugin_manager.allowed(rec) == (False, "blocked")
    assert plugin_manager.notices()[0]["kind"] == "integrity_violation"


def test_catalogue_marks_installed_plugins(hub: FakeHub, admin: Client) -> None:
    free_listing(hub, module="hello_catalogue", entry="hello-catalogue")
    paid_listing(hub)
    assert install(admin, FREE).status == "success"
    web, _ = admin
    items = web.get("/api/v1/marketplace/catalog?q=hello").get_json()["data"]
    assert [(i["id"], i["installed_version"]) for i in items] == [(FREE, "1.0.0")]
    actions = {i["id"]: i["action"] for i in web.get("/api/v1/marketplace/catalog").get_json()["data"]}
    assert actions[PAID] == "buy"
    detail = web.get(f"/api/v1/marketplace/catalog/{PAID}").get_json()["data"]
    assert detail["plans"][0]["id"] == "plan-monthly" and detail["permissions"] == ["network.outbound"]
    assert detail["installed_version"] is None
    assert web.get("/api/v1/marketplace/catalog?sort=wrong").status_code == 400
    assert web.get("/api/v1/marketplace/categories").get_json()["data"][0]["type"] == "mailer"


def test_b64url_round_trip() -> None:
    assert crypto.from_b64url(crypto.b64url(b"\xff\x00abc")) == b"\xff\x00abc"
    assert base64.urlsafe_b64decode(crypto.b64url(b"x") + "===") == b"x"
