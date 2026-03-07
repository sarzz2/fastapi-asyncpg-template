"""
Tests for ASGI middlewares, primarily focusing on regional routing and context management.
"""

from typing import Any, Dict

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.middlewares.region_middleware import CLIENT_REGION, RegionASGIMiddleware


def create_test_app(mapping: dict | None = None, header_names: list | None = None) -> FastAPI:
    """
    Utility to create a FastAPI application with the Region middleware.
    """
    app = FastAPI()
    kwargs: Dict[str, Any] = {}
    if mapping:
        kwargs["mapping"] = mapping
    if header_names:
        kwargs["header_names"] = header_names

    app.add_middleware(RegionASGIMiddleware, **kwargs)

    @app.get("/region")
    def get_region(request: Request) -> Dict[str, Any]:
        return {
            "context": CLIENT_REGION.get(),
            "state": getattr(request.state, "client_region", None),
        }

    return app


@pytest.fixture
def test_client() -> TestClient:
    """Provides a TestClient for the region middleware app."""
    return TestClient(create_test_app())


def test_region_standard_mapping(test_client: TestClient) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that country codes are correctly mapped to regional identifiers (e.g., 'in' -> 'ap-south').
    """
    response = test_client.get("/region", headers={"x-country": "in"})
    assert response.status_code == 200
    data = response.json()
    assert data["context"] == "ap-south"
    assert data["state"] == "ap-south"


def test_region_middleware_no_headers(test_client: TestClient) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that the middleware handles requests without regional headers gracefully.
    """
    response = test_client.get("/region")
    data = response.json()
    assert data["context"] is None
    assert data["state"] is None


def test_region_header_priority(test_client: TestClient) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify regional header precedence: geo-region > cloud-region > country.
    """
    # 1. Geo-region win
    headers = {"x-geo-region": "us-east", "x-cloud-region": "eu-west", "x-country": "in"}
    assert test_client.get("/region", headers=headers).json()["context"] == "us-east"

    # 2. Cloud-region win (over country)
    headers = {"x-cloud-region": "eu-west", "x-country": "in"}
    assert test_client.get("/region", headers=headers).json()["context"] == "eu-west"


def test_region_whitelist_rejection(test_client: TestClient) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that invalid characters in regional headers are rejected via whitelist validation.
    """
    response = test_client.get("/region", headers={"x-geo-region": "invalid!region"})
    assert response.json()["context"] is None


def test_custom_regional_mapping_initialization() -> None:
    """
    Verify that the middleware correctly supports custom mappings and header configurations.
    """
    custom_app = create_test_app(mapping={"dev": "local"}, header_names=["x-env"])
    client = TestClient(custom_app)

    # 1. Successful custom map
    assert client.get("/region", headers={"x-env": "dev"}).json()["context"] == "local"

    # 2. Whitelisted but unmapped (pass-through)
    assert client.get("/region", headers={"x-env": "prod"}).json()["context"] == "prod"


def test_region_normalization_edge_cases() -> None:
    """
    Verify internal normalization logic for edge cases (e.g., empty strings).
    """
    middleware = RegionASGIMiddleware(app=FastAPI())
    assert middleware._normalize_map("") is None  # pylint: disable=protected-access
