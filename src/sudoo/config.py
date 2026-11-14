"""Every setting of the panel, typed and documented in one place.

Values come from environment variables (the panel's `.env` file, passed in by Docker Compose). Names are case
insensitive: the field `idle_hours` is set with `IDLE_HOURS=6`. A wrong value (for example `IDLE_HOURS=soon`) stops
the panel at start-up with a message naming the setting, instead of failing later.

The settings that choose plugins (`exposure`, `enterprise_source`) name an entry point; see plugins.py and
docs/PLUGINS.md.

Almost every setting can also be changed in the panel (Settings page, or PATCH /api/v1/settings): those in
EDITABLE take effect at once, those in RESTART (they choose plugins) when the panel restarts. The changes are kept in
<ODOO_ROOT>/manager/settings.json on top of `.env`, secrets encrypted; removing a change brings back the `.env`
value. Where things are and how they are reached (folders, ports, exposure, storage) is set in `.env` only, because
the web service and the containers read it too.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """The panel's configuration. See .env.example for every setting with an explanation."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    # ------------------------------------------------------------------ locations
    odoo_root: Path = Field(Path("/opt/odoo"), description="Folder that holds instances, backups and panel data.")
    docs_dir: Path = Field(
        PACKAGE_DIR.parent.parent / "documentation", description="README.md and docs/ shown in the panel."
    )
    memory_dir: Path = Field(Path("/dev/shm"), description="Memory-backed folder for secrets needed briefly as files.")

    # ------------------------------------------------------------------ Odoo
    odoo_image: str = Field("odoo", description="Docker image of Odoo; the tag is the Odoo version.")
    odoo_versions: str = Field(
        "auto",
        description='Versions offered: "auto" (every published version of the official image from odoo_min_version) '
        "or a comma-separated list such as 17.0,18.0,saas-18.2.",
    )
    odoo_min_version: str = Field("16.0", description='Oldest version offered when odoo_versions is "auto".')
    postgres_image: str = Field("postgres:16", description="Docker image of each instance's database.")
    odoo_admin_password: str = Field("admin", description='Password of the Odoo user "admin" in new instances.')

    # ------------------------------------------------------------------ Enterprise add-ons (plugin: enterprise_source)
    enterprise_source: str = Field(
        "folder", description='Where Enterprise add-ons come from: "folder", "git" or "none".'
    )
    enterprise_path: str = Field(
        "/opt/odoo/enterprise/{version}",
        description="folder source: where the add-ons of a version are; {version} (19.0) and {major} (19) are replaced.",
    )
    enterprise_git_url: str = Field("", description="git source: repository holding one branch per Odoo version.")
    enterprise_git_branch: str = Field("{version}", description="git source: branch name of a version, e.g. {version}.")
    enterprise_marker: str = Field("web_enterprise", description="Module whose presence proves the add-ons are there.")

    # ------------------------------------------------------------------ exposure (plugin: exposure)
    exposure: str = Field(
        "cloudflare-quick", description='How instances are reached: "cloudflare-quick" or "host-ports".'
    )
    cloudflared_image: str = Field("cloudflare/cloudflared:latest", description="cloudflare-quick: connector image.")
    connector_prefix: str = Field("sudoo-connector-", description="cloudflare-quick: container name prefix.")
    connector_status_port_start: int = Field(20300, description="cloudflare-quick: first status port of a connector.")
    panel_connector_status_port: int = Field(20242, description="cloudflare-quick: status port of the panel connector.")
    public_host: str = Field("", description="host-ports: the server's public name or address.")
    public_scheme: Literal["http", "https"] = Field("http", description="host-ports: scheme of the public addresses.")

    # ------------------------------------------------------------------ update triggers (plugins)
    update_triggers: str = Field(
        "polling", description='What starts code updates, comma-separated: "polling", "github-webhook" or both.'
    )
    github_webhook_secret: str = Field(
        "", description="github-webhook: the secret entered on GitHub (20 or more random characters)."
    )

    # ------------------------------------------------------------------ storage, sign-in, mail (plugins)
    storage: str = Field("sqlite", description='Where the panel keeps its own data: "sqlite".')
    auth: str = Field("local", description='How user names and passwords are checked: "local" (the panel\'s accounts).')
    second_factors: str = Field(
        "email,totp", description='Second factors offered at sign-in, comma-separated: "email", "totp" or both.'
    )
    require_second_factor: Literal["none", "admins", "everyone"] = Field(
        "admins", description='Who must use a second factor: "none", "admins" or "everyone".'
    )
    mailer: str = Field("smtp", description='How the panel sends e-mail: "smtp" or "none".')
    mail_from: str = Field("", description="Sender of the panel's e-mails, e.g. Sudoo.sh <no-reply@example.com>.")
    smtp_host: str = Field("", description="smtp: the mail server; empty: no e-mail (and no e-mail codes).")
    smtp_port: int = Field(587, description="smtp: port (587 for STARTTLS, 465 for SSL).")
    smtp_security: Literal["starttls", "ssl", "none"] = Field("starttls", description="smtp: encryption.")
    smtp_username: str = Field("", description="smtp: user name, usually the full e-mail address.")
    smtp_password: str = Field("", description="smtp: password or app password.")
    mail_templates_dir: str = Field("", description="Folder with e-mail templates that replace the built-in ones.")
    brand_color: str = Field(
        "#714B67", pattern=r"^#[0-9A-Fa-f]{6}$", description="Accent colour of e-mails, as #RRGGBB."
    )

    # ------------------------------------------------------------------ limits
    rate_limiter: str = Field("memory", description='Where request counts are kept: "memory".')
    rate_limit_reads_per_minute: int = Field(
        600, ge=0, description="Requests that read, per minute, per signed-in user or address; 0: no limit."
    )
    rate_limit_changes_per_minute: int = Field(
        60, ge=0, description="Requests that change something, per minute, per user or address; 0: no limit."
    )
    max_instances: int = Field(0, ge=0, description="Instances on this server at most; 0: no limit.")
    max_instances_per_user: int = Field(0, ge=0, description="Instances one user (or API token) may own; 0: no limit.")
    create_cooldown_minutes: float = Field(
        0, ge=0, description="Minutes a user must wait between two creations; 0: no wait."
    )

    # ------------------------------------------------------------------ ports
    panel_port: int = Field(9000, description="Port of the panel: the web service (sudoo-web) listens here.")
    api_port: int = Field(9002, description="Port of the backend (127.0.0.1 only); the web service forwards to it.")
    events_port: int = Field(9001, description="Port of the live event stream (127.0.0.1 only).")
    gateway_port_start: int = Field(8069, description="First gateway port (one per instance).")
    odoo_port_start: int = Field(28069, description="First Odoo port (one per instance, 127.0.0.1 only).")

    # ------------------------------------------------------------------ behaviour
    idle_hours: float = Field(6, ge=0, description="Pause an instance after this many hours without visits; 0: never.")
    auto_pause: bool = Field(True, description="New instances pause when idle (each instance can change it).")
    auto_update: bool = Field(True, description="New instances get new code automatically.")
    auto_upgrade: bool = Field(True, description="New instances upgrade changed modules after an update.")
    delete_after_days: int = Field(30, ge=0, description="Lifetime offered for new instances, in days; 0: keep.")
    poll_minutes: float = Field(2, gt=0, description="polling: check GitHub for new commits this often.")
    session_idle_minutes: float = Field(60, gt=0, description="Panel sign-out after this long without activity.")
    session_max_hours: float = Field(12, gt=0, description="Longest panel session.")
    admin_contact_name: str = Field("the administrator", description="Who users are told to contact.")
    admin_contact_phone: str = ""
    admin_contact_email: str = ""

    metrics_interval_seconds: float = Field(
        5, ge=2, le=60, description="Seconds between two measurements of the server and the instances."
    )
    daily_backups: bool = Field(
        True,
        description="Back up every instance that was used since its last daily backup, once a day; each keeps only "
        "its latest daily backup.",
    )
    daily_backup_time: str = Field(
        "00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="When the daily backups run (HH:MM, 24 hours)."
    )
    timezone: str = Field("UTC", description="Time zone of the daily backup time, for example Africa/Cairo.")

    # ------------------------------------------------------------------ marketplace (docs/MARKETPLACE.md)
    marketplace: bool = Field(
        True,
        description="Use the Sudoo.sh marketplace: register with the hub, send a signed heartbeat every 6 hours, "
        "install plugins. Off: the panel never contacts the hub; installed free plugins keep working.",
    )
    hub_url: str = Field(
        "https://hub.sudoo.sh",
        description="Address of the Sudoo.sh hub (https; http only for localhost while testing).",
    )

    @field_validator("hub_url")
    @classmethod
    def _hub_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(value.strip())
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme not in ("https", "http") or not parts.hostname or (parts.scheme == "http" and not local):
            raise ValueError("must be an https:// address (http:// only for localhost)")
        if parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError("must be a plain address such as https://hub.sudoo.sh")
        return value.strip().rstrip("/")

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("unknown time zone; use a name such as UTC or Africa/Cairo") from error
        return value

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    # ------------------------------------------------------------------ fixed intervals (not settings)
    pause_check_interval_seconds: int = 120
    expiry_check_interval_seconds: int = 600
    history_samples: int = 120  # the previous pages' short history (instances/monitor.py)

    # ------------------------------------------------------------------ derived locations
    @property
    def instances_dir(self) -> Path:
        return self.odoo_root / "instances"

    @property
    def backups_dir(self) -> Path:
        return self.odoo_root / "backups"

    @property
    def manager_dir(self) -> Path:
        return self.odoo_root / "manager"

    @property
    def keys_dir(self) -> Path:
        return self.manager_dir / "keys"

    @property
    def deploy_keys_dir(self) -> Path:
        """One read-only GitHub deploy key per repository."""
        return self.keys_dir / "deploy"

    @property
    def secret_file(self) -> Path:
        """Signs session cookies."""
        return self.manager_dir / "secret_key"

    @property
    def vault_key_file(self) -> Path:
        """Encrypts stored secrets and peppers password hashes (core/vault.py)."""
        return self.manager_dir / "vault.key"

    @property
    def admin_contact(self) -> dict[str, str]:
        return {"name": self.admin_contact_name, "phone": self.admin_contact_phone, "email": self.admin_contact_email}

    def contact_sentence(self) -> str:
        """'Please contact the administrator, <name> (<phone>, <email>).' for messages shown to sync operators."""
        details = ", ".join(value for value in (self.admin_contact_phone, self.admin_contact_email) if value)
        who = "the administrator"
        if self.admin_contact_name and self.admin_contact_name.lower() != who:
            who += f", {self.admin_contact_name}"
        return f"Please contact {who}" + (f" ({details})." if details else ".")


