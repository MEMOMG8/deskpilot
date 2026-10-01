import base64
import ctypes
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol

SPOTIFY_ACCOUNTS_HOST = "accounts.spotify.com"
SPOTIFY_API_HOST = "api.spotify.com"
SPOTIFY_AUTH_URL = f"https://{SPOTIFY_ACCOUNTS_HOST}/authorize"
SPOTIFY_TOKEN_URL = f"https://{SPOTIFY_ACCOUNTS_HOST}/api/token"
SPOTIFY_API_BASE_URL = f"https://{SPOTIFY_API_HOST}/v1"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8765/callback"
SPOTIFY_SCOPES = "user-read-playback-state user-modify-playback-state"
DEFAULT_SPOTIFY_TOKEN_FILE = Path.home() / "Documents" / "DeskPilot" / "spotify.bin"
TOKEN_REFRESH_SKEW_SECONDS = 60
OAUTH_TIMEOUT_SECONDS = 120


class SpotifyError(RuntimeError):
    """Raised when Spotify work cannot complete safely."""


class SpotifyNotConnectedError(SpotifyError):
    """Raised when no local Spotify token is available."""


class SpotifyNoActiveDeviceError(SpotifyError):
    """Raised when Spotify has no active playback device."""


class SpotifyOAuthError(SpotifyError):
    """Raised when OAuth cannot complete safely."""


@dataclass(frozen=True)
class SpotifyToken:
    access_token: str
    refresh_token: str
    expires_at: float


@dataclass(frozen=True)
class OAuthCallbackResult:
    code: str


@dataclass(frozen=True)
class SpotifyDevice:
    id: str
    name: str
    type: str
    is_active: bool
    is_restricted: bool


class SecureTokenStore(Protocol):
    def load(self) -> SpotifyToken | None:
        """Load a protected Spotify token."""

    def save(self, token: SpotifyToken) -> None:
        """Save a protected Spotify token."""

    def delete(self) -> None:
        """Delete a protected Spotify token."""


class SpotifyHttpClient(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object] | None]:
        """Make one HTTPS request to Spotify."""


def generate_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def generate_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(
    *,
    client_id: str,
    state: str,
    code_challenge: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "scope": SPOTIFY_SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
    )
    return f"{SPOTIFY_AUTH_URL}?{query}"


def parse_oauth_callback_path(path: str, expected_state: str) -> OAuthCallbackResult:
    parsed = urllib.parse.urlparse(path)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.path != "/callback":
        raise SpotifyOAuthError("Spotify callback path is invalid.")

    if query.get("state", [""])[0] != expected_state:
        raise SpotifyOAuthError("Spotify connection state is invalid.")

    if query.get("error", [""])[0]:
        raise SpotifyOAuthError("Spotify connection was denied.")

    code = query.get("code", [""])[0]
    if not code:
        raise SpotifyOAuthError("Spotify authorization code is missing.")

    return OAuthCallbackResult(code=code)


