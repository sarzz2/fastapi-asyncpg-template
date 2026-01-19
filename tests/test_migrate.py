# pylint: disable=redefined-outer-name
"""Tests for migrate.py coverage gaps."""

from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_run_migration_up() -> None:
    """Test run_migration with 'up' direction."""

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    sql_content = """
-- up
CREATE TABLE test_table (id INT);
-- down
DROP TABLE test_table;
"""

    with patch(
        "builtins.open",
        return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=sql_content)))),
    ):
        await run_migration(mock_pool, "test.sql", "up")

    mock_conn.execute.assert_called_once()
    call_arg = mock_conn.execute.call_args[0][0]
    assert "CREATE TABLE" in call_arg


@pytest.mark.asyncio
async def test_run_migration_down() -> None:
    """Test run_migration with 'down' direction."""

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    sql_content = """
-- up
CREATE TABLE test_table (id INT);
-- down
DROP TABLE test_table;
"""

    with patch(
        "builtins.open",
        return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=sql_content)))),
    ):
        await run_migration(mock_pool, "test.sql", "down")

    mock_conn.execute.assert_called_once()
    call_arg = mock_conn.execute.call_args[0][0]
    assert "DROP TABLE" in call_arg


@pytest.mark.asyncio
async def test_run_migration_invalid_direction() -> None:
    """Test run_migration with invalid direction."""

    mock_pool = MagicMock()
    sql_content = "-- up\nCREATE TABLE x;\n-- down\nDROP TABLE x;"

    with patch(
        "builtins.open",
        return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=sql_content)))),
    ):
        with pytest.raises(ValueError, match="Invalid direction"):
            await run_migration(mock_pool, "test.sql", "invalid")


@pytest.mark.asyncio
async def test_apply_migrations_down_with_steps() -> None:
    """Test apply_migrations down with specific steps."""

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with (
        patch("migrate.get_applied_migrations", return_value=["001_test.sql", "002_test.sql"]),
        patch("migrate.run_migration", new_callable=AsyncMock) as mock_run,
        patch("migrate.remove_migration_record", new_callable=AsyncMock) as mock_remove,
        patch("os.listdir", return_value=["001_test.sql", "002_test.sql"]),
    ):
        await apply_migrations(mock_pool, direction="down", steps=1)

        # Should only rollback 1 migration
        assert mock_run.call_count == 1
        assert mock_remove.call_count == 1


@pytest.mark.asyncio
async def test_run_specific_migration_up_already_applied() -> None:
    """Test run_specific_migration when already applied."""

    mock_pool = MagicMock()

    with (
        patch("migrate.get_applied_migrations", return_value=["001_test.sql"]),
        patch("os.path.exists", return_value=True),
        patch("os.path.dirname", return_value="/path"),
        patch("builtins.print") as mock_print,
    ):
        await run_specific_migration(mock_pool, "001_test.sql", "up")

        mock_print.assert_called_with("Migration 001_test.sql is already applied.")


@pytest.mark.asyncio
async def test_run_specific_migration_down_not_applied() -> None:
    """Test run_specific_migration down when not applied."""

    mock_pool = MagicMock()

    with (
        patch("migrate.get_applied_migrations", return_value=[]),
        patch("os.path.exists", return_value=True),
        patch("os.path.dirname", return_value="/path"),
        patch("builtins.print") as mock_print,
    ):
        await run_specific_migration(mock_pool, "001_test.sql", "down")

        mock_print.assert_called_with("Migration 001_test.sql is not applied and cannot be rolled back.")


@pytest.mark.asyncio
async def test_run_specific_migration_not_found() -> None:
    """Test run_specific_migration with missing file."""

    mock_pool = MagicMock()

    with (
        patch("os.path.exists", return_value=False),
        patch("os.path.dirname", return_value="/path"),
    ):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            await run_specific_migration(mock_pool, "missing.sql", "up")


@pytest.mark.asyncio
async def test_check_all_migrations_applied_true() -> None:
    """Test check_all_migrations_applied returns True."""

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with (
        patch("migrate.create_db_pool", return_value=mock_pool),
        patch("migrate.get_applied_migrations", return_value=["001_test.sql"]),
        patch("os.listdir", return_value=["001_test.sql"]),
    ):
        result = await check_all_migrations_applied()
        assert result is True


