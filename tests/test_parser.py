import pytest

from server.parser import ParseError, Request, parse


def test_create_user() -> None:
    r = parse("CREATE /users/bob { age: 23 }")
    assert r == Request(command="CREATE", path="/users/bob", body={"age": "23"})


def test_create_bank_account() -> None:
    r = parse("CREATE /bank-accounts/1 { owner: /users/bob, balance: 100 }")
    assert r.command == "CREATE"
    assert r.path == "/bank-accounts/1"
    assert r.body == {"owner": "/users/bob", "balance": "100"}


def test_alter_partial() -> None:
    r = parse("ALTER /bank-accounts/1 { balance: 0 }")
    assert r.command == "ALTER"
    assert r.body == {"balance": "0"}


def test_delete_no_body() -> None:
    r = parse("DELETE /users/bob")
    assert r.command == "DELETE"
    assert r.body == {}


def test_watch_timestamps() -> None:
    r = parse(
        "WATCH /users/bob { from: 2024-01-01T00:00:00Z, to: 2024-12-31T23:59:59Z }"
    )
    assert r.body["from"] == "2024-01-01T00:00:00Z"
    assert r.body["to"] == "2024-12-31T23:59:59Z"


def test_read_subgroup() -> None:
    r = parse("READ /users")
    assert r.command == "READ"
    assert r.path == "/users"
    assert r.body == {}


def test_unknown_command() -> None:
    with pytest.raises(ParseError):
        parse("FROBNICATE /users/bob {}")


def test_malformed_body() -> None:
    with pytest.raises(ParseError):
        parse("CREATE /users/bob { age 23 }")


def test_extra_content() -> None:
    with pytest.raises(ParseError):
        parse("READ /users {} garbage")