class SpotifyService:
    def __init__(
        self,
        *,
        token_store: SecureTokenStore | None = None,
        http_client: SpotifyHttpClient | None = None,
        callback_receiver: object | None = None,
        browser_launcher: object | None = None,
        env_getter: object | None = None,
        clock: object | None = None,
    ) -> None:
        self.token_store = token_store or DpapiSpotifyTokenStore()
        self.http_client = http_client or UrlLibSpotifyHttpClient()
        self.callback_receiver = callback_receiver or LocalOAuthCallbackReceiver()
        self.browser_launcher = browser_launcher or webbrowser.open
        self.env_getter = env_getter or os.getenv
        self.clock = clock or time.time

    def connect(self) -> str:
        client_id = self._client_id()
        verifier = generate_pkce_verifier()
        challenge = generate_pkce_challenge(verifier)
        state = generate_oauth_state()
        authorization_url = build_authorization_url(
            client_id=client_id,
            state=state,
            code_challenge=challenge,
        )

        callback = self.callback_receiver.receive(
            state,
            OAUTH_TIMEOUT_SECONDS,
            authorization_url,
            self.browser_launcher,
        )
        token = self._exchange_code(client_id, callback.code, verifier)
        self.token_store.save(token)
        return "Spotify connected."

    def disconnect(self) -> str:
        self.token_store.delete()
        return "Spotify disconnected."

    def status(self) -> str:
        status_code, payload = self._api_request("GET", "/me/player")
        if status_code == 204:
            return "No active Spotify device. Open Spotify and play something first."

        if payload is None:
            raise SpotifyError("Spotify is unavailable.")

        is_playing = bool(payload.get("is_playing"))
        item = payload.get("item")
        if isinstance(item, dict):
            track = item.get("name")
            artists = item.get("artists")
            artist_names = _format_artist_names(artists)
            if isinstance(track, str) and artist_names:
                state = "Playing" if is_playing else "Paused"
                return f"Spotify {state}: {track} by {artist_names}."

        return "Spotify is playing." if is_playing else "Spotify is paused."

    def play(self) -> str:
        self._api_request("PUT", "/me/player/play")
        return "Playing Spotify."

    def pause(self) -> str:
        self._api_request("PUT", "/me/player/pause")
        return "Pausing Spotify."

    def next_track(self) -> str:
        self._api_request("POST", "/me/player/next")
        return "Skipping to the next Spotify song."

    def previous_track(self) -> str:
        self._api_request("POST", "/me/player/previous")
        return "Going to the previous Spotify song."

    def set_volume(self, volume_percent: int) -> str:
        if volume_percent < 0 or volume_percent > 100:
            raise SpotifyError("Spotify volume must be between 0 and 100.")

        self._api_request(
            "PUT",
            f"/me/player/volume?{urllib.parse.urlencode({'volume_percent': volume_percent})}",
        )
        return f"Spotify volume set to {volume_percent}%."

    def available_devices(self) -> list[SpotifyDevice]:
        _status_code, payload = self._api_request("GET", "/me/player/devices")
        if payload is None:
            raise SpotifyError("Spotify is unavailable.")
        devices = payload.get("devices")
        if not isinstance(devices, list):
            raise SpotifyError("Spotify device response was invalid.")

        return [
            _device_from_payload(device)
            for device in devices
            if isinstance(device, dict)
        ]

    def transfer_playback(self, device_id: str, *, play: bool = True) -> str:
        if not device_id:
            raise SpotifyError("Spotify device is unavailable.")

        self._api_request(
            "PUT",
            "/me/player",
            data={"device_ids": [device_id], "play": play},
            json_body=True,
        )
        return "Spotify playback transferred."

    def _client_id(self) -> str:
        client_id = self.env_getter("SPOTIFY_CLIENT_ID")
        if not isinstance(client_id, str) or not client_id.strip():
            raise SpotifyOAuthError("SPOTIFY_CLIENT_ID is not configured.")
        return client_id.strip()

    def _exchange_code(
        self,
        client_id: str,
        code: str,
        verifier: str,
    ) -> SpotifyToken:
        status_code, payload = self.http_client.request_json(
            "POST",
            SPOTIFY_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        if status_code < 200 or status_code >= 300 or payload is None:
            raise SpotifyOAuthError("Spotify connection failed.")

        return _token_from_payload(payload, self.clock())

    def _refresh_token(self, token: SpotifyToken) -> SpotifyToken:
        status_code, payload = self.http_client.request_json(
            "POST",
            SPOTIFY_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": self._client_id(),
            },
        )
        if status_code < 200 or status_code >= 300 or payload is None:
            self.token_store.delete()
            raise SpotifyNotConnectedError("Spotify is not connected. Say connect spotify.")

        refreshed = _token_from_payload(
            payload,
            self.clock(),
            fallback_refresh_token=token.refresh_token,
        )
        self.token_store.save(refreshed)
        return refreshed

    def _access_token(self) -> str:
        token = self.token_store.load()
        if token is None:
            raise SpotifyNotConnectedError("Spotify is not connected. Say connect spotify.")

        if token.expires_at <= self.clock() + TOKEN_REFRESH_SKEW_SECONDS:
            token = self._refresh_token(token)

        return token.access_token

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, object] | None = None,
        json_body: bool = False,
    ) -> tuple[int, dict[str, object] | None]:
        url = f"{SPOTIFY_API_BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        status_code, payload = self.http_client.request_json(
            method,
            url,
            headers=headers,
            data=data,
        )
        if status_code == 204:
            return status_code, payload
        if status_code == 404:
            raise SpotifyNoActiveDeviceError(
                "No active Spotify device. Open Spotify and play something first."
            )
        if status_code == 401:
            self.token_store.delete()
            raise SpotifyNotConnectedError("Spotify is not connected. Say connect spotify.")
        if status_code < 200 or status_code >= 300:
            raise SpotifyError("Spotify is unavailable.")
        return status_code, payload


class UrlLibSpotifyHttpClient:
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object] | None]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            SPOTIFY_ACCOUNTS_HOST,
            SPOTIFY_API_HOST,
        }:
            raise SpotifyError("Spotify request target is not trusted.")

        body = None
        request_headers = dict(headers or {})
        if data is not None:
            content_type = request_headers.get("Content-Type", "")
            if content_type.startswith("application/json"):
                body = json.dumps(data).encode("utf-8")
            else:
                body = urllib.parse.urlencode(data).encode("utf-8")
                request_headers.setdefault(
                    "Content-Type",
                    "application/x-www-form-urlencoded",
                )

        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, _read_json_response(response.read())
        except urllib.error.HTTPError as error:
            return error.code, _read_json_response(error.read())
        except urllib.error.URLError as error:
            raise SpotifyError("Spotify is unavailable.") from error


