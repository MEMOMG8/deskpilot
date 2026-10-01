import base64
import hashlib
import urllib.parse

import pytest

from deskpilot_backend.spotify import (
    OAuthCallbackResult,
    SPOTIFY_REDIRECT_URI,
    SPOTIFY_SCOPES,
    SpotifyDevice,
    SpotifyError,
    SpotifyNoActiveDeviceError,
    SpotifyNotConnectedError,
    SpotifyOAuthError,
    SpotifyService,
    SpotifyToken,
    build_authorization_url,
    generate_pkce_challenge,
    generate_pkce_verifier,
    parse_oauth_callback_path,
)


class FakeTokenStore:
    def __init__(self, token: SpotifyToken | None = None) -> None:
        self.token = token
        self.saved: list[SpotifyToken] = []
        self.deleted = False

    def load(self) -> SpotifyToken | None:
        return self.token

    def save(self, token: SpotifyToken) -> None:
        self.token = token
        self.saved.append(token)

    def delete(self) -> None:
        self.deleted = True
        self.token = None


class FakeHttpClient:
    def __init__(self, responses: list[tuple[int, dict[str, object] | None]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object] | None]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "data": data or {},
            }
        )
        return self.responses.pop(0)


class FakeCallbackReceiver:
    def __init__(self, result: OAuthCallbackResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, int, str]] = []

    def receive(
        self,
        expected_state: str,
        timeout_seconds: int,
        authorization_url: str,
        browser_launcher,
    ) -> OAuthCallbackResult:
        self.calls.append((expected_state, timeout_seconds, authorization_url))
        browser_launcher(authorization_url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_pkce_verifier_and_challenge_are_url_safe() -> None:
    verifier = generate_pkce_verifier()
    challenge = generate_pkce_challenge(verifier)
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")

    assert 43 <= len(verifier) <= 128
    assert challenge == expected
    assert "=" not in challenge


def test_authorization_url_uses_required_scope_and_no_secret() -> None:
    url = build_authorization_url(
        client_id="client-id",
        state="state",
        code_challenge="challenge",
    )
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.spotify.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == [SPOTIFY_REDIRECT_URI]
    assert query["scope"] == [SPOTIFY_SCOPES]
    assert query["code_challenge_method"] == ["S256"]
    assert "client_secret" not in query


def test_callback_validation_accepts_code_and_rejects_bad_state_or_denial() -> None:
    assert (
        parse_oauth_callback_path("/callback?code=abc&state=good", "good").code
        == "abc"
    )

    with pytest.raises(SpotifyOAuthError, match="state"):
        parse_oauth_callback_path("/callback?code=abc&state=bad", "good")

    with pytest.raises(SpotifyOAuthError, match="denied"):
        parse_oauth_callback_path("/callback?error=access_denied&state=good", "good")


def test_connect_opens_browser_exchanges_code_and_stores_protected_token() -> None:
    store = FakeTokenStore()
    http = FakeHttpClient(
        [
            (
                200,
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                },
            )
        ]
    )
    opened_urls: list[str] = []
    service = SpotifyService(
        token_store=store,
        http_client=http,
        callback_receiver=FakeCallbackReceiver(OAuthCallbackResult(code="code")),
        browser_launcher=opened_urls.append,
        env_getter=lambda name: "client-id",
        clock=lambda: 100.0,
    )

    message = service.connect()

    assert message == "Spotify connected."
    assert opened_urls
    assert "client_secret" not in opened_urls[0]
    assert http.calls[0]["data"]["client_id"] == "client-id"
    assert http.calls[0]["data"]["code"] == "code"
    assert "client_secret" not in http.calls[0]["data"]
    assert store.saved == [
        SpotifyToken(access_token="access", refresh_token="refresh", expires_at=3700.0)
    ]


def test_connect_requires_client_id_and_maps_timeout() -> None:
    service = SpotifyService(
        token_store=FakeTokenStore(),
        http_client=FakeHttpClient([]),
        callback_receiver=FakeCallbackReceiver(OAuthCallbackResult(code="code")),
        browser_launcher=lambda url: None,
        env_getter=lambda name: None,
    )
    with pytest.raises(SpotifyOAuthError, match="SPOTIFY_CLIENT_ID"):
        service.connect()

    timed_out = SpotifyService(
        token_store=FakeTokenStore(),
        http_client=FakeHttpClient([]),
        callback_receiver=FakeCallbackReceiver(
            SpotifyOAuthError("Spotify connection timed out.")
        ),
        browser_launcher=lambda url: None,
        env_getter=lambda name: "client-id",
    )
    with pytest.raises(SpotifyOAuthError, match="timed out"):
        timed_out.connect()


