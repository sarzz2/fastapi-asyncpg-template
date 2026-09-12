"""
Pydantic Schemas for Celery Dead Letter Queue (DLQ).
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DLQTaskBase(BaseModel):
    """Base Dead Letter Queue task schema with core properties."""

    model_config = ConfigDict(populate_by_name=True)

    task_name: str
    queue: str = "default"
    args: list[Any] = Field(default_factory=list)
    task_kwargs: dict[str, Any] = Field(default_factory=dict, alias="kwargs")
    headers: dict[str, Any] = Field(default_factory=dict)

    @property
    def kwargs(self) -> dict[str, Any]:
        """Alias property for task_kwargs."""
        return self.task_kwargs

    @field_validator("args", mode="before")
    @classmethod
    def parse_args(cls, v: Any) -> Any:
        """Parse JSON serialized args if string."""
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return []
            try:
                parsed = json.loads(v_stripped)
                return parsed if isinstance(parsed, list) else [parsed]
            except (json.JSONDecodeError, TypeError):
                return []
        return v or []

    @field_validator("task_kwargs", "headers", mode="before")
    @classmethod
    def parse_dict_fields(cls, v: Any) -> Any:
        """Parse JSON serialized dict fields if string."""
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return {}
            try:
                parsed = json.loads(v_stripped)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return v or {}


class DLQTaskResponse(DLQTaskBase):
    """Response model for Dead Letter Queue entries."""

    id: UUID
    task_id: str
    exception_type: str | None = None
    exception_message: str | None = None
    traceback: str | None = None
    retry_count: int = 0
    failed_at: datetime
    created_at: datetime
    updated_at: datetime

    def __getattribute__(self, name: str) -> Any:
        """Dynamically parse args, task_kwargs, and headers JSON strings on access."""
        val = super().__getattribute__(name)
        if name in ("args", "task_kwargs", "headers") and isinstance(val, str):
            try:
                parsed = json.loads(val)
                object.__setattr__(self, name, parsed)
                return parsed
            except (json.JSONDecodeError, TypeError):
                default_val: list[Any] | dict[str, Any] = [] if name == "args" else {}
                object.__setattr__(self, name, default_val)
                return default_val
        return val


class DLQTaskFilter(BaseModel):
    """Filter parameters for querying Dead Letter Queue tasks."""

    task_name: str | None = Field(default=None, description="Filter by task name")
    exception_type: str | None = Field(default=None, description="Filter by exception type")
    search: str | None = Field(default=None, description="Search in task name, message, or traceback")
    date_from: datetime | None = Field(default=None, description="Filter by failed_at >= date_from")
    date_to: datetime | None = Field(default=None, description="Filter by failed_at <= date_to")


class DLQTargetBase(BaseModel):
    """Base schema for DLQ operations targeting task IDs or task name."""

    task_ids: list[UUID] | None = Field(default=None, description="List of target task UUIDs")
    task_name: str | None = Field(default=None, description="Target Celery task name")


class DLQUpdatePayload(DLQTargetBase):
    """Payload model for modifying single or multiple DLQ task payloads."""

    model_config = ConfigDict(populate_by_name=True)

    args: list[Any] | None = Field(default=None, description="Optional new positional arguments")
    task_kwargs: dict[str, Any] | None = Field(
        default=None, alias="kwargs", description="Optional new keyword arguments"
    )
    queue: str | None = Field(default=None, description="Optional new target queue name")
    merge_kwargs: bool = Field(
        default=True, description="If True, merge kwargs into existing kwargs. If False, overwrite."
    )

    @property
    def kwargs(self) -> dict[str, Any] | None:
        """Alias property for task_kwargs."""
        return self.task_kwargs

    @field_validator("args", mode="before")
    @classmethod
    def parse_args_json(cls, v: Any) -> Any:
        """Parse JSON string args into list if provided as serialized string."""
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return None
            try:
                parsed = json.loads(v_stripped)
                return parsed if isinstance(parsed, list) else [parsed]
            except (json.JSONDecodeError, TypeError):
                return v
        return v

    @field_validator("task_kwargs", mode="before")
    @classmethod
    def parse_kwargs_json(cls, v: Any) -> Any:
        """Parse JSON string kwargs into dict if provided as serialized string."""
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return None
            try:
                parsed = json.loads(v_stripped)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return v
        return v


class DLQRetriggerRequest(DLQTargetBase):
    """Request payload for single or bulk retriggering tasks."""


class DLQDeleteRequest(DLQTargetBase):
    """Request payload for deleting single or multiple tasks."""


class DLQRetriggerResponse(BaseModel):
    """Response model for retriggering a single DLQ task."""

    message: str = Field(..., description="Execution status message")
    old_dlq_id: UUID = Field(..., description="Original DLQ entry UUID")
    new_celery_task_id: str = Field(..., description="Newly dispatched Celery task execution ID")
    task_name: str = Field(..., description="Celery task name")


class DLQActionResponse(BaseModel):
    """Response model for DLQ operations (edit, retrigger, delete)."""

    message: str = Field(..., description="Status summary message")
    affected_count: int = Field(..., description="Number of affected task entries")


class DLQStatsResponse(BaseModel):
    """Summary metrics and statistics for the Dead Letter Queue."""

    total_count: int = 0
    by_task_name: dict[str, int] = Field(default_factory=dict)
    by_exception_type: dict[str, int] = Field(default_factory=dict)
