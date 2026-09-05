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

# start the target lab services (4 scan targets)
lab-up:
    docker compose --profile lab up -d

# stop the target lab services
lab-down:
    docker compose --profile lab down

# follow logs from the target lab services
lab-logs:
    docker compose --profile lab logs -f

# follow logs from the zitadel service only
zitadel-logs:
    docker compose logs -f zitadel

# print the Zitadel OIDC discovery document. Requires `127.0.0.1 zitadel` in
# /etc/hosts first (see the issuer trap section of docs/zitadel-local.md) —
# Zitadel resolves the virtual instance from the Host header, so plain
# `localhost:8080` gets a 404 "Instance not found" here even though the port
# is reachable.
zitadel-discovery:
    curl -s http://zitadel:8080/.well-known/openid-configuration | python3 -m json.tool

# fetch an OAuth2 access token via the client_credentials grant, for a
# machine user/app you've created by hand in the Zitadel console (see
# docs/zitadel-local.md)
# Same /etc/hosts prerequisite as zitadel-discovery.
zitadel-token client_id client_secret:
    curl -s -u "{{client_id}}:{{client_secret}}" \
        -d grant_type=client_credentials \
        -d scope="openid urn:zitadel:iam:org:project:id:${ZITADEL_PROJECT_ID}:aud" \
        http://zitadel:8080/oauth/v2/token | python3 -m json.tool

# decode a JWT's header and payload without verifying the signature — for
# eyeballing claims during local testing only, never a substitute for real
# verification (that's W2-04's job).
zitadel-decode token:
    #!/usr/bin/env python3
    import base64, json
    def b64d(s):
        s += "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s)
    header, payload, _ = "{{token}}".split(".")
    print(json.dumps(json.loads(b64d(header)), indent=2))
    print(json.dumps(json.loads(b64d(payload)), indent=2))

zitadel-bootstrap:
    docker compose exec app python scripts/zitadel_bootstrap.py

# run database migrations
migrate:
    docker compose exec app alembic upgrade head

# roll back database migrations (defaults to the previous revision)
downgrade revision="-1":
    docker compose exec app alembic downgrade {{revision}}

# create a new migration
migration msg:
    docker compose exec app alembic revision --autogenerate -m "{{msg}}"

# run tests inside the app container (unit + e2e)
test:
    docker compose exec app pytest

# run unit tests only, skipping e2e (safe outside Docker too)
test-unit:
    docker compose exec app pytest -m "not e2e"

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
    @echo "\n=== Zitadel ===" && curl -sf http://localhost:8080/debug/healthz || echo "NOT HEALTHY"

