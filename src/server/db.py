"""
Database models and session management.

Schema
------
- Users        : name (PK), age
- BankAccounts : id (PK), owner (FK → Users.name ON DELETE CASCADE), balance
- Events       : append-only log of every CREATE / ALTER / DELETE command,
                 used to replay past states for timestamped WATCH requests.

History is kept unbounded in size.  A configurable retention window could be
added by periodically running:
    DELETE FROM events WHERE timestamp < now() - interval '<retention>'
exposed as an env var (e.g. RETENTION_DAYS).
"""

import json
import os
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False)


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.name", ondelete="CASCADE"),
        nullable=False,
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False)


class Event(Base):
    """Append-only log entry for a mutating command."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    command: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)  # JSON


# ---------------------------------------------------------------------------
# Engine / session factory
# ---------------------------------------------------------------------------


def make_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or os.environ["DATABASE_URL"])


def make_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def record_event(
    session: AsyncSession,
    command: str,
    path: str,
    body: dict[str, str],
) -> None:
    session.add(
        Event(
            timestamp=datetime.now(timezone.utc),
            command=command,
            path=path,
            body=json.dumps(body),
        )
    )


async def get_earliest_event_timestamp(
    session: AsyncSession,
) -> datetime | None:
    result = await session.execute(select(Event.timestamp).order_by(Event.id).limit(1))
    return result.scalar_one_or_none()


async def get_events_for_watch(
    session: AsyncSession,
    watched_path: str,
    is_prefix: bool,
    from_ts: datetime,
    to_ts: datetime | None,
) -> list[Event]:
    """Return events matching a watched path within a timestamp range."""
    if is_prefix:
        stmt = select(Event).where(
            Event.path.like(watched_path + "/%"),
            Event.timestamp >= from_ts,
        )
    else:
        stmt = select(Event).where(
            Event.path == watched_path,
            Event.timestamp >= from_ts,
        )
    if to_ts is not None:
        stmt = stmt.where(Event.timestamp <= to_ts)
    result = await session.execute(stmt.order_by(Event.id))
    return list(result.scalars().all())
