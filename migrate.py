import argparse
import os
from typing import List, Optional

import asyncpg

from api.core.config import settings


async def create_migrations_table(pool: asyncpg.pool.Pool) -> None:
    """
    Create the schema_migrations table to track applied migrations.
    Args:
        pool: The asyncpg connection pool.
    """
    async with pool.acquire() as connection:
        await connection.execute(
            """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
        )


async def get_applied_migrations(pool: asyncpg.pool.Pool) -> List[str]:
    """
    Fetch the list of applied migrations from the schema_migrations table.
    Args:
        pool: The asyncpg connection pool.
    Returns:
        List[str]: A list of applied migration versions.
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch("SELECT version FROM schema_migrations ORDER BY version;")
    return [row["version"] for row in rows]


async def record_migration(pool: asyncpg.pool.Pool, version: str) -> None:
    """
    Record a migration as applied in the schema_migrations table.
    Args:
        pool: The asyncpg connection pool.
        version: The version of the migration to record.
    """
    async with pool.acquire() as connection:
        await connection.execute("INSERT INTO schema_migrations (version) VALUES ($1);", version)


async def remove_migration_record(pool: asyncpg.pool.Pool, version: str) -> None:
    """
    Remove a migration record from the schema_migrations table.
    Args:
        pool: The asyncpg connection pool.
        version: The version of the migration to remove.
    """
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM schema_migrations WHERE version = $1;", version)


async def run_migration(pool: asyncpg.pool.Pool, filename: str, direction: str) -> None:
    """
    Run a migration script in the specified direction ('up' or 'down').
    Args:
        pool: The asyncpg connection pool.
        filename: The path to the migration script.
        direction: The direction of the migration ('up' or 'down').
    """
    with open(filename, "r") as f:
        sql = f.read()

    # Split the file into 'up' and 'down' sections
    sections = sql.split("-- down")

    if direction == "up":
        sql_to_execute = sections[0].split("-- up")[1].strip()
    elif direction == "down":
        sql_to_execute = sections[1].strip() if len(sections) > 1 else ""
    else:
        raise ValueError("Invalid direction: choose 'up' or 'down'.")

    async with pool.acquire() as connection:
        await connection.execute(sql_to_execute)


async def apply_migrations(pool: asyncpg.pool.Pool, direction: str = "up", steps: Optional[int] = None) -> None:
    """
    Apply or rollback migrations up to a specific number of steps or to the latest state.
    Args:
        pool: The asyncpg connection pool.
        direction: The direction of the migration ('up' or 'down').
        steps: The number of steps to migrate. If None, migrate all pending migrations.
    """
    migrations_dir = os.path.join("api/", "migrations")
    files: list[str] = sorted(os.listdir(migrations_dir))

    applied_migrations = await get_applied_migrations(pool)
    if direction == "down":
        if steps is None:
            steps = 1
        files = list(reversed(files))

    if steps is None:
        # Apply all pending migrations
        migrations_to_apply = [
            f
            for f in files
            if f.endswith(".sql") and (f not in applied_migrations if direction == "up" else f in applied_migrations)
        ]
    else:
        # Apply a specific number of steps
        migrations_to_apply = [
            f
            for f in files
            if f.endswith(".sql") and (f not in applied_migrations if direction == "up" else f in applied_migrations)
        ][:steps]

    for filename in migrations_to_apply:
        print(f"Running migration {direction}: {filename}")
        await run_migration(pool, os.path.join(migrations_dir, filename), direction)
        if direction == "up":
            await record_migration(pool, filename)
        elif direction == "down":
            await remove_migration_record(pool, filename)


async def run_specific_migration(pool: asyncpg.pool.Pool, migration_name: str, direction: str = "up") -> None:
    """
    Run a specific migration file in the specified direction.
    Args:
        pool: The asyncpg connection pool.
        migration_name: The name of the migration file to run.
        direction: The direction of the migration ('up' or 'down').
    """
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    migration_path = os.path.join(migrations_dir, migration_name)

    if not os.path.exists(migration_path):
        raise FileNotFoundError(f"Migration {migration_name} does not exist.")

    if direction == "up":
        applied_migrations = await get_applied_migrations(pool)
        if migration_name in applied_migrations:
            print(f"Migration {migration_name} is already applied.")
            return
        await run_migration(pool, migration_path, "up")
        await record_migration(pool, migration_name)

    elif direction == "down":
        applied_migrations = await get_applied_migrations(pool)
        if migration_name not in applied_migrations:
            print(f"Migration {migration_name} is not applied and cannot be rolled back.")
            return
        await run_migration(pool, migration_path, "down")
        await remove_migration_record(pool, migration_name)


async def check_all_migrations_applied() -> bool:
    """
    Check if all migrations have been applied.
    Returns:
        bool: True if all migrations have been applied, False otherwise.
    """
    migrations_dir = os.path.join("api/", "migrations")
    files = sorted(os.listdir(migrations_dir))

    pool: asyncpg.pool.Pool = await create_db_pool()
    try:
        applied_migrations = await get_applied_migrations(pool)
        return set(applied_migrations) == set(files)
    except asyncpg.UndefinedTableError:
        return False
    finally:
        await pool.close()


async def create_db_pool() -> asyncpg.pool.Pool:
    """
    Create and return an asyncpg connection pool.
    Returns:
        The asyncpg connection pool.
    """
    return await asyncpg.create_pool(settings.PRIMARY_DATABASE_URL, max_inactive_connection_lifetime=3)


async def main() -> None:
    """
    Main function to handle command-line migration operations.
    """
    parser = argparse.ArgumentParser(description="Manage database migrations.")
    parser.add_argument(
        "direction",
        nargs="?",
        default="up",
        choices=["up", "down"],
        help="Migration direction: 'up' to apply or 'down' to rollback (default: 'up').",
    )
    parser.add_argument(
        "steps",
        nargs="?",
        type=int,
        default=None,
        help="Number of steps to migrate up or down.",
    )
    parser.add_argument("--specific", "-s", type=str, help="Run a specific migration file.")

    args = parser.parse_args()

    db_pool = await create_db_pool()
    await create_migrations_table(db_pool)
    if args.specific:
        await run_specific_migration(db_pool, args.specific, direction=args.direction)
    else:
        await apply_migrations(db_pool, direction=args.direction, steps=args.steps)

    await db_pool.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
