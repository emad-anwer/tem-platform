set dotenv-load

# list available recipes
default:
    @just --list

# start the stack in detached mode
up:
    docker compose up -d

# start the stack with hot reload (file watching)
dev:
    docker compose watch

# stop and remove containers
down:
    docker compose down

# stop and remove containers, volumes, and images
nuke:
    docker compose down -v --rmi local

# follow logs from all services
logs:
    docker compose logs -f

# follow logs from the app service only
logs-app:
    docker compose logs -f app

# run database migrations
migrate:
    docker compose exec app alembic upgrade head

# create a new migration
migration msg:
    docker compose exec app alembic revision --autogenerate -m "{{msg}}"

# run tests inside the app container
test:
    docker compose exec app pytest

# run linter and format checker
lint:
    ruff check .
    ruff format --check .

# auto-fix lint and format issues
fix:
    ruff check --fix .
    ruff format .

# open a shell inside the app container
shell:
    docker compose exec app bash

# open a psql shell
db-shell:
    docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB}

# rebuild the app image
build:
    docker compose build app

# check the health of all services
health:
    @echo "=== App ===" && curl -sf http://localhost:8000/healthz || echo "NOT HEALTHY"
    @echo "\n=== Postgres ===" && docker compose exec postgres pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} || echo "NOT HEALTHY"
    @echo "\n=== Redis ===" && docker compose exec -e REDISCLI_AUTH="${REDIS_PASSWORD}" redis redis-cli ping || echo "NOT HEALTHY"
