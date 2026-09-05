from __future__ import annotations

import base64
import json
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass

import httpx
from pipeline.core.config import sanitize_httpx_no_proxy

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
SCOPE = "openid profile email offline_access"
VERIFY_URL = f"{ISSUER}/codex/device"
REDIRECT_URI = f"{ISSUER}/deviceauth/callback"
KEYRING_SERVICE = "ZM AIO TOOL ChatGPT"
KEYRING_USER = "chatgpt-account"


def _jwt_claims(token: str | None) -> dict:
    try:
        raw = (token or "").split(".")[1]
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, IndexError, TypeError, json.JSONDecodeError):
        return {}


def _account_id(tokens: dict) -> str:
    for token_name in ("id_token", "access_token"):
        claims = _jwt_claims(tokens.get(token_name))
        auth = claims.get("https://api.openai.com/auth") or {}
        candidate = auth.get("chatgpt_account_id") or claims.get("chatgpt_account_id")
        if candidate:
            return str(candidate)
    return ""


class SystemTokenStore:
    """Tokens live in macOS Keychain / Windows Credential Manager, never app data."""

    def __init__(self, account_id: str = "default"):
        self.account_id = account_id

    def load(self) -> dict | None:
        try:
            import keyring
            raw = keyring.get_password(KEYRING_SERVICE, f"{KEYRING_USER}:{self.account_id}")
            value = json.loads(raw) if raw else None
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    def save(self, tokens: dict) -> None:
        import keyring
        keyring.set_password(KEYRING_SERVICE, f"{KEYRING_USER}:{self.account_id}", json.dumps(tokens))

    def delete(self) -> None:
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, f"{KEYRING_USER}:{self.account_id}")
        except Exception:
            pass


@dataclass
class DeviceLogin:
    id: str
    device_auth_id: str
    user_code: str
    interval: int
    expires_at: float


class ChatGPTAuth:
    def __init__(self, token_store=None, client=None, account_id="default", browser_opener=None):
        self.store = token_store or SystemTokenStore(account_id)
        self.account_id = account_id
        self.browser_opener = browser_opener
        sanitize_httpx_no_proxy()
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self._pending: dict[str, DeviceLogin] = {}
        self._refresh_lock = threading.Lock()

    def status(self) -> dict:
        tokens = self.store.load()
        if not tokens:
            return {"status": "signed_out", "configured": False}
        claims = _jwt_claims(tokens.get("id_token"))
        return {"status": "connected", "configured": True, "email": claims.get("email", ""), "expiresAt": tokens.get("expires_at")}

    def start_login(self, open_browser: bool = True) -> dict:
        response = self.client.post(f"{ISSUER}/api/accounts/deviceauth/usercode", json={"client_id": CLIENT_ID}, headers={"Accept": "application/json"})
        response.raise_for_status()
        raw = response.json()
        if not raw.get("device_auth_id") or not (raw.get("user_code") or raw.get("usercode")):
            raise RuntimeError("Device login response is incomplete")
        login = DeviceLogin(uuid.uuid4().hex, str(raw["device_auth_id"]), str(raw.get("user_code") or raw["usercode"]), max(2, int(raw.get("interval") or 5)), time.time() + 900)
        self._pending[login.id] = login
        if open_browser:
            (self.browser_opener or webbrowser.open)(VERIFY_URL)
        return {"loginId": login.id, "userCode": login.user_code, "verificationUrl": VERIFY_URL, "interval": login.interval, "expiresAt": login.expires_at}

    def poll(self, login_id: str) -> dict:
        login = self._pending.get(login_id)
        if not login:
            raise KeyError(login_id)
        if time.time() >= login.expires_at:
            self._pending.pop(login_id, None)
            return {"status": "expired"}
        response = self.client.post(f"{ISSUER}/api/accounts/deviceauth/token", json={"device_auth_id": login.device_auth_id, "user_code": login.user_code}, headers={"Accept": "application/json"})
        if response.status_code in {403, 404, 429}:
            return {"status": "pending"}
        response.raise_for_status()
        raw = response.json()
        if not all(raw.get(key) for key in ("authorization_code", "code_verifier")):
            return {"status": "pending"}
        token_response = self.client.post(f"{ISSUER}/oauth/token", data={"grant_type": "authorization_code", "client_id": CLIENT_ID, "code": raw["authorization_code"], "code_verifier": raw["code_verifier"], "redirect_uri": REDIRECT_URI}, headers={"Accept": "application/json"})
        token_response.raise_for_status()
        tokens = self._normalize_tokens(token_response.json())
        self.store.save(tokens)
        self._pending.pop(login_id, None)
        status = self.status()
        return {"status": "connected", "email": status.get("email", "")}

    @staticmethod
    def _normalize_tokens(raw: dict, previous_refresh: str = "") -> dict:
        if not raw.get("access_token"):
            raise RuntimeError("Token response is incomplete")
        expires_in = int(raw.get("expires_in") or 3600)
        return {"access_token": raw["access_token"], "refresh_token": raw.get("refresh_token") or previous_refresh, "id_token": raw.get("id_token", ""), "account_id": _account_id(raw), "expires_at": time.time() + expires_in}

    def tokens(self) -> dict:
        with self._refresh_lock:
            tokens = self.store.load()
            if not tokens:
                raise RuntimeError("ChatGPT account is signed out")
            if float(tokens.get("expires_at") or 0) > time.time() + 60:
                return tokens
            refresh = tokens.get("refresh_token")
            if not refresh:
                self.store.delete()
                raise RuntimeError("ChatGPT session expired; sign in again")
            response = self.client.post(f"{ISSUER}/oauth/token", json={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": CLIENT_ID, "scope": SCOPE}, headers={"Accept": "application/json"})
            if response.status_code == 400:
                self.store.delete()
                raise RuntimeError("ChatGPT session expired; sign in again")
            response.raise_for_status()
            updated = self._normalize_tokens(response.json(), refresh)
            self.store.save(updated)
            return updated

    def logout(self) -> None:
        self.store.delete()
