"""The cryptography the panel shares with the hub (hub.sudoo.sh): signed requests, package signatures and leases.

Signed requests
    Every request to the hub that needs to say which panel sends it carries X-Sudoo-Installation, X-Sudoo-Timestamp,
    X-Sudoo-Nonce and X-Sudoo-Signature, the base64url Ed25519 signature (installation key) of these lines:

        sudoo-hub-request-v1
        <METHOD>
        <path, with ?query when there is one>
        <installation id>
        <timestamp>
        <nonce>
        <SHA-256 of the body, hex>

Package signatures
    The hub signs "sudoo-plugin-v1\\n<plugin id>\\n<version>\\n<sha256 of the package>" with its Ed25519 key, so a
    signature binds one package to one plugin and one version (an old release cannot be passed off as an update).

Leases
    A heartbeat answers with a lease: a JWT signed by the hub key (alg EdDSA, kid = key id), for this installation
    (aud "sudoo-panel:<id>"), valid 7 days. It says the standing of each reported plugin and the licence dates of
    the paid ones. Only the signed claims are trusted, never the plain JSON next to it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

REQUEST_DOMAIN = "sudoo-hub-request-v1"
PACKAGE_DOMAIN = b"sudoo-plugin-v1"
LEASE_TYPE = "sudoo-lease+jwt"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LeaseError(ValueError):
    """The lease is not valid: wrong signature, wrong installation, expired, or not a lease at all."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def from_b64url(text: str) -> bytes:
    """Decode base64url with or without padding; ValueError when it is not base64url."""
    if not text or not re.fullmatch(r"[A-Za-z0-9_=-]+", text):
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as error:
        raise ValueError("not base64url") from error


def public_key_b64url(key: Ed25519PublicKey) -> str:
    return b64url(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def public_key_from_b64url(text: str) -> Ed25519PublicKey:
    raw = from_b64url(text)
    if len(raw) != 32:
        raise ValueError("an Ed25519 public key is 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def key_id(key: Ed25519PublicKey) -> str:
    """The hub's name for a public key: the first 16 hex digits of the SHA-256 of its raw bytes."""
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def private_key_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def verify(key: Ed25519PublicKey, signature: bytes, message: bytes) -> bool:
    if len(signature) != 64:
        return False
    try:
        key.verify(signature, message)
    except InvalidSignature:
        return False
    return True


# ---------------------------------------------------------------- signed requests


def request_message(
    method: str, path_with_query: str, installation_id: str, timestamp: int, nonce: str, body: bytes
) -> bytes:
    lines = (
        REQUEST_DOMAIN,
        method.upper(),
        path_with_query,
        installation_id,
        str(timestamp),
        nonce,
        hashlib.sha256(body).hexdigest(),
    )
    return "\n".join(lines).encode()


def signed_headers(
    key: Ed25519PrivateKey, installation_id: str, method: str, path_with_query: str, body: bytes, timestamp: int
) -> dict[str, str]:
    """The four headers that prove this panel sent the request (a new nonce every time)."""
    nonce = secrets.token_urlsafe(24)
    signature = key.sign(request_message(method, path_with_query, installation_id, timestamp, nonce, body))
    return {
        "X-Sudoo-Installation": installation_id,
        "X-Sudoo-Timestamp": str(timestamp),
        "X-Sudoo-Nonce": nonce,
        "X-Sudoo-Signature": b64url(signature),
    }


# ---------------------------------------------------------------- packages


def package_statement(plugin_id: str, version: str, sha256: str) -> bytes:
    """What the hub signs for a package (the same format as hub.signing.signing_message)."""
    if not SHA256_RE.match(sha256):
        raise ValueError("sha256 must be 64 lower-case hex digits")
    if not plugin_id or not version or any(c in plugin_id + version for c in "\n\r\0"):
        raise ValueError("plugin id and version must be single-line and not empty")
    return b"\n".join((PACKAGE_DOMAIN, plugin_id.encode(), version.encode(), sha256.encode()))


def verify_package(key: Ed25519PublicKey, plugin_id: str, version: str, sha256: str, signature: str) -> bool:
    """True only when `signature` is the hub's signature of a package with this SHA-256 as this plugin and
    version."""
    try:
        raw = from_b64url(signature)
        message = package_statement(plugin_id, version, sha256)
    except ValueError:
        return False
    return verify(key, raw, message)


# ---------------------------------------------------------------- leases


@dataclass(frozen=True)
class Lease:
    token: str
    claims: dict[str, Any]

    @property
    def issued_at(self) -> int:
        return int(self.claims["iat"])

    @property
    def expires_at(self) -> int:
        return int(self.claims["exp"])

    @property
    def plugins(self) -> dict[str, str]:
        """Standing of each reported plugin: free, licensed, grace, expired, unlicensed or unknown."""
        value = self.claims.get("plugins") or {}
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    @property
    def licences(self) -> dict[str, dict[str, Any]]:
        """For each paid plugin with a licence: {"state", "expires_at", "grace_until"} (Unix seconds or None)."""
        value = self.claims.get("licenses") or {}
        if not isinstance(value, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for plugin_id, item in value.items():
            if isinstance(item, dict):
                result[str(plugin_id)] = {
                    "state": str(item.get("state") or ""),
                    "expires_at": _int_or_none(item.get("expires_at")),
                    "grace_until": _int_or_none(item.get("grace_until")),
                }
        return result


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def read_lease(token: str, keys: dict[str, Ed25519PublicKey], issuer: str, installation_id: str, now: float) -> Lease:
    """Verify a lease with the pinned hub keys (by kid) and check what it is for; raises LeaseError."""
    parts = token.split(".")
    if len(parts) != 3:
        raise LeaseError("not a JWT")
    try:
        header = json.loads(from_b64url(parts[0]))
        claims = json.loads(from_b64url(parts[1]))
        signature = from_b64url(parts[2])
    except ValueError as error:
        raise LeaseError("not a JWT") from error
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise LeaseError("not a JWT")
    if header.get("alg") != "EdDSA":  # never "none", never an HMAC algorithm with the public key as secret
        raise LeaseError("the lease is not signed with Ed25519")
    if header.get("typ") not in (None, LEASE_TYPE):
        raise LeaseError("not a lease")
    key = keys.get(str(header.get("kid")))
    if key is None:
        raise LeaseError("the lease is signed with a key this panel does not trust")
    if not verify(key, signature, f"{parts[0]}.{parts[1]}".encode()):
        raise LeaseError("the lease signature is not valid")
    for claim in ("iat", "exp", "iss", "aud", "sub"):
        if claim not in claims:
            raise LeaseError(f"the lease has no {claim}")
    if str(claims["iss"]).rstrip("/") != issuer.rstrip("/"):
        raise LeaseError("the lease comes from another hub")
    audience = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    if f"sudoo-panel:{installation_id}" not in audience or str(claims["sub"]) != installation_id:
        raise LeaseError("the lease is for another installation")
    try:
        expires, not_before = float(claims["exp"]), float(claims["nbf"] if "nbf" in claims else claims["iat"])
    except (TypeError, ValueError) as error:
        raise LeaseError("the lease has wrong dates") from error
    if expires <= now:
        raise LeaseError("the lease has expired")
    if not_before > now + 300:
        raise LeaseError("the lease is not valid yet (check the server's clock)")
    return Lease(token, claims)
