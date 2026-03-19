"""
Command handlers.

Each handler is responsible for:
  1. Validating the request against the schema.
  2. Performing the database operation inside a transaction.
  3. Recording the event in the Events table (same transaction).
  4. Committing.
  5. Notifying watchers after the commit.

Notification after commit
-------------------------
We notify watchers AFTER the transaction commits.  This means that if
the server crashes between commit and notify, the notification is lost.
The alternative—notifying inside the transaction—risks sending a
notification for a write that is later rolled back.  For this toy the
lost-notification risk is acceptable.
"""

import asyncio
import json
import re
from datetime import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import server.state as state
from server.db import (
    BankAccount,
    User,
    get_earliest_event_timestamp,
    get_events_for_watch,
    record_event,
)
from server.parser import Request
from server.protocol import format_response

_NUMBER_RE = re.compile(r"^(0|[1-9][0-9]*)$")


def _is_valid_number(s: str) -> bool:
    return bool(_NUMBER_RE.match(s))


def _is_prefix_path(path: str) -> bool:
    """True for /users or /bank-accounts; False for /users/bob etc."""
    return path.count("/") == 1


def _parse_path_parts(path: str) -> tuple[str, str | None]:
    """Return (collection, entity_id_or_None)."""
    parts = path.lstrip("/").split("/", 1)
    return parts[0], parts[1] if len(parts) == 2 else None


def _parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def _entity_properties(session: AsyncSession, path: str) -> dict[str, str]:
    collection, entity_id = _parse_path_parts(path)
    if collection == "users" and entity_id is not None:
        row = (
            await session.execute(select(User).where(User.name == entity_id))
        ).scalar_one_or_none()
        if row:
            return {"age": str(row.age)}
    elif collection == "bank-accounts" and entity_id is not None:
        row_ba = (
            await session.execute(
                select(BankAccount).where(BankAccount.id == int(entity_id))
            )
        ).scalar_one_or_none()
        if row_ba:
            return {
                "owner": f"/users/{row_ba.owner}",
                "balance": str(row_ba.balance),
            }
    return {}


def _watch_msg(path: str, props: dict[str, str]) -> str:
    return format_response(200, {"command": "WATCH", "path": path, **props})


def _gone_msg(path: str) -> str:
    return format_response(410, {"command": "WATCH", "path": path})


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------


async def handle_create(request: Request, session: AsyncSession) -> str:
    collection, entity_id = _parse_path_parts(request.path)

    async def handle_create_user() -> str:
        if entity_id is None:
            return format_response(400, {"command": "CREATE", "path": request.path})
        age_str = request.body.get("age", "")
        if not _is_valid_number(age_str):
            return format_response(400, {"command": "CREATE", "path": request.path})
        existing: User | None = (
            await session.execute(select(User).where(User.name == entity_id))
        ).scalar_one_or_none()
        if existing:
            return format_response(409, {"path": request.path})
        session.add(User(name=entity_id, age=int(age_str)))
        await record_event(session, "CREATE", request.path, request.body)
        await session.commit()
        await state.notify_change(
            request.path, _watch_msg(request.path, {"age": age_str})
        )
        return format_response(201, {"path": request.path})

    async def handle_create_bank_account() -> str:
        if entity_id is None or not _is_valid_number(entity_id):
            return format_response(400, {"command": "CREATE", "path": request.path})
        account_id = int(entity_id)
        owner_path = request.body.get("owner", "")
        balance_str = request.body.get("balance", "")
        if not _is_valid_number(balance_str):
            return format_response(400, {"command": "CREATE", "path": request.path})
        owner_parts = owner_path.lstrip("/").split("/", 1)
        if len(owner_parts) != 2 or owner_parts[0] != "users":
            return format_response(400, {"command": "CREATE", "path": request.path})
        owner_name = owner_parts[1]
        owner = (
            await session.execute(select(User).where(User.name == owner_name))
        ).scalar_one_or_none()
        if owner is None:
            return format_response(404, {"path": owner_path})
        existing: BankAccount | None = (
            await session.execute(
                select(BankAccount).where(BankAccount.id == account_id)
            )
        ).scalar_one_or_none()
        if existing:
            return format_response(409, {"path": request.path})
        session.add(
            BankAccount(id=account_id, owner=owner_name, balance=int(balance_str))
        )
        await record_event(session, "CREATE", request.path, request.body)
        await session.commit()
        await state.notify_change(
            request.path,
            _watch_msg(request.path, {"owner": owner_path, "balance": balance_str}),
        )
        return format_response(201, {"path": request.path})

    if collection == "users":
        return await handle_create_user()
    elif collection == "bank-accounts":
        return await handle_create_bank_account()
    else:
        return format_response(400, {"command": "CREATE", "path": request.path})


