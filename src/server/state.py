"""
In-memory watch state.

Each active WATCH command owns an asyncio.Queue.  After every committed
CREATE / ALTER / DELETE the relevant handler calls notify_change or
notify_deleted, which pushes messages onto matching queues.  The WATCH
loop in handlers.py reads from the queue and forwards messages to the
client.

Termination
-----------
- Exact watcher  (/users/bob)  : terminated by notify_deleted when the
  entity is deleted.
- Prefix watcher (/users)      : terminated explicitly by the handler
  via terminate_prefix_watchers, either when the subgroup is deleted or
  when it becomes empty.

In both cases, a None sentinel is pushed onto the queue; the WATCH loop
exits when it reads None.  The WATCH loop's finally block always calls
unregister(), which is a no-op if the watcher was never added or was
already removed.

Client disconnection
--------------------
On disconnection the watcher is silently dropped from _watchers in the
WATCH loop's finally block.
Alternative: log the event for observability, e.g.:
    logger.warning("Client disconnected, dropping watcher for %s", path)
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class _Watcher:
    watched_path: str
    writer: asyncio.StreamWriter
    is_prefix: bool
    to_ts: datetime | None  # None means unbounded


_watchers: list[_Watcher] = []


def reset() -> None:
    global _watchers
    _watchers = []


def register(
    watched_path: str,
    writer: asyncio.StreamWriter,
    is_prefix: bool,
    to_ts: datetime | None = None,
) -> None:
    _watchers.append(_Watcher(watched_path, writer, is_prefix, to_ts))


def unregister(writer: asyncio.StreamWriter) -> None:
    global _watchers
    _watchers = [w for w in _watchers if w.writer is not writer]


def _matches(watcher: _Watcher, entity_path: str) -> bool:
    if watcher.is_prefix:
        return entity_path.startswith(watcher.watched_path + "/")
    return entity_path == watcher.watched_path


def _expired(watcher: _Watcher) -> bool:
    return watcher.to_ts is not None and datetime.now(timezone.utc) > watcher.to_ts


async def _send(watcher: _Watcher, message: str) -> bool:
    """Send a message. Returns False if the connection is broken."""
    try:
        watcher.writer.write((message + "\n").encode())
        await watcher.writer.drain()
        return True
    except (BrokenPipeError, ConnectionResetError):
        return False


async def notify_change(entity_path: str, message: str) -> None:
    for w in list(_watchers):
        if not _matches(w, entity_path):
            continue
        if _expired(w):
            unregister(w.writer)
            continue
        if not await _send(w, message):
            unregister(w.writer)


async def notify_deleted(entity_path: str, message: str) -> None:
    for w in list(_watchers):
        if not _matches(w, entity_path):
            continue
        await _send(w, message)
        if not w.is_prefix:
            unregister(w.writer)


async def terminate_prefix_watchers(watched_path: str, message: str) -> None:
    for w in list(_watchers):
        if w.watched_path == watched_path and w.is_prefix:
            await _send(w, message)
            unregister(w.writer)
