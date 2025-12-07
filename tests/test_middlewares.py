"""Tests for middlewares."""
# pylint: disable=redefined-outer-name, protected-access, unused-argument

from typing import Any, Dict

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.middlewares.region_middleware import CLIENT_REGION, RegionASGIMiddleware


def create_app() -> FastAPI:
    """Create a FastAPI app with middleware for testing."""
    app = FastAPI()
    app.add_middleware(RegionASGIMiddleware)

    @app.get("/region")
    def get_region(request: Request) -> Dict[str, Any]:
        return {
            "context_region": CLIENT_REGION.get(),
            "state_region": getattr(request.state, "client_region", "MISSING"),
        }

    return app


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient."""
    app = create_app()
    return TestClient(app)


def test_region_middleware_default_map(client: TestClient) -> None:
    """Test standard mapping from default map."""
    # "in" -> "ap-south"
    response = client.get("/region", headers={"x-country": "in"})
    assert response.status_code == 200
    data = response.json()
    assert data["context_region"] == "ap-south"
    assert data["state_region"] == "ap-south"


def test_region_middleware_no_header(client: TestClient) -> None:
    """Test no header present."""
    response = client.get("/region")
    assert response.status_code == 200
    data = response.json()
    assert data["context_region"] is None
    assert data["state_region"] is None


def test_region_middleware_priority(client: TestClient) -> None:
    """Test header priority: x-geo-region > x-cloud-region > x-country."""
    # x-geo-region should win
    headers = {
        "x-geo-region": "us-east",
        "x-cloud-region": "eu-west",
        "x-country": "in",
    }
    response = client.get("/region", headers=headers)
    assert response.json()["context_region"] == "us-east"

    # x-cloud-region should win if no x-geo-region
    headers = {
        "x-cloud-region": "eu-west",
        "x-country": "in",
    }
    response = client.get("/region", headers=headers)
    assert response.json()["context_region"] == "eu-west"


def test_region_middleware_whitelist(client: TestClient) -> None:
    """Test whitelist regex rejection."""
    # invalid char '!'
    response = client.get("/region", headers={"x-geo-region": "invalid!"})
    assert response.json()["context_region"] is None


def test_region_middleware_custom_mapping() -> None:
    """Test initializing middleware with custom mapping."""
    app = FastAPI()
    app.add_middleware(RegionASGIMiddleware, mapping={"custom": "mapped"}, header_names=["x-custom"])

    @app.get("/region")
    def get_region(request: Request) -> Dict[str, Any]:
        return {"region": CLIENT_REGION.get()}

    client = TestClient(app)

    # helper for mapping
    response = client.get("/region", headers={"x-custom": "CUSTOM"})
    assert response.json()["region"] == "mapped"

    # pass-through (if in whitelist but not in map)
    # The code says: return self.mapping.get(v, v)
    # So if "other" is whitelisted but not in map, it returns "other"
    response = client.get("/region", headers={"x-custom": "other"})
    assert response.json()["region"] == "other"


def test_normalize_map_direct() -> None:
    """Test _normalize_map directly for unreachable branches via __call__."""
    middleware = RegionASGIMiddleware(app=FastAPI())
    assert middleware._normalize_map("") is None