# ---------------------------------------------------------------------------
# ALTER
# ---------------------------------------------------------------------------


async def handle_alter(request: Request, session: AsyncSession) -> str:
    collection, entity_id = _parse_path_parts(request.path)

    if collection == "users":
        if entity_id is None:
            return format_response(400, {"command": "ALTER", "path": request.path})
        user = (
            await session.execute(select(User).where(User.name == entity_id))
        ).scalar_one_or_none()
        if user is None:
            return format_response(404, {"path": request.path})
        if "age" in request.body:
            age_str = request.body["age"]
            if not _is_valid_number(age_str):
                return format_response(400, {"command": "ALTER", "path": request.path})
            user.age = int(age_str)
        await record_event(session, "ALTER", request.path, request.body)
        await session.commit()
        props = await _entity_properties(session, request.path)
        await state.notify_change(request.path, _watch_msg(request.path, props))
        return format_response(200, {"path": request.path})

    if collection == "bank-accounts":
        if entity_id is None or not _is_valid_number(entity_id):
            return format_response(400, {"command": "ALTER", "path": request.path})
        account = (
            await session.execute(
                select(BankAccount).where(BankAccount.id == int(entity_id))
            )
        ).scalar_one_or_none()
        if account is None:
            return format_response(404, {"path": request.path})
        if "owner" in request.body:
            owner_path = request.body["owner"]
            owner_parts = owner_path.lstrip("/").split("/", 1)
            if len(owner_parts) != 2 or owner_parts[0] != "users":
                return format_response(400, {"command": "ALTER", "path": request.path})
            owner_name = owner_parts[1]
            owner = (
                await session.execute(select(User).where(User.name == owner_name))
            ).scalar_one_or_none()
            if owner is None:
                return format_response(404, {"path": owner_path})
            account.owner = owner_name
        if "balance" in request.body:
            balance_str = request.body["balance"]
            if not _is_valid_number(balance_str):
                return format_response(400, {"command": "ALTER", "path": request.path})
            account.balance = int(balance_str)
        await record_event(session, "ALTER", request.path, request.body)
        await session.commit()
        props = await _entity_properties(session, request.path)
        await state.notify_change(request.path, _watch_msg(request.path, props))
        return format_response(200, {"path": request.path})

    return format_response(400, {"command": "ALTER", "path": request.path})


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


async def handle_delete(request: Request, session: AsyncSession) -> str:
    collection, entity_id = _parse_path_parts(request.path)

    if collection == "users":
        if entity_id is not None:
            user = (
                await session.execute(select(User).where(User.name == entity_id))
            ).scalar_one_or_none()
            if user is None:
                return format_response(404, {"path": request.path})
            # Collect accounts that will be cascade-deleted so we can notify.
            cascade = list(
                (
                    await session.execute(
                        select(BankAccount).where(BankAccount.owner == entity_id)
                    )
                ).scalars()
            )
            await session.delete(user)
            await record_event(session, "DELETE", request.path, {})
            await session.commit()
            await state.notify_deleted(request.path, _gone_msg(request.path))
            for acct in cascade:
                acct_path = f"/bank-accounts/{acct.id}"
                await state.notify_deleted(acct_path, _gone_msg(acct_path))
            # Terminate prefix watchers if their subgroup is now empty.
            no_users = (
                await session.execute(select(User).limit(1))
            ).scalar_one_or_none() is None
            if no_users:
                await state.terminate_prefix_watchers("/users", _gone_msg("/users"))
            no_accounts = (
                await session.execute(select(BankAccount).limit(1))
            ).scalar_one_or_none() is None
            if no_accounts:
                await state.terminate_prefix_watchers(
                    "/bank-accounts", _gone_msg("/bank-accounts")
                )
            return format_response(200, {"path": request.path})

        # DELETE /users — delete all users (cascades to all bank accounts).
        all_users = list((await session.execute(select(User))).scalars())
        all_accounts = list((await session.execute(select(BankAccount))).scalars())
        await session.execute(sa_delete(User))
        await record_event(session, "DELETE", request.path, {})
        await session.commit()
        for u in all_users:
            await state.notify_deleted(
                f"/users/{u.name}", _gone_msg(f"/users/{u.name}")
            )
        await state.terminate_prefix_watchers("/users", _gone_msg("/users"))
        for acct in all_accounts:
            acct_path = f"/bank-accounts/{acct.id}"
            await state.notify_deleted(acct_path, _gone_msg(acct_path))
        await state.terminate_prefix_watchers(
            "/bank-accounts", _gone_msg("/bank-accounts")
        )
        return format_response(200, {"path": request.path})

    if collection == "bank-accounts":
        if entity_id is not None:
            if not _is_valid_number(entity_id):
                return format_response(400, {"command": "DELETE", "path": request.path})
            account = (
                await session.execute(
                    select(BankAccount).where(BankAccount.id == int(entity_id))
                )
            ).scalar_one_or_none()
            if account is None:
                return format_response(404, {"path": request.path})
            await session.delete(account)
            await record_event(session, "DELETE", request.path, {})
            await session.commit()
            await state.notify_deleted(request.path, _gone_msg(request.path))
            no_accounts = (
                await session.execute(select(BankAccount).limit(1))
            ).scalar_one_or_none() is None
            if no_accounts:
                await state.terminate_prefix_watchers(
                    "/bank-accounts", _gone_msg("/bank-accounts")
                )
            return format_response(200, {"path": request.path})

        # DELETE /bank-accounts
        all_accounts = list((await session.execute(select(BankAccount))).scalars())
        await session.execute(sa_delete(BankAccount))
        await record_event(session, "DELETE", request.path, {})
        await session.commit()
        for acct in all_accounts:
            acct_path = f"/bank-accounts/{acct.id}"
            await state.notify_deleted(acct_path, _gone_msg(acct_path))
        await state.terminate_prefix_watchers(
            "/bank-accounts", _gone_msg("/bank-accounts")
        )
        return format_response(200, {"path": request.path})

    return format_response(400, {"command": "DELETE", "path": request.path})


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


