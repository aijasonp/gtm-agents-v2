---
name: doppler-share
description: Retrieve and decrypt secrets from Doppler Share URLs (https://share.doppler.com/s/<slug>#<key>). Use when someone shares a Doppler Share link to securely pass a secret (API key, token, password). Handles the full E2EE flow without needing a browser.
---

# Doppler Share Skill

Decrypts Doppler Share one-time secret links entirely in Python — no browser required.

## How it works

Doppler Share uses E2EE: the hash fragment (`#key`) is the AES decryption key and never leaves the client. The script:
1. Fetches the page to get a session cookie + CSRF token
2. POSTs SHA256(key) to retrieve the encrypted ciphertext
3. Decrypts locally using PBKDF2-SHA256 key derivation + AES-256-GCM

**Requires:** `pip install cryptography`

## Usage

```bash
# Print secret to stdout
python skills/doppler-share/scripts/retrieve_secret.py "https://share.doppler.com/s/<slug>#<key>"

# Save directly to a credentials file
python skills/doppler-share/scripts/retrieve_secret.py \
  "https://share.doppler.com/s/<slug>#<key>" \
  --save ~/.config/myservice/credentials \
  --key MY_SERVICE_TOKEN
```

## Important

- Links are **one-time use** — fetch immediately when shared
- The `web_fetch` tool cannot decrypt these (requires JS) — always use this script
- After saving, never echo the secret value in chat responses
- Credentials files are saved with `chmod 600` automatically
