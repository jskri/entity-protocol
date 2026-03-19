from server.handlers import handle_create, handle_delete, handle_read
from server.parser import Request


async def test_delete_user(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    r = await handle_delete(Request("DELETE", "/users/bob", {}), db_session)
    assert r.startswith("200")
    read = await handle_read(Request("READ", "/users/bob", {}), db_session)
    assert read[0].startswith("404")


async def test_delete_user_cascades_to_bank_account(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/bob", "balance": "100"}
        ),
        db_session,
    )
    await handle_delete(Request("DELETE", "/users/bob", {}), db_session)
    read = await handle_read(Request("READ", "/bank-accounts/1", {}), db_session)
    assert read[0].startswith("404")


async def test_delete_missing_entity(db_session) -> None:
    r = await handle_delete(Request("DELETE", "/users/nobody", {}), db_session)
    assert r.startswith("404")


async def test_delete_subgroup(db_session) -> None:
    await handle_create(Request("CREATE", "/users/a", {"age": "1"}), db_session)
    await handle_create(Request("CREATE", "/users/b", {"age": "2"}), db_session)
    r = await handle_delete(Request("DELETE", "/users", {}), db_session)
    assert r.startswith("200")
    read = await handle_read(Request("READ", "/users", {}), db_session)
    assert read[0].startswith("404")