async def handle_read(request: Request, session: AsyncSession) -> list[str]:
    collection, entity_id = _parse_path_parts(request.path)

    if collection == "users":
        if entity_id is not None:
            user = (
                await session.execute(select(User).where(User.name == entity_id))
            ).scalar_one_or_none()
            if user is None:
                return [format_response(404, {"path": request.path})]
            return [format_response(200, {"path": request.path, "age": str(user.age)})]
        users = list((await session.execute(select(User))).scalars())
        if not users:
            return [format_response(404, {"path": request.path})]
        return [
            format_response(200, {"path": f"/users/{u.name}", "age": str(u.age)})
            for u in users
        ]

    if collection == "bank-accounts":
        if entity_id is not None:
            if not _is_valid_number(entity_id):
                return [format_response(400, {"command": "READ", "path": request.path})]
            acct = (
                await session.execute(
                    select(BankAccount).where(BankAccount.id == int(entity_id))
                )
            ).scalar_one_or_none()
            if acct is None:
                return [format_response(404, {"path": request.path})]
            return [
                format_response(
                    200,
                    {
                        "path": request.path,
                        "owner": f"/users/{acct.owner}",
                        "balance": str(acct.balance),
                    },
                )
            ]
        accounts = list((await session.execute(select(BankAccount))).scalars())
        if not accounts:
            return [format_response(404, {"path": request.path})]
        return [
            format_response(
                200,
                {
                    "path": f"/bank-accounts/{a.id}",
                    "owner": f"/users/{a.owner}",
                    "balance": str(a.balance),
                },
            )
            for a in accounts
        ]

    return [format_response(400, {"command": "READ", "path": request.path})]


# ---------------------------------------------------------------------------
# WATCH
# ---------------------------------------------------------------------------


async def handle_watch(
    request: Request,
    session: AsyncSession,
    writer: asyncio.StreamWriter,
) -> str:
    from_str = request.body.get("from")
    to_str = request.body.get("to")
    is_prefix = _is_prefix_path(request.path)

    if from_str and to_str:
        if _parse_timestamp(from_str) > _parse_timestamp(to_str):
            return format_response(
                422, {"path": request.path, "from": from_str, "to": to_str}
            )

    if from_str:
        from_ts = _parse_timestamp(from_str)
        earliest = await get_earliest_event_timestamp(session)
        if earliest is not None and from_ts < earliest:
            return format_response(416, {"path": request.path, "from": from_str})
        to_ts_val = _parse_timestamp(to_str) if to_str else None
        past = await get_events_for_watch(
            session, request.path, is_prefix, from_ts, to_ts_val
        )
        for event in past:
            body = json.loads(event.body)
            msg = (
                _gone_msg(event.path)
                if event.command == "DELETE"
                else _watch_msg(event.path, body)
            )
            _write(writer, msg)
        await writer.drain()

    to_ts_val = _parse_timestamp(to_str) if to_str else None
    state.register(request.path, writer, is_prefix, to_ts=to_ts_val)
    return format_response(200, {"path": request.path})


def _write(writer: asyncio.StreamWriter, message: str) -> None:
    writer.write((message + "\n").encode())
