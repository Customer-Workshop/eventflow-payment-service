"""Tests for user login logging feature."""

from app.auth import login_records


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
        """Unknown username should log a failed attempt."""
        login_records.clear()
        response = client.post(
            "/auth/login",
            json={"username": "ghost", "password": "whatever"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "failed" in data["message"].lower()
        assert len(login_records) == 1
        assert login_records[0].success is False
        assert login_records[0].failure_reason == "unknown user"

    def test_login_invalid_password(self, client):
        """Wrong password should log a failed attempt."""
        login_records.clear()
        response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "failed" in data["message"].lower()
        assert len(login_records) == 1
        assert login_records[0].success is False
        assert login_records[0].failure_reason == "invalid password"

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


class TestLoginRecordsEndpoint:
    """Tests for the /auth/login-records endpoint."""

    def test_list_login_records_empty(self, client):
        """Should return an empty list when no logins have occurred."""
        login_records.clear()
        response = client.get("/auth/login-records")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_login_records_after_logins(self, client):
        """Should return login records in reverse chronological order."""
        login_records.clear()
        client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        client.post("/auth/login", json={"username": "viewer", "password": "viewer123"})
        response = client.get("/auth/login-records")
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
        response = client.get("/auth/login-records?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2
