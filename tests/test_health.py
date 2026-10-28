from fastapi.testclient import TestClient

from hayat_backend.main import app


def test_health_reports_safe_degraded_status_without_secrets():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "hayat-api"
    assert body["status"] in {"ok", "degraded"}
    assert "GROQ_API_KEY" not in str(body)
    assert "SUPABASE_SERVICE_ROLE_KEY" not in str(body)


def test_health_includes_request_id_and_timing_headers():
    response = TestClient(app).get("/health", headers={"X-Request-ID": "test-request"})

    assert response.headers["X-Request-ID"] == "test-request"
    assert float(response.headers["X-Response-Time-Ms"]) >= 0
