from server.handlers import handle_create, handle_read
from server.parser import Request


async def test_read_user(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    r = await handle_read(Request("READ", "/users/bob", {}), db_session)
    assert len(r) == 1
    assert "23" in r[0]
    assert "/users/bob" in r[0]


async def test_read_missing_user(db_session) -> None:
    r = await handle_read(Request("READ", "/users/nobody", {}), db_session)
    assert r[0].startswith("404")


async def test_read_subgroup(db_session) -> None:
    await handle_create(Request("CREATE", "/users/alice", {"age": "30"}), db_session)
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    r = await handle_read(Request("READ", "/users", {}), db_session)
    assert len(r) == 2
    paths = ["/users/alice", "/users/bob"]
    for path in paths:
        assert any(path in line for line in r)


async def test_read_bank_account(db_session) -> None:
    await handle_create(Request("CREATE", "/users/alice", {"age": "30"}), db_session)
    await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/alice", "balance": "500"}
        ),
        db_session,
    )
    r = await handle_read(Request("READ", "/bank-accounts/1", {}), db_session)
    assert len(r) == 1
    assert "500" in r[0]
    assert "/users/alice" in r[0]


async def test_read_empty_subgroup(db_session) -> None:
    r = await handle_read(Request("READ", "/bank-accounts", {}), db_session)
    assert r[0].startswith("404")
