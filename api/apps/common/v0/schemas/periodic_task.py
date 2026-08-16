from datetime import datetime
from uuid import UUID

from celery.schedules import crontab
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.apps.common.constants import IntervalPeriod, ScheduleType


class PeriodicTaskBase(BaseModel):
    """Base schema for periodic tasks."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., description="Unique name identifier for the task schedule")
    task: str = Field(..., description="Full dot-separated python path of the Celery task")
    schedule_type: ScheduleType = Field(ScheduleType.CRONTAB, description="Type of schedule: 'crontab' or 'interval'")
    cron_minute: str | None = Field("*", description="Cron minute (0-59, *, */5, etc.)")
    cron_hour: str | None = Field("*", description="Cron hour (0-23, *, */2, etc.)")
    cron_day_of_week: str | None = Field("*", description="Cron day of week (0-6, mon-sun, *)")
    cron_day_of_month: str | None = Field("*", description="Cron day of month (1-31, *)")
    cron_month_of_year: str | None = Field("*", description="Cron month of year (1-12, *)")
    interval_every: int | None = Field(None, gt=0, description="Interval value (e.g., 5 for every 5 minutes)")
    interval_period: IntervalPeriod | None = Field(
        None, description="Interval period unit ('seconds', 'minutes', 'hours', 'days')"
    )
    args: list = Field(default_factory=list, description="Positional arguments for the task")
    task_kwargs: dict = Field(default_factory=dict, alias="kwargs", description="Keyword arguments for the task")
    enabled: bool = Field(True, description="Whether the schedule is currently enabled")

    @property
    def kwargs(self) -> dict:
        """Alias property for task_kwargs."""
        return self.task_kwargs

    @model_validator(mode="after")
    def validate_schedule_fields(self) -> "PeriodicTaskBase":
        """Validate schedule consistency for crontab and interval types."""
        if self.schedule_type == ScheduleType.INTERVAL:
            if not self.interval_every or self.interval_every <= 0:
                raise ValueError("interval_every must be a positive integer for interval schedule")
            if not self.interval_period:
                raise ValueError("interval_period is required for interval schedule")
        elif self.schedule_type == ScheduleType.CRONTAB:
            try:
                crontab(
                    minute=self.cron_minute or "*",
                    hour=self.cron_hour or "*",
                    day_of_week=self.cron_day_of_week or "*",
                    day_of_month=self.cron_day_of_month or "*",
                    month_of_year=self.cron_month_of_year or "*",
                )
            except Exception as err:
                raise ValueError(f"Invalid crontab expression: {err}") from err
        return self


class PeriodicTaskCreate(PeriodicTaskBase):
    """Schema for creating a periodic task."""


class PeriodicTaskUpdate(BaseModel):
    """Schema for updating an existing periodic task."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    task: str | None = None
    schedule_type: ScheduleType | None = None
    cron_minute: str | None = None
    cron_hour: str | None = None
    cron_day_of_week: str | None = None
    cron_day_of_month: str | None = None
    cron_month_of_year: str | None = None
    interval_every: int | None = Field(None, gt=0, description="Interval value (must be > 0)")
    interval_period: IntervalPeriod | None = None
    args: list | None = None
    task_kwargs: dict | None = Field(None, alias="kwargs")
    enabled: bool | None = None

    @property
    def kwargs(self) -> dict | None:
        """Alias property for task_kwargs."""
        return self.task_kwargs

    @model_validator(mode="after")
    def validate_update_schedule_fields(self) -> "PeriodicTaskUpdate":
        """Validate schedule fields for partial update payloads."""
        if self.interval_every is not None and self.interval_every <= 0:
            raise ValueError("interval_every must be a positive integer")

        if any(
            v is not None
            for v in [
                self.cron_minute,
                self.cron_hour,
                self.cron_day_of_week,
                self.cron_day_of_month,
                self.cron_month_of_year,
            ]
        ):
            try:
                crontab(
                    minute=self.cron_minute or "*",
                    hour=self.cron_hour or "*",
                    day_of_week=self.cron_day_of_week or "*",
                    day_of_month=self.cron_day_of_month or "*",
                    month_of_year=self.cron_month_of_year or "*",
                )
            except Exception as err:
                raise ValueError(f"Invalid crontab expression: {err}") from err
        return self


class PeriodicTaskResponse(PeriodicTaskBase):
    """Response schema for periodic tasks."""

    id: UUID
    last_run_at: datetime | None = None
    total_run_count: int = 0
    created_at: datetime
    updated_at: datetime


class ManualTaskTriggerRequest(BaseModel):
    """Schema for manually triggering a Celery task on demand."""

    model_config = ConfigDict(populate_by_name=True)

    task_name: str = Field(
        ...,
        description="Celery task name (e.g. 'api.tasks.delete_old_logs.delete_old_logs')",
    )
    args: list = Field(default_factory=list, description="Positional arguments for task execution")
    task_kwargs: dict = Field(default_factory=dict, alias="kwargs", description="Keyword arguments for execution")

    @property
    def kwargs(self) -> dict:
        """Alias property for task_kwargs."""
        return self.task_kwargs


class ManualTaskTriggerResponse(BaseModel):
    """Response schema after manually dispatching a task."""

    message: str
    task_id: str
    task_name: str
