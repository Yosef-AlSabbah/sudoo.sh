"""Settings: defaults, validation and derived values."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sudoo.config import Settings


def test_defaults_are_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ENTERPRISE_SOURCE", "EXPOSURE"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(odoo_root=Path("/srv/x"))
    assert settings.exposure == "cloudflare-quick"
    assert settings.enterprise_source == "folder"
    assert settings.instances_dir == Path("/srv/x/instances")
    assert settings.vault_key_file == Path("/srv/x/manager/vault.key")


def test_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDLE_HOURS", "3")
    monkeypatch.setenv("EXPOSURE", "host-ports")
    settings = Settings()
    assert settings.idle_hours == 3
    assert settings.exposure == "host-ports"


@pytest.mark.parametrize(("name", "value"), [("idle_hours", "soon"), ("delete_after_days", -1), ("poll_minutes", 0)])
def test_wrong_values_are_refused(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{name: value})


def test_contact_sentence() -> None:
    settings = Settings(admin_contact_name="Sam", admin_contact_email="sam@example.com")
    assert settings.contact_sentence() == "Please contact the administrator, Sam (sam@example.com)."


def test_every_setting_is_documented() -> None:
    """docs/CONFIGURATION.md lists every setting an administrator can change."""
    fixed = {
        "pause_check_interval_seconds",
        "expiry_check_interval_seconds",
        "history_samples",
    }
    documented = (Path(__file__).resolve().parent.parent / "docs" / "CONFIGURATION.md").read_text()
    missing = [name for name in Settings.model_fields if name not in fixed and f"`{name.upper()}`" not in documented]
    assert not missing


def test_every_setting_is_in_the_env_template() -> None:
    """.env.example names every setting (as NAME=value, or commented out for the rarely changed ones)."""
    import re

    fixed = {"pause_check_interval_seconds", "expiry_check_interval_seconds", "history_samples"}
    template = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
    missing = [
        name
        for name in Settings.model_fields
        if name not in fixed and not re.search(rf"^(# )?{name.upper()}=", template, re.MULTILINE)
    ]
    assert not missing


def test_hub_url_must_be_https() -> None:
    assert Settings(hub_url="https://hub.example.com/").hub_url == "https://hub.example.com"
    assert Settings(hub_url="http://127.0.0.1:8000").hub_url == "http://127.0.0.1:8000"
    for wrong in ("http://hub.example.com", "ftp://hub.example.com", "https://hub.example.com/?x=1"):
        with pytest.raises(ValidationError):
            Settings(hub_url=wrong)


def test_contact_sentence_without_a_name() -> None:
    assert Settings().contact_sentence() == "Please contact the administrator."
