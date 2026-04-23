#!/usr/bin/env bash
# ── Folio — Start everything with one command ──────────────────
# Usage:  ./start.sh
#
# Starts Redis, Celery worker, and Daphne (Django ASGI server).
# Ctrl+C once to shut everything down cleanly.

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv/bin"
PIDFILE_REDIS="/tmp/folio_redis.pid"
PIDFILE_CELERY="/tmp/folio_celery.pid"
PIDFILE_SERVER="/tmp/folio_server.pid"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"

    for label_pid in "Daphne:$PIDFILE_SERVER" "Celery:$PIDFILE_CELERY"; do
        label="${label_pid%%:*}"
        pidfile="${label_pid##*:}"
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null
                wait "$pid" 2>/dev/null
                echo -e "  ${RED}Stopped${NC} $label (PID $pid)"
            fi
            rm -f "$pidfile"
        fi
    done

    # Stop Redis
    if [ -f "$PIDFILE_REDIS" ]; then
        pid=$(cat "$PIDFILE_REDIS")
        if kill -0 "$pid" 2>/dev/null; then
            redis-cli shutdown nosave 2>/dev/null || kill "$pid" 2>/dev/null
            echo -e "  ${RED}Stopped${NC} Redis (PID $pid)"
        fi
        rm -f "$PIDFILE_REDIS"
    fi

    echo -e "${GREEN}All services stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# ── 1. Redis ────────────────────────────────────────────────────
echo -e "${CYAN}[1/3] Redis${NC}"

# Kill any existing Redis
if pgrep -x redis-server >/dev/null 2>&1; then
    echo -e "  ${YELLOW}Killing existing Redis...${NC}"
    redis-cli shutdown nosave 2>/dev/null || pkill -x redis-server 2>/dev/null
    sleep 1
fi

redis-server --daemonize yes --pidfile "$PIDFILE_REDIS" --loglevel warning
echo -e "  ${GREEN}Redis started${NC} (PID $(cat "$PIDFILE_REDIS"))"

# ── 2. Celery ───────────────────────────────────────────────────
echo -e "${CYAN}[2/3] Celery worker${NC}"

cd "$DIR"
"$VENV/celery" -A portfolio_project worker --loglevel=info \
    > /tmp/folio_celery.log 2>&1 &
echo $! > "$PIDFILE_CELERY"
echo -e "  ${GREEN}Celery started${NC} (PID $(cat "$PIDFILE_CELERY"))  — logs: /tmp/folio_celery.log"

# ── 3. Django dev server (ASGI, auto-reload) ───────────────────
echo -e "${CYAN}[3/3] Django server${NC}"

"$VENV/python" "$DIR/manage.py" runserver 127.0.0.1:8000 \
    > /tmp/folio_server.log 2>&1 &
echo $! > "$PIDFILE_SERVER"
echo -e "  ${GREEN}Django started${NC} (PID $(cat "$PIDFILE_SERVER"))  — logs: /tmp/folio_server.log  (auto-reloads on code changes)"

# ── Ready ───────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}All services running!${NC}"
echo -e "  App:    ${CYAN}http://127.0.0.1:8000/${NC}"
echo -e "  Celery: ${CYAN}tail -f /tmp/folio_celery.log${NC}"
echo -e "  Server: ${CYAN}tail -f /tmp/folio_server.log${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop everything.${NC}"
echo ""

# Wait forever until Ctrl+C
wait
