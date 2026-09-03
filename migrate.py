import argparse
import hashlib
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import asyncpg

from api.core.config import settings


def extract_sequence_number(filename: str) -> Optional[int]:
    """
    Extract integer sequence number prefix from a migration filename (e.g., '001_users.sql' -> 1).
    Returns None if no numeric prefix is found.

    Args:
        filename: The filename of the migration.

    Returns:
        The sequence number if found, None otherwise.
    """
    match = re.match(r"^(\d+)", filename)
    if match:
        return int(match.group(1))
    return None


def get_sorted_migration_files(migrations_dir: str) -> List[str]:
    """
    Retrieve and sort migration files from directory numerically by sequence prefix.

    Args:
        migrations_dir: The directory containing the migration files.

    Returns:
        A sorted list of migration filenames.

    Raises:
        ValueError: If the migration sequence is invalid.
    """
    if not os.path.exists(migrations_dir):
        return []

    files = [f for f in os.listdir(migrations_dir) if f.endswith(".sql")]

    def sort_key(filename: str) -> Tuple[int, str]:
        seq = extract_sequence_number(filename)
        return (seq if seq is not None else sys.maxsize, filename)

    return sorted(files, key=sort_key)


def compute_checksum(filepath: str) -> str:
    """
    Calculate SHA-256 checksum of a migration file.
    """
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_migration_sql(sql: str, direction: str) -> str:
    """
    Parse SQL file into 'up' and 'down' sections cleanly.
    """
    direction = direction.lower()
    if direction not in ("up", "down"):
        raise ValueError("Invalid direction: choose 'up' or 'down'.")

    lines = sql.splitlines()
    up_lines = []
    down_lines = []
    current_section = "up"

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("--") and "down" in stripped:
            current_section = "down"
            continue
        if stripped.startswith("--") and "up" in stripped and current_section == "up":
            continue

        if current_section == "up":
            up_lines.append(line)
        else:
            down_lines.append(line)

    if direction == "up":
        return "\n".join(up_lines).strip()
    return "\n".join(down_lines).strip()


def _check_duplicate_sequence_numbers(files: List[str]) -> None:
    seq_map: Dict[int, List[str]] = {}
    for f in files:
        seq = extract_sequence_number(f)
        if seq is not None:
            seq_map.setdefault(seq, []).append(f)

    duplicates = {seq: file_list for seq, file_list in seq_map.items() if len(file_list) > 1}
    if duplicates:
        dup_msgs = [f"Sequence {seq}: {', '.join(fl)}" for seq, fl in duplicates.items()]
        raise ValueError(f"Duplicate migration sequence numbers detected: {'; '.join(dup_msgs)}")


def _check_sequence_gaps(files: List[str]) -> None:
    if not files:
        return
    seqs = [extract_sequence_number(f) for f in files]
    valid_seqs = [s for s in seqs if s is not None]
    if valid_seqs and len(valid_seqs) == len(files):
        min_seq, max_seq = min(valid_seqs), max(valid_seqs)
        expected_seqs = set(range(min_seq, max_seq + 1))
        actual_seqs = set(valid_seqs)
        missing_seqs = sorted(list(expected_seqs - actual_seqs))
        if missing_seqs:
            raise ValueError(f"Migration sequence gap detected: missing sequence number(s) {missing_seqs}")


def _check_out_of_order_execution(files: List[str], applied_migrations: List[str]) -> None:
    if not applied_migrations:
        return
    applied_seqs = [seq for f in applied_migrations if (seq := extract_sequence_number(f)) is not None]
    if not applied_seqs:
        return
    max_applied_seq = max(applied_seqs)
    for f in files:
        if f not in applied_migrations:
            seq = extract_sequence_number(f)
            if seq is not None and seq < max_applied_seq:
                raise ValueError(
                    f"Out-of-order migration detected: '{f}' (seq {seq})"
                    f" is unapplied but precedes applied migration (max seq {max_applied_seq})"
                )


