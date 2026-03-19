from server.handlers import handle_alter, handle_create, handle_read
from server.parser import Request


async def test_alter_user_age(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    r = await handle_alter(Request("ALTER", "/users/bob", {"age": "24"}), db_session)
    assert r.startswith("200")
    read = await handle_read(Request("READ", "/users/bob", {}), db_session)
    assert "24" in read[0]


async def test_alter_partial_preserves_other_fields(db_session) -> None:
    await handle_create(Request("CREATE", "/users/alice", {"age": "30"}), db_session)
    await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/alice", "balance": "500"}
        ),
        db_session,
    )
    await handle_alter(
        Request("ALTER", "/bank-accounts/1", {"balance": "600"}), db_session
    )
    read = await handle_read(Request("READ", "/bank-accounts/1", {}), db_session)
    assert "600" in read[0]
    assert "/users/alice" in read[0]


async def test_alter_missing_entity(db_session) -> None:
    r = await handle_alter(Request("ALTER", "/users/nobody", {"age": "1"}), db_session)
    assert r.startswith("404")


async def test_alter_bank_account_owner_not_found(db_session) -> None:
    await handle_create(Request("CREATE", "/users/alice", {"age": "30"}), db_session)
    await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/alice", "balance": "0"}
        ),
        db_session,
    )
    r = await handle_alter(
        Request("ALTER", "/bank-accounts/1", {"owner": "/users/ghost"}), db_session
    )
    assert r.startswith("404")
