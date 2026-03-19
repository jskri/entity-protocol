# Toy Implementation

A toy implementation of the formal model described in the accompanying blog post.
The model defines a small set of commands — CREATE, ALTER, DELETE, WATCH, READ —
operating on entities addressed by paths. This server implements that protocol
over a plain TCP connection.

---

## File Tree
```
.
├── docker-compose.yml           # server + database
├── docker-compose.test.yml      # test database
├── Dockerfile
├── Makefile
├── pyproject.toml
├── uv.lock
├── .python-version
├── .github/
│   └── workflows/
│       └── ci.yml               # lint, typecheck, test
├── src/
│   └── server/
│       ├── main.py              # TCP listener, client connection loop
│       ├── parser.py            # request parser
│       ├── handlers.py          # command handlers
│       ├── db.py                # SQLAlchemy models and session management
│       ├── state.py             # in-memory watch state
│       └── protocol.py          # response formatting
└── tests/
    ├── conftest.py
    ├── test_alter.py
    ├── test_create.py
    ├── test_delete.py
    ├── test_parser.py
    ├── test_read.py
    └── test_watch.py
```

---

## Architecture

The server listens on a TCP port and handles one persistent connection per
client. Each line received is parsed as a request and dispatched to the
appropriate handler.

**Parser** (`parser.py`): hand-written recursive descent parser implementing
the grammar defined in `implementation.md`. Produces a `Request` dataclass
(command, path, body).

**Handlers** (`handlers.py`): one async function per command. Each handler
opens a database session, performs the operation inside a transaction, records
the command in the `Events` table (same transaction), commits, then notifies
watchers.

**Database** (`db.py`): SQLAlchemy async models over PostgreSQL 16.
Three tables:
- `users` — `name` (PK), `age`
- `bank_accounts` — `id` (PK), `owner` (FK → `users.name` ON DELETE CASCADE),
  `balance`
- `events` — append-only log of every CREATE / ALTER / DELETE, used to replay
  past states for timestamped WATCH requests

**Watch state** (`state.py`): in-memory list of active watchers. Each watcher
holds the watched path, a reference to the client's `StreamWriter`, and an
optional `to` timestamp bound. After every committed mutation, the relevant
handler calls `notify_change`, `notify_deleted`, or
`terminate_prefix_watchers`, which write directly to matching client writers.

**Notifications are sent after commit.** This means a server crash between
commit and notify can cause a missed notification. The alternative — notifying
inside the transaction — risks notifying on a rolled-back write. The lost-
notification risk is acceptable for a toy.

---

## Testing

Tests require Docker to be running.
```bash
make test
```

This starts a dedicated test database container on port 5433, runs the full
pytest suite against it, then tears the container down. Tests cover the parser,
all five commands, and WATCH notifications including cascades.

---

## Running the Server

Start the server and its database:
```bash
make up
```

Stop them:
```bash
make down
```

The server listens on port 8888. The `DATABASE_URL` and `PORT` environment
variables can be overridden in `docker-compose.yml`.

---

## Sending Commands

Connect with `nc`:
```bash
nc 0.0.0.0 8888
```

### CREATE
```
CREATE /users/bob { age: 23 }
201 { path: /users/bob }

CREATE /users/bob { age: 23 }
409 { path: /users/bob }

CREATE /bank-accounts/1 { owner: /users/bob, balance: 100 }
201 { path: /bank-accounts/1 }

CREATE /bank-accounts/2 { owner: /users/nobody, balance: 0 }
404 { path: /users/nobody }
```

### ALTER
```
ALTER /users/bob { age: 30 }
200 { path: /users/bob }

ALTER /bank-accounts/1 { balance: 200 }
200 { path: /bank-accounts/1 }

ALTER /bank-accounts/1 { owner: /users/bob, balance: 50 }
200 { path: /bank-accounts/1 }
```

### DELETE
```
DELETE /users/bob
200 { path: /users/bob }

DELETE /bank-accounts
200 { path: /bank-accounts }
```

Deleting a user cascades to their bank accounts.

### READ
```
READ /users/bob
200 { path: /users/bob, age: 23 }

READ /users
200 { path: /users/bob, age: 23 }
200 { path: /users/alice, age: 30 }

READ /bank-accounts/1
200 { path: /bank-accounts/1, owner: /users/bob, balance: 100 }
```

### WATCH

Open a first connection and register a watch:
```
WATCH /users/bob
200 { path: /users/bob }
```

From a second connection, alter the entity:
```
ALTER /users/bob { age: 99 }
```

The first connection receives:
```
200 { command: WATCH, path: /users/bob, age: 99 }
```

When the entity is deleted, the first connection receives:
```
410 { command: WATCH, path: /users/bob }
```

Subgroup watches are also supported:
```
WATCH /users
200 { path: /users }
```

This covers all current and future entities under `/users`.

Bounded watches replay past events as a burst then stream live updates:
```
WATCH /users/bob { from: 2024-01-01T00:00:00Z, to: 2024-01-01T00:01:00Z }
```
