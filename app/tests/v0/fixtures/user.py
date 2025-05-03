import uuid

import pytest
from httpx import AsyncClient

from app.tests.conftest import API_PREFIX


@pytest.fixture
def random_user():
    """Generate a random user payload."""
    user_id = uuid.uuid4()
    return {
        "id": str(user_id),
        "username": f"user_{user_id.hex[:6]}",
        "email": f"{user_id.hex[:6]}@example.com",
        "password": "S3cureP@ss!",
    }


@pytest.fixture
async def registered_user(client: AsyncClient, random_user):
    """Register a new user and return its token payload."""
    r = await client.post(f"{API_PREFIX}/users/register", json=random_user)
    assert r.status_code == 201, r.text
    tokens = r.json()
    return {**random_user, **tokens}
