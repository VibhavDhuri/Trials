"""
Upstox OAuth2 token management.
Tokens are valid until midnight IST — must be refreshed daily.
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from config import UPSTOX_API_BASE, UPSTOX_AUTH_DIALOG, UPSTOX_TOKEN_URL

load_dotenv()

_PROFILE_ENDPOINT = f"{UPSTOX_API_BASE}/user/profile"


def build_auth_url() -> str:
    """Return the Upstox OAuth2 authorization URL for the user to visit."""
    params = {
        "response_type": "code",
        "client_id": os.getenv("UPSTOX_API_KEY", ""),
        "redirect_uri": os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:5555/callback"),
    }
    return f"{UPSTOX_AUTH_DIALOG}?{urlencode(params)}"


def exchange_code_for_token(auth_code: str) -> str:
    """Exchange an authorization code for an access token."""
    resp = requests.post(
        UPSTOX_TOKEN_URL,
        data={
            "code": auth_code,
            "client_id": os.getenv("UPSTOX_API_KEY", ""),
            "client_secret": os.getenv("UPSTOX_API_SECRET", ""),
            "redirect_uri": os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:5555/callback"),
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_stored_token() -> str:
    return os.getenv("UPSTOX_ACCESS_TOKEN", "")


def validate_token(token: str) -> bool:
    """Return True if the token is valid (not expired/revoked)."""
    if not token:
        return False
    try:
        resp = requests.get(
            _PROFILE_ENDPOINT,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


AUTH_INSTRUCTIONS = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  UPSTOX AUTHENTICATION REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Tokens expire daily at midnight IST.

  Steps to authenticate:
  1. Set UPSTOX_API_KEY and UPSTOX_API_SECRET in your .env file
     (copy .env.example → .env and fill in your credentials)
  2. Run:  python auth/upstox_auth.py --get-url
     to print your OAuth2 login URL
  3. Open the URL in a browser, log in to Upstox
  4. Copy the 'code' parameter from the redirect URL
  5. Run:  python auth/upstox_auth.py --exchange-code <CODE>
     to exchange it for an access token
  6. Paste the access token into UPSTOX_ACCESS_TOKEN in your .env file
  7. Restart the app

  The app will run in OFFLINE (sample data) mode until authenticated.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

if __name__ == "__main__":
    import sys

    if "--get-url" in sys.argv:
        url = build_auth_url()
        print(f"\nOpen this URL in your browser:\n\n  {url}\n")
    elif "--exchange-code" in sys.argv:
        idx = sys.argv.index("--exchange-code")
        if idx + 1 >= len(sys.argv):
            print("Usage: python auth/upstox_auth.py --exchange-code <CODE>")
            sys.exit(1)
        code = sys.argv[idx + 1]
        try:
            token = exchange_code_for_token(code)
            print(f"\nAccess token obtained. Add to your .env:\n\n  UPSTOX_ACCESS_TOKEN={token}\n")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        token = get_stored_token()
        if validate_token(token):
            print("Token is valid.")
        else:
            print(AUTH_INSTRUCTIONS)