# ---------------------------------------------------------------------- changes made in the panel

EDITABLE = (
    # take effect at once
    "brand_color",
    "require_second_factor",
    "session_idle_minutes",
    "session_max_hours",
    "rate_limit_reads_per_minute",
    "rate_limit_changes_per_minute",
    "max_instances",
    "max_instances_per_user",
    "create_cooldown_minutes",
    "idle_hours",
    "auto_pause",
    "auto_update",
    "auto_upgrade",
    "delete_after_days",
    "poll_minutes",
    "metrics_interval_seconds",
    "daily_backups",
    "daily_backup_time",
    "timezone",
    "odoo_versions",
    "odoo_min_version",
    "odoo_image",
    "postgres_image",
    "odoo_admin_password",
    "enterprise_path",
    "enterprise_git_url",
    "enterprise_git_branch",
    "enterprise_marker",
    "github_webhook_secret",
    "mail_from",
    "smtp_host",
    "smtp_port",
    "smtp_security",
    "smtp_username",
    "smtp_password",
    "mail_templates_dir",
    "cloudflared_image",
    "admin_contact_name",
    "admin_contact_phone",
    "admin_contact_email",
    "marketplace",
)
"""Settings that can be changed in the panel, taking effect at once."""

RESTART = ("mailer", "second_factors", "update_triggers", "enterprise_source", "auth", "rate_limiter")
"""Settings that can be changed in the panel and take effect when the panel restarts (they choose plugins)."""