def test_refresh_expired_access_token_before_api_call() -> None:
    store = FakeTokenStore(
        SpotifyToken(access_token="old", refresh_token="refresh", expires_at=100)
    )
    http = FakeHttpClient(
        [
            (200, {"access_token": "new", "expires_in": 3600}),
            (
                200,
                {
                    "is_playing": True,
                    "item": {
                        "name": "Song",
                        "artists": [{"name": "Artist"}],
                    },
                },
            ),
        ]
    )
    service = SpotifyService(
        token_store=store,
        http_client=http,
        env_getter=lambda name: "client-id",
        clock=lambda: 200.0,
    )

    assert service.status() == "Spotify Playing: Song by Artist."
    assert store.saved[-1] == SpotifyToken(
        access_token="new",
        refresh_token="refresh",
        expires_at=3800.0,
    )
    assert http.calls[0]["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh",
        "client_id": "client-id",
    }
    assert http.calls[1]["headers"]["Authorization"] == "Bearer new"


def test_disconnect_deletes_local_token_only() -> None:
    store = FakeTokenStore(SpotifyToken("access", "refresh", 1000))
    service = SpotifyService(token_store=store, http_client=FakeHttpClient([]))

    assert service.disconnect() == "Spotify disconnected."
    assert store.deleted is True


def test_not_connected_and_no_active_device_are_controlled() -> None:
    service = SpotifyService(token_store=FakeTokenStore(), http_client=FakeHttpClient([]))
    with pytest.raises(SpotifyNotConnectedError, match="Spotify is not connected"):
        service.status()

    no_device = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=FakeHttpClient([(204, None)]),
        clock=lambda: 100.0,
    )
    assert (
        no_device.status()
        == "No active Spotify device. Open Spotify and play something first."
    )

    no_device_error = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=FakeHttpClient([(404, None)]),
        clock=lambda: 100.0,
    )
    with pytest.raises(SpotifyNoActiveDeviceError):
        no_device_error.play()


def test_available_devices_parses_spotify_computer_devices() -> None:
    service = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=FakeHttpClient(
            [
                (
                    200,
                    {
                        "devices": [
                            {
                                "id": "desktop",
                                "name": "Desktop Spotify",
                                "type": "Computer",
                                "is_active": False,
                                "is_restricted": False,
                            }
                        ]
                    },
                )
            ]
        ),
        clock=lambda: 100.0,
    )

    assert service.available_devices() == [
        SpotifyDevice(
            id="desktop",
            name="Desktop Spotify",
            type="Computer",
            is_active=False,
            is_restricted=False,
        )
    ]


def test_transfer_playback_uses_json_payload_with_play_enabled() -> None:
    http = FakeHttpClient([(204, None)])
    service = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=http,
        clock=lambda: 100.0,
    )

    assert (
        service.transfer_playback("desktop-device", play=True)
        == "Spotify playback transferred."
    )
    assert http.calls == [
        {
            "method": "PUT",
            "url": "https://api.spotify.com/v1/me/player",
            "headers": {
                "Authorization": "Bearer access",
                "Content-Type": "application/json",
            },
            "data": {"device_ids": ["desktop-device"], "play": True},
        }
    ]


def test_play_endpoint_accepts_204_no_content_as_success() -> None:
    http = FakeHttpClient([(204, None)])
    service = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=http,
        clock=lambda: 100.0,
    )

    assert service.play() == "Playing Spotify."
    assert http.calls == [
        {
            "method": "PUT",
            "url": "https://api.spotify.com/v1/me/player/play",
            "headers": {"Authorization": "Bearer access"},
            "data": {},
        }
    ]


def test_spotify_api_error_mapping_and_volume_validation() -> None:
    unavailable = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=FakeHttpClient([(500, {})]),
        clock=lambda: 100.0,
    )
    with pytest.raises(SpotifyError, match="unavailable"):
        unavailable.pause()

    service = SpotifyService(
        token_store=FakeTokenStore(SpotifyToken("access", "refresh", 9999)),
        http_client=FakeHttpClient([(204, None)]),
        clock=lambda: 100.0,
    )
    assert service.set_volume(42) == "Spotify volume set to 42%."

    with pytest.raises(SpotifyError, match="between 0 and 100"):
        service.set_volume(101)
