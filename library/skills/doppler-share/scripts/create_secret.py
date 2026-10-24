#!/usr/bin/env python3
"""
Create a Doppler Share one-time secret link (reverse of retrieve_secret.py).

Mirrors the browser flow exactly:
1. GET https://share.doppler.com/ -> session cookie + CSRF token
2. Client-side: random 64-char password, PBKDF2-SHA256 (1M rounds) -> AES-256-GCM encrypt
3. POST /send as JSON with encrypted_secret, hashed_password (SHA256 of password),
   encryption_kdf=pbkdf2, encryption_salt_rounds, expire_views, expire_days, _csrf
4. Response contains the slug; full link = https://share.doppler.com/s/<slug>#<password>
   (the #password fragment never leaves the client / is never sent to the server)

Usage:
  python create_secret.py --stdin                 # read secret from stdin
  python create_secret.py --secret "value"        # pass inline (avoid for real secrets)
  python create_secret.py --stdin --views 1 --days 1
"""

import sys
import re
import json
import base64
import hashlib
import secrets
import argparse
import urllib.request
import http.cookiejar

SALT_ROUNDS = 1_000_000
PASSWORD_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def encrypt_secret(plaintext: str):
    """Mirror of window.CryptoLib.encrypt(). Returns (encrypted_b64, password, hashed_password)."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(64))
    hashed_password = hashlib.sha256(password.encode()).hexdigest()

    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=SALT_ROUNDS)
    key = kdf.derive(password.encode())

    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
    ct, tag = ct_with_tag[:-16], ct_with_tag[-16:]

    # Layout matches decrypt: salt(16) + iv(12) + authTag(16) + ciphertext
    buf = salt + iv + tag + ct
    return base64.b64encode(buf).decode(), password, hashed_password


def create_share_link(secret: str, expire_views: int = 1, expire_days: int = 1) -> str:
    encrypted_b64, password, hashed_password = encrypt_secret(secret)

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    req = urllib.request.Request(
        "https://share.doppler.com/",
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with opener.open(req) as r:
        page_html = r.read().decode()

    csrf_match = re.search(r'"csrf":"([^"]+)"', page_html)
    if not csrf_match:
        raise RuntimeError("Could not find CSRF token on page")
    csrf_token = csrf_match.group(1)

    body = json.dumps({
        "encrypted_secret": encrypted_b64,
        "hashed_password": hashed_password,
        "encryption_kdf": "pbkdf2",
        "encryption_salt_rounds": str(SALT_ROUNDS),
        "expire_views": str(expire_views),
        "expire_days": str(expire_days),
        "_csrf": csrf_token,
    }).encode()

    req2 = urllib.request.Request(
        "https://share.doppler.com/send",
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Referer": "https://share.doppler.com/",
        }
    )
    with opener.open(req2) as r:
        payload = json.loads(r.read().decode())

    if "link" not in payload:
        raise RuntimeError(f"Doppler Share create failed: {payload}")

    return f"{payload['link']}#{password}"


def main():
    parser = argparse.ArgumentParser(description="Create a Doppler Share one-time secret link")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--stdin", action="store_true", help="Read secret from stdin")
    src.add_argument("--secret", help="Secret value inline (avoid for real secrets)")
    parser.add_argument("--views", type=int, default=1, help="Expire after N views (default 1)")
    parser.add_argument("--days", type=int, default=1, help="Expire after N days (default 1)")
    args = parser.parse_args()

    secret = sys.stdin.read().strip() if args.stdin else args.secret
    if not secret:
        print("Empty secret, refusing.", file=sys.stderr)
        sys.exit(1)

    link = create_share_link(secret, expire_views=args.views, expire_days=args.days)
    print(link)


if __name__ == "__main__":
    main()
