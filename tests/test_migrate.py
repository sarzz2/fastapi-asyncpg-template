"""
Tests for the migration utility script.
"""

from argparse import Namespace
from unittest.mock import ANY, AsyncMock, MagicMock, mock_open, patch

import asyncpg
import pytest

from migrate import (
    apply_migrations,
    check_all_migrations_applied,
    extract_sequence_number,
    get_sorted_migration_files,
    main,
    parse_migration_sql,
    remove_migration_record,
    run_migration,
    run_specific_migration,
    validate_migration_sequence,
)


@pytest.mark.asyncio
async def test_run_migration_parsing() -> None:
    """
    Verify that SQL files are correctly read and the appropriate section (up/down) is executed.
    """
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock()
    mock_tx.__aexit__ = AsyncMock()
    mock_conn.transaction.return_value = mock_tx

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    sql_content = "-- up\nCREATE TABLE x;\n-- down\nDROP TABLE x;"

    with (
        patch("builtins.open", mock_open(read_data=sql_content)),
        patch("os.path.exists", return_value=True),
        patch("migrate.compute_checksum", return_value="fake_checksum"),
    ):
        # Test UP
        await run_migration(mock_pool, "test.sql", "up", record_state=False)
        mock_conn.execute.assert_called_with("CREATE TABLE x;")

        # Test DOWN
        mock_conn.execute.reset_mock()
        await run_migration(mock_pool, "test.sql", "down", record_state=False)
        mock_conn.execute.assert_called_with("DROP TABLE x;")

        # Test Invalid
        with pytest.raises(ValueError, match="Invalid direction"):
            await run_migration(mock_pool, "test.sql", "invalid")


def test_extract_sequence_number_and_sorting() -> None:
    """
    Verify numeric sequence prefix extraction and natural sorting.
    """
    assert extract_sequence_number("001_users.sql") == 1
    assert extract_sequence_number("010_posts.sql") == 10
    assert extract_sequence_number("invalid.sql") is None

    files = ["010_posts.sql", "001_users.sql", "002_comments.sql"]
    with patch("os.path.exists", return_value=True), patch("os.listdir", return_value=files):
        sorted_files = get_sorted_migration_files("/fake/dir")
        assert sorted_files == ["001_users.sql", "002_comments.sql", "010_posts.sql"]


def test_parse_migration_sql_sections() -> None:
    """
    Verify SQL parsing handles whitespace, comments, and missing blocks correctly.
    """
    sql_with_headers = """
    -- UP
    CREATE TABLE users (id UUID);
    -- DOWN
    DROP TABLE users;
    """
    assert parse_migration_sql(sql_with_headers, "up") == "CREATE TABLE users (id UUID);"
    assert parse_migration_sql(sql_with_headers, "down") == "DROP TABLE users;"

    # Missing down block
    sql_no_down = "CREATE TABLE users (id UUID);"
    assert parse_migration_sql(sql_no_down, "up") == "CREATE TABLE users (id UUID);"
    assert parse_migration_sql(sql_no_down, "down") == ""


def test_validate_migration_sequence_rules() -> None:
    """
    Verify validation rules: duplicate prefixes, gaps, out-of-order, and checksum mismatch.
    """
    # 1. Duplicate prefixes
    with pytest.raises(ValueError, match="Duplicate migration sequence numbers"):
        validate_migration_sequence(["001_a.sql", "001_b.sql"], [])

    # 2. Sequence gaps
    with pytest.raises(ValueError, match="Migration sequence gap detected"):
        validate_migration_sequence(["001_a.sql", "003_c.sql"], [])

    # 3. Out-of-order execution
    with pytest.raises(ValueError, match="Out-of-order migration detected"):
        validate_migration_sequence(
            ["001_a.sql", "002_b.sql", "003_c.sql"],
            applied_migrations=["001_a.sql", "003_c.sql"],
        )

    # 4. Checksum mismatch
    applied_records = {"001_a.sql": {"checksum": "correct_hash"}}
    with (
        patch("os.path.exists", return_value=True),
        patch("migrate.compute_checksum", return_value="modified_hash"),
    ):
        with pytest.raises(ValueError, match="Checksum mismatch for migration"):
            validate_migration_sequence(
                ["001_a.sql"],
                applied_migrations=["001_a.sql"],
                applied_records=applied_records,
                migrations_dir="/fake/dir",
            )


@pytest.mark.asyncio
async def test_apply_migrations_logic() -> None:
    """
    Verify the logic for applying or rolling back multiple migrations based on steps.
    """
    mock_pool = MagicMock()
    migrations = ["001_a.sql", "002_b.sql"]

    with (
        patch("migrate.get_applied_migrations", return_value=migrations),
        patch("migrate.get_applied_migration_records", return_value={}),
        patch("migrate.run_migration", new_callable=AsyncMock) as m_run,
        patch("migrate.remove_migration_record", new_callable=AsyncMock) as m_remove,
        patch("os.listdir", return_value=migrations),
    ):
        # Rollback 1 step
        await apply_migrations(mock_pool, direction="down", steps=1)
        assert m_run.call_count == 1
        assert m_remove.call_count == 1

        # Verify call with ANY for path and specifically checking the filename in the args
        m_run.assert_called_with(mock_pool, ANY, "down", record_state=True)
        assert "002_b.sql" in m_run.call_args[0][1]