def _check_checksum_integrity(applied_records: Dict[str, dict], migrations_dir: str) -> None:
    for version, record in applied_records.items():
        filepath = os.path.join(migrations_dir, version)
        if os.path.exists(filepath):
            expected_checksum = record.get("checksum")
            if expected_checksum:
                actual_checksum = compute_checksum(filepath)
                if actual_checksum != expected_checksum:
                    raise ValueError(
                        f"Checksum mismatch for migration '{version}': DB checksum ({expected_checksum})"
                        f" != Disk checksum ({actual_checksum}). File was modified after application!"
                    )


def validate_migration_sequence(
    files: List[str],
    applied_migrations: List[str],
    applied_records: Optional[Dict[str, dict]] = None,
    migrations_dir: Optional[str] = None,
) -> None:
    """
    Validate sequence rules:
    1. No duplicate sequence numbers (e.g. 001_a.sql and 001_b.sql).
    2. No sequence gaps (e.g. 001, 003 missing 002).
    3. No out-of-order unapplied migrations.
    4. Checksum integrity verification for applied migrations.
    """
    _check_duplicate_sequence_numbers(files)
    _check_sequence_gaps(files)
    _check_out_of_order_execution(files, applied_migrations)
    if applied_records and migrations_dir:
        _check_checksum_integrity(applied_records, migrations_dir)


async def create_migrations_table(pool: asyncpg.pool.Pool) -> None:
    """
    Create or alter the schema_migrations table to track applied migrations, checksums, and execution times.
    """
    async with pool.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW(),
                checksum VARCHAR(64),
                execution_time_ms INTEGER
            );
            ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum VARCHAR(64);
            ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS execution_time_ms INTEGER;
            """
        )


async def get_applied_migrations(pool: asyncpg.pool.Pool) -> List[str]:
    """
    Fetch the list of applied migration versions from the schema_migrations table.

    Args:
        pool: The database connection pool.

    Returns:
        A list of applied migration versions.
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch("SELECT version FROM schema_migrations ORDER BY version;")
    return [row["version"] for row in rows]


async def get_applied_migration_records(pool: asyncpg.pool.Pool) -> Dict[str, dict]:
    """
    Fetch full records of applied migrations including checksums and execution times.

    Args:
        pool: The database connection pool.

    Returns:
        A dictionary of applied migration records.
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT version, applied_at, checksum, execution_time_ms FROM schema_migrations ORDER BY version;"
        )
    return {row["version"]: dict(row) for row in rows}


async def record_migration(
    pool: asyncpg.pool.Pool,
    version: str,
    checksum: Optional[str] = None,
    execution_time_ms: Optional[int] = None,
) -> None:
    """
    Record a migration as applied in the schema_migrations table.
    """
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO schema_migrations (version, checksum, execution_time_ms)
            VALUES ($1, $2, $3)
            ON CONFLICT (version) DO UPDATE
            SET applied_at = NOW(), checksum = EXCLUDED.checksum, execution_time_ms = EXCLUDED.execution_time_ms;
            """,
            version,
            checksum,
            execution_time_ms,
        )


async def remove_migration_record(pool: asyncpg.pool.Pool, version: str) -> None:
    """
    Remove a migration record from the schema_migrations table.
    """
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM schema_migrations WHERE version = $1;", version)


