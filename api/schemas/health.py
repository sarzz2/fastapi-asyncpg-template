from pydantic import BaseModel


class RedisStatus(BaseModel):
    """Redis status model."""

    status: str


class DBRegionStatus(BaseModel):
    """Database region status model."""

    healthy_pools: int
    total_pools: int
    avg_latency: float | None = None


class DBStatus(BaseModel):
    """Database status model."""

    status: str
    regions: dict[str, DBRegionStatus]


class HealthResponse(BaseModel):
    """Health response model."""

    status: str
    database: DBStatus
    redis: RedisStatus
