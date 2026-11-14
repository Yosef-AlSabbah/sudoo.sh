"""Test setup: every test session gets its own empty ODOO_ROOT and documentation folder, so nothing touches a real
server, and the panel's background work (Docker, monitor, connectors) is never started."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(tempfile.mkdtemp(prefix="sudoo-test-"))
(ROOT / "manager").mkdir()
DOCS = ROOT / "documentation"
DOCS.mkdir()
shutil.copy(REPO / "README.md", DOCS)
shutil.copytree(REPO / "docs", DOCS / "docs")

# settings are read when sudoo.config is first imported, so the environment is set before that
os.environ.update(
    ODOO_ROOT=str(ROOT),
    DOCS_DIR=str(DOCS),
    ODOO_VERSIONS="18.0,19.0,20.0",
    ENTERPRISE_SOURCE="none",
    REQUIRE_SECOND_FACTOR="none",  # test_auth.py turns it on where it is tested
)

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from sudoo import accounts, background, plugin_manager  # noqa: E402

RESTARTS: list[float] = []
# the backend is never really stopped in tests: a plugin change only records that it would restart
plugin_manager.stop_backend = lambda: RESTARTS.append(1.0)

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture(scope="session")
def app() -> Flask:
    background.start = lambda: None  # no Docker, monitor or connectors in tests
    from sudoo.web import create_app
    from sudoo.web.v1 import stream

    stream.start = lambda app: None  # the live event stream is tested on its own (test_events.py)

    application = create_app()
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    return application


@pytest.fixture(scope="session")
def passwords() -> dict[str, str]:
    """One super admin and one developer, created once with passwords they chose (so no change is asked for)."""
    chosen = {"admin": "plum-river-lantern-42", "operator": "copper-meadow-violin-17"}
    accounts.create("admin1", "super_admin", chosen["admin"], first_name="Ada", email="ada@example.com")
    accounts.create("sync1", "developer", chosen["operator"])
    return chosen


def sign_in(app: Flask, name: str, password: str) -> tuple[FlaskClient, dict[str, str]]:
    """A client signed in through the API, and the headers a change needs (Origin, CSRF token)."""
    client = app.test_client()
    answer = client.post("/api/v1/session", json={"username": name, "password": password}, headers=ORIGIN)
    assert answer.status_code == 201, answer.get_json()
    return client, {**ORIGIN, "X-CSRF-Token": answer.get_json()["data"]["csrf_token"]}


def _signed_in(app: Flask, name: str, password: str) -> Iterator[tuple[FlaskClient, dict[str, str]]]:
    yield sign_in(app, name, password)


@pytest.fixture
def admin(app: Flask, passwords: dict[str, str]) -> Iterator[tuple[FlaskClient, dict[str, str]]]:
    """A client signed in as administrator, and the headers a change needs (Origin, CSRF token)."""
    yield from _signed_in(app, "admin1", passwords["admin"])


@pytest.fixture
def operator(app: Flask, passwords: dict[str, str]) -> Iterator[tuple[FlaskClient, dict[str, str]]]:
    yield from _signed_in(app, "sync1", passwords["operator"])
