.PHONY: up down test

SERVER_DOCKERFILE := Dockerfile
PY_FILES := db.py handlers.py main.py parser.py protocol.py state.py
SRC_FILES := $(addprefix src/server/, $(PY_FILES))

.docker-build: $(SERVER_DOCKERFILE) $(SRC_FILES) pyproject.toml uv.lock
	docker-compose -f docker-compose.yml build
	touch .docker-build

up: .docker-build
	docker-compose -f docker-compose.yml up

down:
	docker-compose -f docker-compose.yml down

test:
	docker-compose -f docker-compose.test.yml up -d
	DATABASE_URL=postgresql+asyncpg://server:server@localhost:5433/server_test uv run pytest
	docker-compose -f docker-compose.test.yml down
