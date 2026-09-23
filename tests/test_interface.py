from fastapi.testclient import TestClient

from deskpilot_backend.main import app


def test_root_serves_browser_interface() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "DeskPilot" in response.text
    assert "Talk (4 seconds)" in response.text