@pytest.mark.asyncio
async def test_check_all_migrations_applied_undefined_table() -> None:
    """Test check_all_migrations_applied handles UndefinedTableError."""

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with (
        patch("migrate.create_db_pool", return_value=mock_pool),
        patch("migrate.get_applied_migrations", side_effect=asyncpg.UndefinedTableError("table")),
        patch("os.listdir", return_value=["001_test.sql"]),
    ):
        result = await check_all_migrations_applied()
        assert result is False


@pytest.mark.asyncio
async def test_run_specific_migration_up_success() -> None:
    """Test run_specific_migration up successfully applies migration."""

    mock_pool = MagicMock()

    with (
        patch("migrate.get_applied_migrations", return_value=[]),
        patch("os.path.exists", return_value=True),
        patch("os.path.dirname", return_value="/path"),
        patch("migrate.run_migration", new_callable=AsyncMock) as mock_run,
        patch("migrate.record_migration", new_callable=AsyncMock) as mock_record,
    ):
        await run_specific_migration(mock_pool, "001_test.sql", "up")

        mock_run.assert_called_once()
        mock_record.assert_called_once_with(mock_pool, "001_test.sql")


@pytest.mark.asyncio
async def test_run_specific_migration_down_success() -> None:
    """Test run_specific_migration down successfully rolls back migration."""

    mock_pool = MagicMock()

    with (
        patch("migrate.get_applied_migrations", return_value=["001_test.sql"]),
        patch("os.path.exists", return_value=True),
        patch("os.path.dirname", return_value="/path"),
        patch("migrate.run_migration", new_callable=AsyncMock) as mock_run,
        patch("migrate.remove_migration_record", new_callable=AsyncMock) as mock_remove,
    ):
        await run_specific_migration(mock_pool, "001_test.sql", "down")

        mock_run.assert_called_once()
        mock_remove.assert_called_once_with(mock_pool, "001_test.sql")


@pytest.mark.asyncio
async def test_apply_migrations_down_default_steps() -> None:
    """Test apply_migrations down defaults to 1 step when steps is None."""

    mock_pool = MagicMock()

    with (
        patch("migrate.get_applied_migrations", return_value=["001_test.sql", "002_test.sql"]),
        patch("migrate.run_migration", new_callable=AsyncMock) as mock_run,
        patch("migrate.remove_migration_record", new_callable=AsyncMock) as mock_remove,
        patch("os.listdir", return_value=["001_test.sql", "002_test.sql"]),
    ):
        # Steps is None for down, should default to 1
        await apply_migrations(mock_pool, direction="down", steps=None)

        # Should rollback only 1 migration
        assert mock_run.call_count == 1
        assert mock_remove.call_count == 1


@pytest.mark.asyncio
async def test_remove_migration_record() -> None:
    """Test remove_migration_record executes correct SQL."""

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    await remove_migration_record(mock_pool, "test.sql")

    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args[0]
    assert "DELETE FROM schema_migrations" in call_args[0]
    assert call_args[1] == "test.sql"


@pytest.mark.asyncio
async def test_main_apply_migrations() -> None:
    """Test main function applies migrations (no --specific flag)."""

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    mock_args = Namespace(direction="up", steps=None, specific=None)

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock) as mock_create_table,
        patch("migrate.apply_migrations", new_callable=AsyncMock) as mock_apply,
    ):
        await main()

        mock_create_table.assert_called_once_with(mock_pool)
        mock_apply.assert_called_once_with(mock_pool, direction="up", steps=None)
        mock_pool.close.assert_called_once()


@pytest.mark.asyncio
async def test_main_specific_migration() -> None:
    """Test main function runs specific migration."""

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    mock_args = Namespace(direction="up", steps=None, specific="001_test.sql")

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock),
        patch("migrate.run_specific_migration", new_callable=AsyncMock) as mock_specific,
    ):
        await main()

        mock_specific.assert_called_once_with(mock_pool, "001_test.sql", direction="up")
        mock_pool.close.assert_called_once()


@pytest.mark.asyncio
async def test_main_down_with_steps() -> None:
    """Test main function with down direction and steps."""

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    mock_args = Namespace(direction="down", steps=2, specific=None)

    with (
        patch("argparse.ArgumentParser.parse_args", return_value=mock_args),
        patch("migrate.create_db_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("migrate.create_migrations_table", new_callable=AsyncMock),
        patch("migrate.apply_migrations", new_callable=AsyncMock) as mock_apply,
    ):
        await main()

        mock_apply.assert_called_once_with(mock_pool, direction="down", steps=2)
