import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import asyncpg
import redis
from celery.beat import ScheduleEntry, Scheduler
from celery.schedules import crontab, schedule

from api.apps.common.constants import CeleryRedisKeys, IntervalPeriod, ScheduleType
from api.core.config import settings

logger = logging.getLogger("celery.beat")


def parse_schedule(task_row: dict[str, Any]) -> Any:
    """
    Parse database record into a Celery schedule object (crontab or interval schedule).

    Args:
        task_row (dict[str, Any]): Periodic task database row record.

    Returns:
        Any: Celery crontab or schedule object.
    """
    schedule_type = str(task_row.get("schedule_type", ScheduleType.CRONTAB.value))

    if schedule_type == ScheduleType.INTERVAL.value:
        every = int(task_row.get("interval_every") or 60)
        period = str(task_row.get("interval_period", IntervalPeriod.SECONDS.value))

        seconds_multiplier = {
            IntervalPeriod.SECONDS.value: 1,
            IntervalPeriod.MINUTES.value: 60,
            IntervalPeriod.HOURS.value: 3600,
            IntervalPeriod.DAYS.value: 86400,
        }.get(period, 60)

        total_seconds = every * seconds_multiplier
        return schedule(run_every=timedelta(seconds=total_seconds))

    # Default to crontab
    return crontab(
        minute=task_row.get("cron_minute") or "*",
        hour=task_row.get("cron_hour") or "*",
        day_of_week=task_row.get("cron_day_of_week") or "*",
        day_of_month=task_row.get("cron_day_of_month") or "*",
        month_of_year=task_row.get("cron_month_of_year") or "*",
    )


class DatabaseBeatScheduler(Scheduler):
    """
    A custom Celery Beat Scheduler that loads periodic schedules dynamically from
    PostgreSQL (`periodic_tasks` table) and uses Redis for caching and instant sync updates.
    """

    max_interval = 5

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._last_version: str | None = None
        self._redis_client: redis.Redis | None = None
        super().__init__(*args, **kwargs)

    @property
    def redis_client(self) -> redis.Redis:
        """Lazy initialization of synchronous Redis client."""
        if self._redis_client is None:
            self._redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
        return self._redis_client

    def setup_schedule(self) -> None:
        """Initialize schedule entries on startup."""
        logger.info("DatabaseBeatScheduler: Initializing beat schedule...")
        self.install_default_entries(self.schedule)
        self.reload_schedule()

    def fetch_tasks_from_db(self) -> list[dict[str, Any]]:
        """
        Fetch all enabled periodic tasks directly from PostgreSQL.

        Returns:
            list[dict[str, Any]]: List of task row dictionaries.
        """

        async def _async_fetch() -> list[dict[str, Any]]:
            conn = await asyncpg.connect(settings.PRIMARY_DATABASE_URL)
            try:
                query = """
                    SELECT *
                    FROM periodic_tasks
                    WHERE enabled = TRUE;
                """
                rows = await conn.fetch(query)
                results: list[dict[str, Any]] = []
                for row in rows:
                    item = dict(row)
                    item["args"] = json.loads(item["args"]) if isinstance(item["args"], str) else (item["args"] or [])
                    item["kwargs"] = (
                        json.loads(item["kwargs"]) if isinstance(item["kwargs"], str) else (item["kwargs"] or {})
                    )
                    results.append(item)
                return results
            finally:
                await conn.close()

        try:
            return asyncio.run(_async_fetch())
        except Exception as err:  # pylint: disable=broad-except
            logger.error("DatabaseBeatScheduler: Error fetching periodic tasks from DB: %s", err)
            return []

    def reload_schedule(self) -> None:
        """Reload schedules from Redis cache or database."""
        tasks_data: list[dict[str, Any]] = []

        try:
            r = self.redis_client
            cached_json = r.get(CeleryRedisKeys.SCHEDULE_DATA.value)
            if cached_json:
                tasks_data = json.loads(cached_json)
                logger.info("DatabaseBeatScheduler: Loaded %d periodic tasks from Redis cache.", len(tasks_data))
            else:
                tasks_data = self.fetch_tasks_from_db()
                if tasks_data:
                    r.set(CeleryRedisKeys.SCHEDULE_DATA.value, json.dumps(tasks_data), ex=3600)
                logger.info("DatabaseBeatScheduler: Loaded %d periodic tasks from PostgreSQL.", len(tasks_data))

            raw_ver = r.get(CeleryRedisKeys.SCHEDULE_VERSION.value)
            self._last_version = raw_ver.decode("utf-8") if isinstance(raw_ver, bytes) else raw_ver
        except Exception as err:  # pylint: disable=broad-except
            logger.warning("DatabaseBeatScheduler: Redis read error (%s), falling back to DB.", err)
            tasks_data = self.fetch_tasks_from_db()

        # Update self.schedule entries
        new_schedule: dict[str, ScheduleEntry] = {}
        for task_info in tasks_data:
            name = task_info["name"]
            try:
                sched_obj = parse_schedule(task_info)
                entry = ScheduleEntry(
                    name=name,
                    task=task_info["task"],
                    schedule=sched_obj,
                    args=task_info.get("args") or [],
                    kwargs=task_info.get("kwargs") or {},
                    app=self.app,
                )
                new_schedule[name] = entry
            except Exception as parse_err:  # pylint: disable=broad-except
                logger.error("DatabaseBeatScheduler: Failed to parse schedule for task '%s': %s", name, parse_err)

        self.schedule.clear()
        self.schedule.update(new_schedule)
        logger.info("DatabaseBeatScheduler: Active schedule updated with %d tasks.", len(self.schedule))

    def tick(self, *args: Any, **kwargs: Any) -> float:  # pylint: disable=arguments-differ
        """
        Periodically invoked by Celery Beat loop. Checks for version updates in Redis
        and reloads schedule if version changed.

        Returns:
            float: Wait time interval before next tick.
        """
        try:
            current_version = self.redis_client.get(CeleryRedisKeys.SCHEDULE_VERSION.value)
            if current_version != self._last_version:
                logger.info(
                    "DatabaseBeatScheduler: Schedule version change detected (%s -> %s). Reloading...",
                    self._last_version,
                    current_version,
                )
                self.reload_schedule()
        except Exception as err:  # pylint: disable=broad-except
            logger.warning("DatabaseBeatScheduler: Check version failed: %s", err)

        return float(super().tick(*args, **kwargs))