class LocalOAuthCallbackReceiver:
    def receive(
        self,
        expected_state: str,
        timeout_seconds: int,
        authorization_url: str,
        browser_launcher: object,
    ) -> OAuthCallbackResult:
        server = _SpotifyCallbackServer(("127.0.0.1", 8765), _SpotifyCallbackHandler)
        server.expected_state = expected_state
        server.timeout = timeout_seconds

        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            browser_launcher(authorization_url)
            thread.join(timeout_seconds)
        finally:
            server.server_close()

        if thread.is_alive():
            raise SpotifyOAuthError("Spotify connection timed out.")
        if server.error_message is not None:
            raise SpotifyOAuthError(server.error_message)
        if server.code is None:
            raise SpotifyOAuthError("Spotify connection failed.")
        return OAuthCallbackResult(code=server.code)


class _SpotifyCallbackServer(HTTPServer):
    expected_state: str
    code: str | None = None
    error_message: str | None = None


class _SpotifyCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        server = self.server
        if not isinstance(server, _SpotifyCallbackServer):
            return

        try:
            result = parse_oauth_callback_path(self.path, server.expected_state)
        except SpotifyOAuthError as error:
            server.error_message = str(error)
            self._respond(400, "DeskPilot Spotify connection failed.")
            return

        server.code = result.code
        self._respond(200, "Spotify connected. You can close this window.")

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _respond(self, status_code: int, body: str) -> None:
        body_bytes = body.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


class DpapiSpotifyTokenStore:
    def __init__(self, token_file: Path = DEFAULT_SPOTIFY_TOKEN_FILE) -> None:
        self.token_file = token_file

    def load(self) -> SpotifyToken | None:
        if not self.token_file.exists():
            return None
        try:
            raw_data = _dpapi_unprotect(self.token_file.read_bytes())
            payload = json.loads(raw_data.decode("utf-8"))
            return SpotifyToken(
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
                expires_at=float(payload["expires_at"]),
            )
        except Exception as error:
            raise SpotifyError("Spotify token storage is unavailable.") from error

    def save(self, token: SpotifyToken) -> None:
        payload = json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at,
            }
        ).encode("utf-8")
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_bytes(_dpapi_protect(payload))
        except Exception as error:
            raise SpotifyError("Spotify token storage is unavailable.") from error

    def delete(self) -> None:
        try:
            self.token_file.unlink(missing_ok=True)
        except OSError as error:
            raise SpotifyError("Spotify token storage is unavailable.") from error


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SpotifyError("Spotify token protection is only supported on Windows.")

    in_blob, in_buffer = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    _ = in_buffer
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise SpotifyError("Spotify token protection failed.")
    return _bytes_from_blob(out_blob)


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SpotifyError("Spotify token protection is only supported on Windows.")

    in_blob, in_buffer = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    _ = in_buffer
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise SpotifyError("Spotify token protection failed.")
    return _bytes_from_blob(out_blob)


def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, object]:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(len(data), buffer), buffer


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _token_from_payload(
    payload: dict[str, object],
    now: float,
    *,
    fallback_refresh_token: str | None = None,
) -> SpotifyToken:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token") or fallback_refresh_token
    expires_in = payload.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not isinstance(refresh_token, str)
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
    ):
        raise SpotifyOAuthError("Spotify token response was invalid.")
    return SpotifyToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + expires_in,
    )


def _read_json_response(raw_body: bytes) -> dict[str, object] | None:
    if not raw_body:
        return None
    parsed = json.loads(raw_body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else None


def _device_from_payload(payload: dict[str, object]) -> SpotifyDevice:
    device_id = payload.get("id")
    device_name = payload.get("name")
    device_type = payload.get("type")
    if (
        not isinstance(device_id, str)
        or not isinstance(device_name, str)
        or not isinstance(device_type, str)
    ):
        raise SpotifyError("Spotify device response was invalid.")

    return SpotifyDevice(
        id=device_id,
        name=device_name,
        type=device_type,
        is_active=bool(payload.get("is_active")),
        is_restricted=bool(payload.get("is_restricted")),
    )


def _format_artist_names(artists: object) -> str | None:
    if not isinstance(artists, list):
        return None
    names = [
        artist.get("name")
        for artist in artists
        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
    ]
    return ", ".join(names) if names else None