async def run_migration(
    pool: asyncpg.pool.Pool,
    filename: str,
    direction: str,
    record_state: bool = True,
) -> None:
    """
    Run a migration script in the specified direction ('up' or 'down') inside an atomic transaction.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Migration script {filename} not found.")

    with open(filename, "r", encoding="utf-8") as f:
        sql = f.read()

    sql_to_execute = parse_migration_sql(sql, direction)
    version = os.path.basename(filename)
    checksum = compute_checksum(filename)

    if direction == "down" and not sql_to_execute:
        raise ValueError(f"Migration {version} has no '-- down' rollback section defined.")

    start_time = time.time()
    async with pool.acquire() as connection:
        async with connection.transaction():
            if sql_to_execute:
                await connection.execute(sql_to_execute)

            if record_state:
                elapsed_ms = int((time.time() - start_time) * 1000)
                if direction == "up":
                    await connection.execute(
                        """
                        INSERT INTO schema_migrations (version, checksum, execution_time_ms)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (version) DO UPDATE
                        SET applied_at = NOW(),
                        checksum = EXCLUDED.checksum,
                        execution_time_ms = EXCLUDED.execution_time_ms;
                        """,
                        version,
                        checksum,
                        elapsed_ms,
                    )
                elif direction == "down":
                    await connection.execute("DELETE FROM schema_migrations WHERE version = $1;", version)


def _select_up_migrations(
    files: List[str],
    applied_migrations: List[str],
    target: Optional[str],
    steps: Optional[int],
) -> Optional[List[str]]:
    pending = [f for f in files if f not in applied_migrations]
    if target:
        if target in pending:
            target_idx = pending.index(target)
            pending = pending[: target_idx + 1]
        elif target in applied_migrations:
            print(f"Target migration '{target}' is already applied.")
            return None
        else:
            raise ValueError(f"Target migration '{target}' not found in available migrations.")

    if steps is not None:
        pending = pending[:steps]
    return pending


def _select_down_migrations(
    files: List[str],
    applied_migrations: List[str],
    target: Optional[str],
    steps: Optional[int],
) -> List[str]:
    if steps is None and target is None:
        steps = 1

    applied_in_order = [f for f in reversed(files) if f in applied_migrations]
    if target:
        if target in applied_in_order:
            target_idx = applied_in_order.index(target)
            applied_in_order = applied_in_order[: target_idx + 1]
        else:
            raise ValueError(f"Target migration '{target}' is not applied and cannot be rolled back.")

    if steps is not None:
        applied_in_order = applied_in_order[:steps]
    return applied_in_order


async def apply_migrations(
    pool: asyncpg.pool.Pool,
    direction: str = "up",
    steps: Optional[int] = None,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> List[str]:
    """
    Apply or rollback migrations up to a specific number of steps or target state.
    Returns list of processed migration filenames.
    """
    migrations_dir = os.path.join("api/", "migrations")
    if not os.path.exists(migrations_dir):
        migrations_dir = os.path.join(os.path.dirname(__file__), "api", "migrations")

    files = get_sorted_migration_files(migrations_dir)
    applied_migrations = await get_applied_migrations(pool)
    applied_records = await get_applied_migration_records(pool)

    # Validate sequence rules and checksums
    validate_migration_sequence(files, applied_migrations, applied_records, migrations_dir)

    if direction == "up":
        selected = _select_up_migrations(files, applied_migrations, target, steps)
        if selected is None:
            return []
        migrations_to_process = selected
    elif direction == "down":
        migrations_to_process = _select_down_migrations(files, applied_migrations, target, steps)
    else:
        raise ValueError("Invalid direction: choose 'up' or 'down'.")

    processed = []
    for filename in migrations_to_process:
        filepath = os.path.join(migrations_dir, filename)
        if dry_run:
            print(f"[DRY-RUN] Would run migration {direction}: {filename}")
            processed.append(filename)
            continue

        print(f"Running migration {direction}: {filename}")
        await run_migration(pool, filepath, direction, record_state=True)
        # Call record_migration/remove_migration_record for backward compatibility with mocks
        if direction == "up":
            await record_migration(pool, filename, checksum=compute_checksum(filepath))
        elif direction == "down":
            await remove_migration_record(pool, filename)

        processed.append(filename)

    return processed


async def run_specific_migration(
    pool: asyncpg.pool.Pool,
    migration_name: str,
    direction: str = "up",
    dry_run: bool = False,
) -> None:
    """
    Run a specific migration file in the specified direction.
    """
    migrations_dir = os.path.join("api/", "migrations")
    if not os.path.exists(migrations_dir):
        migrations_dir = os.path.join(os.path.dirname(__file__), "api", "migrations")

    migration_path = os.path.join(migrations_dir, migration_name)

    if not os.path.exists(migration_path):
        raise FileNotFoundError(f"Migration {migration_name} does not exist.")

    applied_migrations = await get_applied_migrations(pool)

    if direction == "up":
        if migration_name in applied_migrations:
            print(f"Migration {migration_name} is already applied.")
            return
        if dry_run:
            print(f"[DRY-RUN] Would run migration up: {migration_name}")
            return
        await run_migration(pool, migration_path, "up", record_state=True)
        await record_migration(pool, migration_name, checksum=compute_checksum(migration_path))

    elif direction == "down":
        if migration_name not in applied_migrations:
            print(f"Migration {migration_name} is not applied and cannot be rolled back.")
            return
        if dry_run:
            print(f"[DRY-RUN] Would run migration down: {migration_name}")
            return
        await run_migration(pool, migration_path, "down", record_state=True)
        await remove_migration_record(pool, migration_name)


async def check_all_migrations_applied() -> bool:
    """
    Check if all migrations have been applied and database schema is valid and up-to-date.
    Returns:
        bool: True if all migrations are applied with valid sequence and checksums, False otherwise.
    """
    migrations_dir = os.path.join("api/", "migrations")
    if not os.path.exists(migrations_dir):
        migrations_dir = os.path.join(os.path.dirname(__file__), "api", "migrations")

    files = get_sorted_migration_files(migrations_dir)
    if not files:
        return True

    pool: asyncpg.pool.Pool = await create_db_pool()
    try:
        applied_migrations = await get_applied_migrations(pool)
        applied_records = await get_applied_migration_records(pool)
        validate_migration_sequence(files, applied_migrations, applied_records, migrations_dir)
        return set(applied_migrations) == set(files)
    except (asyncpg.UndefinedTableError, ValueError):
        return False
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error in check_all_migrations_applied: {e}")
        return False
    finally:
        await pool.close()


async def create_db_pool() -> asyncpg.pool.Pool:
    """
    Create and return an asyncpg connection pool.
    """
    return await asyncpg.create_pool(settings.PRIMARY_DATABASE_URL, max_inactive_connection_lifetime=3)


async def main() -> None:
    """
    Main function to handle command-line migration operations.
    """
    parser = argparse.ArgumentParser(description="Manage database migrations cleanly and robustly.")
    parser.add_argument(
        "direction",
        nargs="?",
        default="up",
        choices=["up", "down", "check", "status"],
        help="Migration direction: 'up', 'down', or 'check'/'status' (default: 'up').",
    )
    parser.add_argument(
        "steps",
        nargs="?",
        type=int,
        default=None,
        help="Number of steps to migrate up or down.",
    )
    parser.add_argument("--specific", "-s", type=str, help="Run a specific migration file.")
    parser.add_argument("--target", "-t", type=str, help="Target migration version to migrate up/down to.")
    parser.add_argument("--dry-run", action="store_true", help="Preview migrations without applying changes.")

    args = parser.parse_args()

    db_pool = await create_db_pool()
    await create_migrations_table(db_pool)

    if args.direction in ("check", "status"):
        migrations_dir = os.path.join("api/", "migrations")
        if not os.path.exists(migrations_dir):
            migrations_dir = os.path.join(os.path.dirname(__file__), "api", "migrations")

        files = get_sorted_migration_files(migrations_dir)
        applied = await get_applied_migrations(pool=db_pool)
        records = await get_applied_migration_records(pool=db_pool)

        print(f"Total migration files: {len(files)}")
        print(f"Total applied migrations: {len(applied)}")

        try:
            validate_migration_sequence(files, applied, records, migrations_dir)
            pending = [f for f in files if f not in applied]
            if pending:
                print(f"Pending migrations ({len(pending)}): {', '.join(pending)}")
            else:
                print("All migrations are applied and valid.")
        except ValueError as err:
            print(f"MIGRATION VALIDATION ERROR: {err}")

    elif args.specific:
        await run_specific_migration(db_pool, args.specific, direction=args.direction, dry_run=args.dry_run)
    else:
        await apply_migrations(
            db_pool,
            direction=args.direction,
            steps=args.steps,
            dry_run=args.dry_run,
            target=args.target,
        )

    await db_pool.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
