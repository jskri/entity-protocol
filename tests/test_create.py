from server.handlers import handle_create
from server.parser import Request


async def test_create_user(db_session) -> None:
    r = await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    assert r.startswith("201")
    assert "/users/bob" in r


async def test_create_user_duplicate(db_session) -> None:
    req = Request("CREATE", "/users/bob", {"age": "23"})
    await handle_create(req, db_session)
    r = await handle_create(req, db_session)
    assert r.startswith("409")


async def test_create_bank_account(db_session) -> None:
    await handle_create(Request("CREATE", "/users/bob", {"age": "23"}), db_session)
    r = await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/bob", "balance": "100"}
        ),
        db_session,
    )
    assert r.startswith("201")


async def test_create_bank_account_missing_owner(db_session) -> None:
    r = await handle_create(
        Request(
            "CREATE", "/bank-accounts/1", {"owner": "/users/nobody", "balance": "0"}
        ),
        db_session,
    )
    assert r.startswith("404")
    assert "/users/nobody" in r


async def test_create_user_invalid_age(db_session) -> None:
    r = await handle_create(Request("CREATE", "/users/bob", {"age": "abc"}), db_session)
    assert r.startswith("400")
