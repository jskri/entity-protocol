import asyncio
from unittest.mock import AsyncMock, MagicMock

import server.state as state
from server.handlers import handle_alter, handle_create, handle_delete, handle_watch
from server.parser import Request


def _make_writer() -> MagicMock:
    """A mock StreamWriter that records written bytes."""
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = False
    writer.drain = AsyncMock()
    writer._written: list[str] = []

    def _write(data: bytes) -> None:
        writer._written.extend(data.decode().splitlines())

    writer.write = MagicMock(side_effect=_write)
    return writer


async def test_watch_normal_answer(db_session) -> None:
    r = await handle_watch(
        Request("WATCH", "/users/bob"),
        db_session,
        _make_writer(),
    )
    assert "200" in r


async def test_watch_receives_alter(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/users/bob", {}), db_session, writer)

    await handle_alter(Request("ALTER", "/users/bob", {"age": "30"}), db_session)

    assert any(
        "200" in line and "/users/bob" in line and "30" in line
        for line in writer._written
    )


async def test_watch_receives_410_on_delete(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/users/bob", {}), db_session, writer)

    await handle_delete(Request("DELETE", "/users/bob", {}), db_session)

    assert any("410" in line and "/users/bob" in line for line in writer._written)
    assert not any(w.writer is writer for w in state._watchers)


async def test_watch_unregistered_after_delete(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/users/bob", {}), db_session, writer)
    await handle_delete(Request("DELETE", "/users/bob", {}), db_session)

    # Further alter on unrelated entity should not reach the watcher.
    await handle_create(Request("CREATE", "/users/alice", {"age": "40"}), db_session)
    await handle_alter(Request("ALTER", "/users/alice", {"age": "41"}), db_session)

    assert not any("alice" in line for line in writer._written)


async def test_watch_prefix_receives_existing_entity_alter(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    await handle_create(Request("CREATE", "/users/alice", {"age": "30"}), db_session)
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/users", {}), db_session, writer)

    await handle_alter(Request("ALTER", "/users/bob", {"age": "99"}), db_session)

    assert any("99" in line and "/users/bob" in line for line in writer._written)


async def test_watch_prefix_receives_new_entity(db_session) -> None:
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/users", {}), db_session, writer)

    await handle_create(Request("CREATE", "/users/carol", {"age": "25"}), db_session)

    assert any("/users/carol" in line and "25" in line for line in writer._written)


async def test_watch_prefix_terminated_on_subgroup_delete(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/users", {}), db_session, writer)

    await handle_delete(Request("DELETE", "/users", {}), db_session)

    assert any("410" in line for line in writer._written)
    assert not any(w.writer is writer for w in state._watchers)


async def test_watch_cascade_notifies_bank_account_watcher(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/bob", "balance": "100"}
        ),
        db_session,
    )
    writer = _make_writer()
    await handle_watch(Request("WATCH", "/bank-accounts/1", {}), db_session, writer)

    await handle_delete(Request("DELETE", "/users/bob", {}), db_session)

    assert any("410" in line and "/bank-accounts/1" in line for line in writer._written)


async def test_watch_invalid_timestamp_order(db_session) -> None:
    writer = _make_writer()
    r = await handle_watch(
        Request(
            "WATCH",
            "/users/bob",
            {"from": "2024-12-31T00:00:00Z", "to": "2024-01-01T00:00:00Z"},
        ),
        db_session,
        writer,
    )
    assert "422" in r
