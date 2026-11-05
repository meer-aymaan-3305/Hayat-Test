"""Only trawellcare-bff may reach this API."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from hayat_backend import main
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.service_auth import is_service_token

SECRET = "a-test-secret-that-is-at-least-32-characters"


def _token(secret=SECRET, sub="system:bff", expires_in=60):
    claims = {"sub": sub, "exp": datetime.now(UTC) + timedelta(seconds=expires_in)}
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def client(monkeypatch):
    settings = Settings(app_env="production", jwt_system_secret=SECRET)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return TestClient(create_app(store=MemoryStore()))


def test_health_stays_open(client):
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/v1/coordinator/programme-enquiries/ENQ-12345678"),
        ("get", "/v1/coordinator/handoffs/00000000-0000-0000-0000-000000000000"),
        ("post", "/v1/coordinator/handoffs/00000000-0000-0000-0000-000000000000/confirm-appointment"),
        ("post", "/v1/sessions/guest"),
    ],
)
def test_routes_refuse_callers_without_a_service_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_spoofed_coordinator_headers_are_not_enough(client):
    headers = {"X-Coordinator-ID": "coord_101", "X-Coordinator-Role": "case_manager"}
    assert client.get("/v1/coordinator/programme-enquiries/ENQ-12345678", headers=headers).status_code == 401


def test_valid_service_token_is_let_through(client):
    response = client.post("/v1/sessions/guest", headers={"X-Service-Token": _token()})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        None,
        "not-a-token",
        _token(secret="another-secret-that-is-at-least-32-characters"),
        _token(expires_in=-5),
        _token(sub="customer:1"),
    ],
)
def test_bad_tokens_are_rejected(token):
    assert is_service_token(token, SECRET) is False


def test_missing_secret_fails_closed():
    assert is_service_token(_token(), None) is False


def test_redact_needs_the_service_token(client):
    assert client.post("/v1/redact", json={"text": "My chat"}).status_code == 401


def test_redact_removes_medical_details_from_a_title(client):
    headers = {"X-Service-Token": _token()}
    response = client.post("/v1/redact", json={"text": "I have diabetes and need treatment"}, headers=headers)
    assert response.status_code == 200
    assert "diabetes" not in response.json()["text"]
    assert client.post("/v1/redact", json={"text": "Summer trip"}, headers=headers).json() == {"text": "Summer trip"}
