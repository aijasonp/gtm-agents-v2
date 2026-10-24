"""Offline license files: Ed25519-signed JSON with an expiry. No phone-home.

When a license lapses the agents keep running; `gtm update` refuses new releases
and the self-test reports the lapse.
"""
from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

# Vendor public key, baked into each release. Replace with your own via `gtm-license keygen`.
PUBLIC_KEY_PATH = Path(__file__).with_name("license_pub.pem")


def keygen(out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    priv = out / "license_priv.pem"
    pub = out / "license_pub.pem"
    priv.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo))
    return priv, pub


def _canonical(claims: dict) -> bytes:
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()


def issue(private_key_pem: bytes, customer: str, agents: list[str], expires: str) -> dict:
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    claims = {"customer": customer, "agents": sorted(agents), "expires": expires}
    return {**claims, "signature": base64.b64encode(key.sign(_canonical(claims))).decode()}


def verify(lic: dict, public_key_pem: bytes | None = None, today: date | None = None) -> dict:
    """Returns {"valid": bool, "expired": bool, "agents": [...], "reason": str}."""
    pem = public_key_pem or (PUBLIC_KEY_PATH.read_bytes() if PUBLIC_KEY_PATH.exists() else None)
    if pem is None:
        return {"valid": False, "expired": False, "agents": [], "reason": "no vendor public key in this build"}
    claims = {k: lic.get(k) for k in ("customer", "agents", "expires")}
    try:
        pub: Ed25519PublicKey = serialization.load_pem_public_key(pem)
        pub.verify(base64.b64decode(lic.get("signature", "")), _canonical(claims))
    except (InvalidSignature, ValueError, TypeError):
        return {"valid": False, "expired": False, "agents": [], "reason": "signature check failed"}
    expired = date.fromisoformat(claims["expires"]) < (today or date.today())
    return {"valid": True, "expired": expired, "agents": claims["agents"],
            "reason": "expired: agents keep running, updates and support paused" if expired else "ok"}


def load_and_verify(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"valid": False, "expired": False, "agents": [], "reason": f"no license file at {p}"}
    return verify(json.loads(p.read_text()))
