"""Minimal liveness contract for platform health checks."""


def test_health_live_does_not_require_external_services(api_client) -> None:
    response = api_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
