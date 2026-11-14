"""The connection to the Sudoo.sh hub (hub.sudoo.sh): identity, signed requests, heartbeat and lease, linking,
the catalogue and purchases. See docs/MARKETPLACE.md.

    crypto.py        signed requests, package signatures, lease verification (the formats the hub uses)
    client.py        this installation's identity (Ed25519 key, encrypted with the vault) and HTTP calls
    marketplace.py   registration, heartbeat, lease, linking, catalogue, purchases, status
"""

from .client import HubRefused, HubUnavailable

__all__ = ["HubRefused", "HubUnavailable"]
