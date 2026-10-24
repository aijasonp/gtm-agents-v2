#!/usr/bin/env python3
"""
Retrieve and decrypt a Doppler Share secret from a share URL.

Usage:
  python retrieve_secret.py "https://share.doppler.com/s/<slug>#<key>"
  python retrieve_secret.py "https://share.doppler.com/s/<slug>#<key>" --save ~/.config/myservice/credentials --key MYSERVICE_TOKEN

Requires: cryptography (pip install cryptography)
"""

import sys
import re
import base64
import hashlib
import argparse
import urllib.request
import urllib.parse
import http.cookiejar
from pathlib import Path

def decrypt_doppler_share(url: str) -> str:
    """Full Doppler Share E2EE decrypt flow."""
    # Parse slug and password from URL
    match = re.match(r'https://share\.doppler\.com/s/([^#?]+)#(.+)', url)
    if not match:
        raise ValueError("Invalid Doppler Share URL. Expected: https://share.doppler.com/s/<slug>#<key>")

    slug, password = match.group(1), match.group(2)

    # SHA256 the password for server auth (server never sees raw password)
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()

    # Get page with cookie session + CSRF token
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    req = urllib.request.Request(
        f"https://share.doppler.com/s/{slug}",
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with opener.open(req) as r:
        page_html = r.read().decode()

    csrf_match = re.search(r'"csrf":"([^"]+)"', page_html)
    if not csrf_match:
        raise RuntimeError("Could not find CSRF token on page")
    csrf_token = csrf_match.group(1)

    # POST hashed password to retrieve encrypted ciphertext
    post_data = urllib.parse.urlencode({
        "hashed_password": hashed_pw,
        "_csrf": csrf_token,
    }).encode()

    req2 = urllib.request.Request(
        f"https://share.doppler.com/s/{slug}",
        data=post_data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "Referer": f"https://share.doppler.com/s/{slug}",
        }
    )
    with opener.open(req2) as r:
        import json
        payload = json.loads(r.read().decode())

    if not payload.get("success"):
        raise RuntimeError(f"Doppler API error: {payload}")

    encrypted = payload["encrypted_secret"]
    salt_rounds = payload["encryption_salt_rounds"]
    # kdf is always pbkdf2

    # Decrypt: PBKDF2-SHA256 key derivation + AES-256-GCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    buf = base64.b64decode(encrypted)
    # Layout: salt(16) + iv(12) + authTag(16) + ciphertext
    salt = buf[:16]
    iv   = buf[16:28]
    tag  = buf[28:44]
    ct   = buf[44:]

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=salt_rounds)
    key = kdf.derive(password.encode())

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ct + tag, None)
    return plaintext.decode()


def main():
    parser = argparse.ArgumentParser(description="Decrypt a Doppler Share secret URL")
    parser.add_argument("url", help="Full Doppler Share URL including #key fragment")
    parser.add_argument("--save", metavar="FILE", help="Save to this file (e.g. ~/.config/foo/credentials)")
    parser.add_argument("--key", metavar="KEY_NAME", help="Variable name to use when saving (e.g. GRAFANA_TOKEN)")
    args = parser.parse_args()

    print("Retrieving secret from Doppler Share...", file=sys.stderr)
    secret = decrypt_doppler_share(args.url)

    if args.save:
        path = Path(args.save).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        key_name = args.key or "SECRET"
        # Append or update the key in the file
        line = f"{key_name}={secret}\n"
        existing = path.read_text() if path.exists() else ""
        pattern = re.compile(rf'^{re.escape(key_name)}=.*$', re.MULTILINE)
        if pattern.search(existing):
            new_content = pattern.sub(line.rstrip(), existing)
        else:
            new_content = existing + line
        path.write_text(new_content)
        path.chmod(0o600)
        print(f"Saved to {path} as {key_name}=***", file=sys.stderr)
        print(f"Done. Value starts with: {secret[:8]}...")
    else:
        print(secret)


if __name__ == "__main__":
    main()