SECRET = ("odoo_admin_password", "github_webhook_secret", "smtp_password")
"""Settings whose value is never shown, only whether they are set; kept encrypted in settings.json."""

_CHANGEABLE = frozenset(EDITABLE + RESTART)


class LiveSettings:
    """The current settings: `.env`, with the changes made in the panel on top.

    Reading an attribute gives the current value, so code that keeps a reference (plugins get it in their
    constructor) sees changes at once. Each change builds a new, validated, frozen Settings object. Secrets are
    stored encrypted with the vault key and decrypted when first read (the vault itself needs these settings to
    find its key, so it cannot be used while they load).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._env = Settings()
        self._overrides: dict[str, Any] = {}
        self._encrypted: dict[str, str] = {}
        self._current = self._env
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        try:
            saved = json.loads(self._file.read_text())
            self._encrypted = {
                k: v["encrypted"] for k, v in saved.items() if k in SECRET and isinstance(v, dict) and "encrypted" in v
            }
            plain = {k: v for k, v in saved.items() if k in _CHANGEABLE and k not in self._encrypted}
            self._current = Settings(**plain)
            self._overrides = {k: getattr(self._current, k) for k in plain}
        except (OSError, ValueError):
            pass  # no changes yet, or an unreadable file: .env alone
        self._started = self._current  # what the plugins were created with

    def __getattr__(self, name: str) -> Any:
        if name in SECRET and self._encrypted:
            self._decrypt_secrets()
        return getattr(self._current, name)

    def _decrypt_secrets(self) -> None:
        from sudoo.core import vault

        with self._lock:
            if not self._encrypted:
                return
            plain = {k: vault.decrypt(v, f"setting:{k}") for k, v in self._encrypted.items()}
            self._encrypted = {}
            self._overrides.update(plain)
            self._current = Settings(**self._overrides)

    @property
    def _file(self) -> Path:
        return self._env.manager_dir / "settings.json"

    @property
    def env(self) -> Settings:
        """The values from `.env` alone."""
        return self._env

    def overrides(self) -> dict[str, Any]:
        """The settings changed in the panel, with their values."""
        self._decrypt_secrets()
        return dict(self._overrides)

    def pending_restart(self, name: str) -> bool:
        """True when a setting that applies at restart was changed since the panel started."""
        return name in RESTART and getattr(self._current, name) != getattr(self._started, name)

    def change(self, values: Mapping[str, Any]) -> None:
        """Change settings (None removes a change). Raises ValueError, naming the setting, when a value is not
        valid or the setting can only be set in .env."""
        refused = sorted(set(values) - _CHANGEABLE)
        if refused:
            raise ValueError(f"These settings can only be changed in .env: {', '.join(refused)}.")
        self._decrypt_secrets()
        from sudoo.core import vault

        with self._lock:
            overrides = {**self._overrides, **values}
            overrides = {k: v for k, v in overrides.items() if v is not None}
            current = Settings(**overrides)  # pydantic.ValidationError is a ValueError
            self._overrides = {k: getattr(current, k) for k in overrides}
            self._current = current
            stored = {
                k: {"encrypted": vault.encrypt(str(v), f"setting:{k}")} if k in SECRET else v
                for k, v in self._overrides.items()
            }
            vault.write_private(self._file, json.dumps(stored, indent=1))
        for listener in self._listeners:
            listener(dict(values))

    def on_change(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Call `listener(changed values)` after every change."""
        self._listeners.append(listener)


live = LiveSettings()
settings = cast(Settings, live)
"""The current settings. Typed as Settings: everything else in the panel reads it like a Settings object."""
