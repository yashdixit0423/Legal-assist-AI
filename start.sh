#!/usr/bin/env bash
# One-command local start for LegalEdge: database -> migrations -> corpus (if empty) -> API -> web.
# Usage:  ./start.sh        Stop: press Ctrl+C (the database keeps running; stop it with: docker compose stop)
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
mkdir -p var/logs

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$1"; }
die() { printf "\n\033[1;31mERROR: %s\033[0m\n" "$1"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# The venv's executables are in bin/ on macOS/Linux and Scripts/ on Windows.
VENV=.venv/bin; [ -d "$VENV" ] || VENV=.venv/Scripts

if ! have docker && [ -d var/pgdata ]; then
  # No Docker (e.g. Windows + Git Bash): a local PostgreSQL cluster in var/pgdata.
  # Set PG_BIN to the folder holding pg_ctl/psql if they are not on PATH.
  PG="${PG_BIN:+$PG_BIN/}"
  say "1-2/6 No Docker - starting the local PostgreSQL in var/pgdata"
  "${PG}pg_ctl" -D var/pgdata status >/dev/null 2>&1 || "${PG}pg_ctl" -D var/pgdata -l var/logs/postgres.log -w start
  psql_q() { PGPASSWORD=legaledge "${PG}psql" -h localhost -U legaledge -d legaledge -tAc "$1" | tr -d '\r'; }
else
say "1/6 Checking Docker"
if ! docker info >/dev/null 2>&1; then
  have open || die "Docker isn't running. Start it and re-run."
  echo "Docker isn't running - opening Docker Desktop..."
  open -a Docker || die "Docker Desktop is not installed."
  for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || die "Docker did not start within 2 minutes. Open Docker Desktop manually and re-run."
fi
echo "Docker OK"

say "2/6 Starting PostgreSQL (port 5433)"
docker compose up -d postgres
for i in $(seq 1 60); do
  status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || echo starting)
  [ "$status" = "healthy" ] && break; sleep 2
done
[ "$status" = "healthy" ] || { docker compose logs --tail 30 postgres; die "Postgres did not become healthy."; }
psql_q() { docker compose exec -T postgres psql -U legaledge -d legaledge -tAc "$1"; }
fi
echo "Postgres healthy"

say "3/6 Applying migrations"
"$VENV/alembic" upgrade head

say "4/6 Checking corpus"
count=$(psql_q "select count(*) from statute_sections" 2>/dev/null || echo 0)
chunks=$(psql_q "select count(*) from kb_chunks where embedding is not null" 2>/dev/null || echo 0)
echo "sections=$count chunks=$chunks"
if [ "${count:-0}" -lt 100 ]; then
  echo "Corpus empty - fetching and parsing (needs internet, a few minutes)..."
  "$VENV/legaledge-kb" fetch
  "$VENV/legaledge-kb" parse
fi
if [ "${chunks:-0}" -lt 100 ]; then
  echo "Building the index (several minutes)..."
  "$VENV/legaledge-kb" index || { echo "Retrying index on CPU..."; MODEL_DEVICE=cpu "$VENV/legaledge-kb" index; }
fi

cleanup() { echo; echo "Stopping API and web..."; kill ${API_PID:-} ${WEB_PID:-} 2>/dev/null || true; }
trap cleanup EXIT INT TERM

say "5/6 Starting API on :8000  (log: var/logs/api.log)"
if have lsof; then
  lsof -ti -sTCP:LISTEN :8000 >/dev/null 2>&1 && die "Port 8000 is already in use. Run: lsof -i :8000  and stop that process."
else
  curl -fsS localhost:8000/v1/health >/dev/null 2>&1 && die "Port 8000 is already in use. Stop that process and re-run."
fi
"$VENV/uvicorn" app.main:app --app-dir apps/api --port 8000 > var/logs/api.log 2>&1 &
API_PID=$!
for i in $(seq 1 60); do curl -fsS localhost:8000/v1/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS localhost:8000/v1/health >/dev/null 2>&1 || { tail -30 var/logs/api.log; die "API did not start."; }
curl -s localhost:8000/v1/health; echo

say "6/6 Starting web on :8080  (log: var/logs/web.log)"
cd "$ROOT/legalai_frontend"
[ -d node_modules ] || npm install
npm run dev > "$ROOT/var/logs/web.log" 2>&1 &
WEB_PID=$!
for i in $(seq 1 30); do curl -fsS localhost:8080 >/dev/null 2>&1 && break; sleep 1; done

printf "\n\033[1;32mLegalEdge is running:\033[0m\n  App:      http://localhost:8080\n  API docs: http://localhost:8000/docs\n\nPress Ctrl+C to stop.\n"
if have open; then open http://localhost:8080 || true; fi
wait
