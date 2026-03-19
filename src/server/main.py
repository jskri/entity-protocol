"""
Starts the server and handles commands.
"""

import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import server.db as db
from server.handlers import (
    handle_alter,
    handle_create,
    handle_delete,
    handle_read,
    handle_watch,
)
from server.parser import ParseError, parse
from server.protocol import format_response


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        while True:
            line = await reader.readline()
            if not line:
                break  # connection was closes
            text = line.decode(errors="replace").strip()
            if not text:
                continue  # skip newlines or whitespace-only lines

            try:
                request = parse(text)
            except ParseError as exc:
                response = format_response(
                    400,
                    {"command": exc.command or "UNKNOWN", "path": exc.path or "/"},
                )
                writer.write((response + "\n").encode())
                await writer.drain()
                continue

            # A new session is created for each command to:
            # - avoid a command to read the cache from a previous command
            # - ensure that each command is a transaction
            async with db_session_factory() as db_session:
                if request.command == "CREATE":
                    writer.write(
                        (await handle_create(request, db_session) + "\n").encode()
                    )
                    await writer.drain()
                elif request.command == "ALTER":
                    writer.write(
                        (await handle_alter(request, db_session) + "\n").encode()
                    )
                    await writer.drain()
                elif request.command == "DELETE":
                    writer.write(
                        (await handle_delete(request, db_session) + "\n").encode()
                    )
                    await writer.drain()
                elif request.command == "READ":
                    for r in await handle_read(request, db_session):
                        writer.write((r + "\n").encode())
                    await writer.drain()
                elif request.command == "WATCH":
                    writer.write(
                        (
                            await handle_watch(request, db_session, writer) + "\n"
                        ).encode()
                    )
                    await writer.drain()

    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    db_engine = db.make_engine()
    async with db_engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)

    db_session_factory = db.make_session_factory(db_engine)
    port = int(os.environ.get("PORT", "8888"))

    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, db_session_factory),
        host="0.0.0.0",
        port=port,
    )
    print(f"Listening on port {port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