@pytest.mark.asyncio
async def test_apply_migrations_dry_run_and_target() -> None:
    """
    Verify dry-run mode and target version application.
    """
    mock_pool = MagicMock()
    files = ["001_a.sql", "002_b.sql", "003_c.sql"]

    with (
        patch("migrate.get_applied_migrations", return_value=["001_a.sql"]),
        patch("migrate.get_applied_migration_records", return_value={}),
        patch("os.listdir", return_value=files),
        patch("builtins.print") as m_print,
    ):
        # Target = 002_b.sql, Dry-run
        processed = await apply_migrations(mock_pool, direction="up", target="002_b.sql", dry_run=True)
        assert processed == ["002_b.sql"]
        m_print.assert_called_with("[DRY-RUN] Would run migration up: 002_b.sql")


@pytest.mark.asyncio
async def test_run_specific_migration_guards() -> None:
    """
    Verify guards that prevent re-applying or rolling back unapplied specific migrations.
    """
    mock_pool = MagicMock()

    with (
        patch("migrate.get_applied_migrations", return_value=["001.sql"]),
        patch("os.path.exists", return_value=True),
        patch("os.path.dirname", return_value="/"),
        patch("builtins.print") as m_print,
    ):
        # Already applied
        await run_specific_migration(mock_pool, "001.sql", "up")
        m_print.assert_called_with("Migration 001.sql is already applied.")

        # Not applied (rollback)
        m_print.reset_mock()
        with patch("migrate.get_applied_migrations", return_value=[]):
            await run_specific_migration(mock_pool, "001.sql", "down")
            m_print.assert_called_with("Migration 001.sql is not applied and cannot be rolled back.")


@pytest.mark.asyncio
async def test_check_all_migrations_applied_scenarios() -> None:
    """
    Verify the migration status check helper.
    """
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with (
        patch("migrate.create_db_pool", return_value=mock_pool),
        patch("os.listdir", return_value=["001.sql"]),
    ):
        # 1. Success
        with (
            patch("migrate.get_applied_migrations", return_value=["001.sql"]),
            patch("migrate.get_applied_migration_records", return_value={}),
        ):
            assert await check_all_migrations_applied() is True

        # 2. Table not found (migrations never run)
        with patch("migrate.get_applied_migrations", side_effect=asyncpg.UndefinedTableError("x")):
            assert await check_all_migrations_applied() is False


@pytest.mark.asyncio
async def test_specific_migration_execution() -> None:
    """
    Verify that specific migrations trigger the correct run and record/remove calls.
    """
    mock_pool = MagicMock()
    with (
        patch("migrate.get_applied_migrations", return_value=[]),
        patch("os.path.exists", return_value=True),
        patch("os.path.dirname", return_value="/"),
        patch("migrate.run_migration", new_callable=AsyncMock) as m_run,
        patch("migrate.record_migration", new_callable=AsyncMock) as m_rec,
        patch("migrate.compute_checksum", return_value="hash123"),
    ):
        await run_specific_migration(mock_pool, "001.sql", "up")
        m_run.assert_called_once()
        m_rec.assert_called_once_with(mock_pool, "001.sql", checksum="hash123")


@pytest.mark.asyncio
async def test_remove_migration_record_sql() -> None:
    """
    Verify the SQL execution for removing a migration record.
    """
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    await remove_migration_record(mock_pool, "test.sql")

    # Check SQL params (first arg is SQL, second is filename)
    call_args = mock_conn.execute.call_args[0]
    assert "DELETE FROM schema_migrations" in call_args[0]
    assert call_args[1] == "test.sql"


@pytest.mark.asyncio
async def test_main_cli_dispatch() -> None:
    """
    Verify that the main() CLI correctly dispatches to apply_migrations or run_specific_migration.
    """
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    # 1. Standard Apply
    args_std = Namespace(direction="up", steps=None, specific=None, target=None, dry_run=False)
    with (
        patch("argparse.ArgumentParser.parse_args", return_value=args_std),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock) as m_table,
        patch("migrate.apply_migrations", new_callable=AsyncMock) as m_apply,
    ):
        await main()
        m_table.assert_called_once()
        m_apply.assert_called_once_with(mock_pool, direction="up", steps=None, dry_run=False, target=None)

    # 2. Specific Migration
    args_spec = Namespace(direction="down", steps=None, specific="spec.sql", target=None, dry_run=False)
    with (
        patch("argparse.ArgumentParser.parse_args", return_value=args_spec),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock),
        patch("migrate.run_specific_migration", new_callable=AsyncMock) as m_spec,
    ):
        await main()
        m_spec.assert_called_once_with(mock_pool, "spec.sql", direction="down", dry_run=False)
