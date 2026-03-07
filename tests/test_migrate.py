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
    main,
    remove_migration_record,
    run_migration,
    run_specific_migration,
)


@pytest.mark.asyncio
async def test_run_migration_parsing() -> None:
    """
    Verify that SQL files are correctly read and the appropriate section (up/down) is executed.
    """
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    sql_content = "-- up\nCREATE TABLE x;\n-- down\nDROP TABLE x;"

    with patch("builtins.open", mock_open(read_data=sql_content)):
        # Test UP
        await run_migration(mock_pool, "test.sql", "up")
        mock_conn.execute.assert_called_with("CREATE TABLE x;")

        # Test DOWN
        mock_conn.execute.reset_mock()
        await run_migration(mock_pool, "test.sql", "down")
        mock_conn.execute.assert_called_with("DROP TABLE x;")

        # Test Invalid
        with pytest.raises(ValueError, match="Invalid direction"):
            await run_migration(mock_pool, "test.sql", "invalid")


@pytest.mark.asyncio
async def test_apply_migrations_logic() -> None:
    """
    Verify the logic for applying or rolling back multiple migrations based on steps.
    """
    mock_pool = MagicMock()
    migrations = ["001_a.sql", "002_b.sql"]

    with (
        patch("migrate.get_applied_migrations", return_value=migrations),
        patch("migrate.run_migration", new_callable=AsyncMock) as m_run,
        patch("migrate.remove_migration_record", new_callable=AsyncMock) as m_remove,
        patch("os.listdir", return_value=migrations),
    ):
        # Rollback 1 step
        await apply_migrations(mock_pool, direction="down", steps=1)
        assert m_run.call_count == 1
        assert m_remove.call_count == 1

        # Verify call with ANY for path and specifically checking the filename in the args
        m_run.assert_called_with(mock_pool, ANY, "down")
        assert "002_b.sql" in m_run.call_args[0][1]


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
        with patch("migrate.get_applied_migrations", return_value=["001.sql"]):
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
    ):
        await run_specific_migration(mock_pool, "001.sql", "up")
        m_run.assert_called_once()
        m_rec.assert_called_once_with(mock_pool, "001.sql")


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
    args_std = Namespace(direction="up", steps=None, specific=None)
    with (
        patch("argparse.ArgumentParser.parse_args", return_value=args_std),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock) as m_table,
        patch("migrate.apply_migrations", new_callable=AsyncMock) as m_apply,
    ):
        await main()
        m_table.assert_called_once()
        m_apply.assert_called_once_with(mock_pool, direction="up", steps=None)

    # 2. Specific Migration
    args_spec = Namespace(direction="down", steps=None, specific="spec.sql")
    with (
        patch("argparse.ArgumentParser.parse_args", return_value=args_spec),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock),
        patch("migrate.run_specific_migration", new_callable=AsyncMock) as m_spec,
    ):
        await main()
        m_spec.assert_called_once_with(mock_pool, "spec.sql", direction="down")
