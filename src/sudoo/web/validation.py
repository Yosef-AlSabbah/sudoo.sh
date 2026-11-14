"""Checking every value that comes from a browser or an API client before it is used.

Rules applied to all input (see docs/SECURITY.md):
    - a request that changes something must send a JSON object with Content-Type application/json
      (checked in security.py); a form posted from another site cannot do that
    - a value has the expected type: text is text, a switch is true or false, a number is a number
    - text is trimmed, limited in length and may not contain control characters (no NUL bytes, no new lines)
    - names, addresses and branches must match an allow-list pattern; nothing is "cleaned up" silently
Values are then only ever passed to commands as separate arguments, never through a shell (shell.py), and only
ever shown in the browser escaped (static/js/core.js, esc()).

Every check stops the request with 400 and a message that says what to enter instead.
"""

from __future__ import annotations

import re
from collections.abc import Container, Mapping
from pathlib import Path
from typing import Any

from flask import abort, request

from sudoo import accounts
from sudoo.instances import backups, store
from sudoo.repos import github

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MODULES_RE = re.compile(r"^[a-z0-9_]{1,64}(,[a-z0-9_]{1,64}){0,99}$")
SUBMODULE_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,100}$")
CUSTOM_NAME_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")


def body() -> dict[str, Any]:
    """The request's JSON object (security.py has already checked the Content-Type)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        abort(400, "The request must be a JSON object.")
    return data


def text(data: Mapping[str, Any], key: str, *, max_length: int = 200, default: str = "") -> str:
    """A trimmed text field; numbers are refused, missing or null gives `default`."""
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        abort(400, f"The field '{key}' must be text.")
    value = value.strip()
    if len(value) > max_length:
        abort(400, f"The field '{key}' is too long (at most {max_length} characters).")
    if _CONTROL.search(value):
        abort(400, f"The field '{key}' contains characters that are not allowed.")
    return value


def secret(data: Mapping[str, Any], key: str) -> str:
    """A password field: kept exactly as typed (spaces count), limited in length, never logged."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        abort(400, "Enter the password.")
    if len(value) > accounts.MAX_PASSWORD_LENGTH:
        abort(400, f"The password must be at most {accounts.MAX_PASSWORD_LENGTH} characters long.")
    return value


def flag(data: Mapping[str, Any], key: str, default: bool = False) -> bool:
    """A switch: true or false; missing means `default`."""
    value = data.get(key, default)
    if not isinstance(value, bool):
        abort(400, f"The field '{key}' must be true or false.")
    return value


def days(data: Mapping[str, Any], key: str, maximum: int = 3650) -> int:
    """A number of days sent as a JSON number: 0 (meaning "never") up to `maximum`."""
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        abort(400, f"The field '{key}' must be a whole number of days between 0 and {maximum}.")
    return value


def backup_file(value: str) -> Path:
    """The name of an existing backup file (never a path)."""
    path = backups.path_of(value)
    if path is None:
        abort(404, "This backup does not exist.")
    return path


def whole_number(value: str, name: str, minimum: int = 0, maximum: int = 10**9) -> int:
    """A whole number given as text (query parameters), within limits."""
    if not re.fullmatch(r"\d{1,10}", value or ""):
        abort(400, f"'{name}' must be a whole number.")
    number = int(value)
    if not minimum <= number <= maximum:
        abort(400, f"'{name}' must be between {minimum} and {maximum}.")
    return number


# --------------------------------------------------------------------------- domain values


def one_of(value: str, allowed: Container[str], message: str) -> str:
    if value not in allowed:
        abort(400, message)
    return value


def instance_name(value: str) -> str:
    if not store.NAME_RE.match(value or ""):
        abort(404, "This instance does not exist.")
    return value


def custom_name(value: str) -> str:
    """The optional name typed when creating an instance (turned into a technical name afterwards)."""
    if value and not CUSTOM_NAME_RE.match(value):
        abort(400, "The name may contain letters, numbers, spaces, dots, dashes and underscores (at most 40).")
    return value


def repo_address(value: str, required: bool = True) -> str:
    if not value and not required:
        return value
    if not github.ADDRESS_RE.match(value) or not github.repo_name(value):
        abort(400, "This is not a GitHub repository address. Example: https://github.com/company/repository")
    return value


def repo_reference(value: str) -> str:
    """A repository given as a GitHub address or as owner/repository."""
    if not github.repo_name(value):
        abort(400, "Enter the repository as owner/repository or as its GitHub address.")
    return value


def branch(value: str, required: bool = True) -> str:
    if not value and not required:
        return value
    if not github.valid_branch(value):
        abort(400, "This branch name is not valid.")
    return value


def module_list(value: str) -> list[str]:
    modules = value.replace(" ", "").strip(",")
    if not MODULES_RE.match(modules):
        abort(400, "Enter technical module names separated by commas, for example: sale_custom,stock_custom")
    return modules.split(",")


def submodule_path(value: str) -> str:
    path = value.strip("/")
    if not SUBMODULE_PATH_RE.match(path) or ".." in path.split("/") or "//" in path:
        abort(400, "The folder name may only contain letters, numbers, dashes, dots and slashes.")
    return path


def username(value: str) -> str:
    if not accounts.USERNAME_RE.match(value):
        abort(
            400,
            "User names are 3 to 32 characters: lower-case letters, digits, dots, dashes and underscores, "
            "starting with a letter.",
        )
    return value


PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*){2,6}$")
PLUGIN_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]{1,40})?(?:\+[0-9A-Za-z.-]{1,40})?$"
)
HUB_REFERENCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LINK_CODE_RE = re.compile(r"^[A-Za-z0-9-]{8,16}$")


def plugin_id(value: str) -> str:
    """A marketplace plugin id such as com.sudoo.smtp."""
    if len(value) > 128 or not PLUGIN_ID_RE.match(value):
        abort(400, "Give a plugin id such as com.sudoo.smtp.")
    return value


def plugin_version(value: str) -> str:
    if len(value) > 64 or not PLUGIN_VERSION_RE.match(value):
        abort(400, "Give a version such as 1.2.0.")
    return value


def hub_reference(value: str, what: str) -> str:
    """An id the hub gave (plan, purchase): letters, digits, - and _ only."""
    if not HUB_REFERENCE_RE.match(value):
        abort(400, f"The {what} is not valid.")
    return value


def link_code(value: str) -> str:
    """The one-time code from app.sudoo.sh (Servers, Link a server)."""
    if not LINK_CODE_RE.match(value):
        abort(400, "Enter the code shown on app.sudoo.sh (letters and digits).")
    return value


def idempotency_key(value: str) -> str:
    """Made once per press of Buy and sent again unchanged on a retry: 16 to 64 of A-Z, a-z, 0-9, _ and -."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", value):
        abort(400, "The purchase needs an idempotency_key: 16 to 64 letters, digits, - and _.")
    return value
