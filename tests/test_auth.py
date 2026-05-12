"""Tests for user login logging feature."""

import base64

from app.auth import login_records


def _admin_auth_header() -> dict[str, str]:
    """Return HTTP Basic auth header for the admin user."""
    credentials = base64.b64encode(b"admin:admin123").decode()
    return {"Authorization": f"Basic {credentials}"}


class TestLoginEndpoint:
    """Tests for the /auth/login endpoint."""

    def test_successful_login(self, client):
        """Valid credentials should return a success response and create a login record."""
        login_records.clear()
        response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Login successful"
        assert data["username"] == "admin"
        assert "logged_in_at" in data
        assert len(login_records) == 1
        assert login_records[0].success is True

    def test_login_unknown_user(self, client):
        """Unknown username should return 401 with generic error."""
        login_records.clear()
        response = client.post(
            "/auth/login",
            json={"username": "ghost", "password": "whatever"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "invalid credentials" in data["detail"].lower()
        assert len(login_records) == 1
        assert login_records[0].success is False
        assert login_records[0].failure_reason == "invalid credentials"

    def test_login_invalid_password(self, client):
        """Wrong password should return 401 with generic error."""
        login_records.clear()
        response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "invalid credentials" in data["detail"].lower()
        assert len(login_records) == 1
        assert login_records[0].success is False
        assert login_records[0].failure_reason == "invalid credentials"

    def test_login_captures_user_agent(self, client):
        """Login record should capture the User-Agent header."""
        login_records.clear()
        response = client.post(
            "/auth/login",
            json={"username": "operator", "password": "operator123"},
            headers={"User-Agent": "TestBrowser/1.0"},
        )
        assert response.status_code == 200
        assert login_records[0].user_agent == "TestBrowser/1.0"

    def test_login_returns_same_error_for_unknown_user_and_bad_password(self, client):
        """Both failure modes should return identical error messages to prevent enumeration."""
        login_records.clear()
        resp_unknown = client.post(
            "/auth/login",
            json={"username": "nonexistent", "password": "whatever"},
        )
        resp_bad_pass = client.post(
            "/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert resp_unknown.status_code == resp_bad_pass.status_code == 401
        assert resp_unknown.json()["detail"] == resp_bad_pass.json()["detail"]


class TestLoginRecordsEndpoint:
    """Tests for the /auth/login-records endpoint."""

    def test_list_login_records_requires_auth(self, client):
        """Should return 401 when no credentials are provided."""
        response = client.get("/auth/login-records")
        assert response.status_code == 401

    def test_list_login_records_empty(self, client):
        """Should return an empty list when no logins have occurred."""
        login_records.clear()
        response = client.get("/auth/login-records", headers=_admin_auth_header())
        assert response.status_code == 200
        assert response.json() == []

    def test_list_login_records_after_logins(self, client):
        """Should return login records in reverse chronological order."""
        login_records.clear()
        client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        client.post("/auth/login", json={"username": "viewer", "password": "viewer123"})
        response = client.get("/auth/login-records", headers=_admin_auth_header())
        assert response.status_code == 200
        records = response.json()
        assert len(records) == 2
        assert records[0]["username"] == "viewer"
        assert records[1]["username"] == "admin"

    def test_list_login_records_limit(self, client):
        """Limit parameter should cap the number of returned records."""
        login_records.clear()
        for _ in range(5):
            client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        response = client.get("/auth/login-records?limit=2", headers=_admin_auth_header())
        assert response.status_code == 200
        assert len(response.json()) == 2
