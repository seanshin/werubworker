#!/bin/bash
# WeruBWorker 전체 서비스 시작 (백엔드 + 프론트엔드)
# Usage: ./start.sh [--stop] [--restart] [--status]

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8765
FRONTEND_PORT=1420
GITEA_PORT=3000
VENV="$DIR/.venv"
GUI_DIR="$DIR/surfaces/gui"
TOKEN_FILE="$HOME/.config/werubworker/sidecar-$BACKEND_PORT.token"
LOG_DIR="$HOME/.config/werubworker/logs"
mkdir -p "$LOG_DIR"

_status() {
    local be_pid=$(lsof -ti :$BACKEND_PORT 2>/dev/null | head -1)
    local fe_pid=$(lsof -ti :$FRONTEND_PORT 2>/dev/null | head -1)
    local gitea_pid=$(lsof -ti :$GITEA_PORT 2>/dev/null | head -1)
    echo "=== WeruBWorker 서비스 상태 ==="
    if [ -n "$gitea_pid" ]; then
        echo "  Gitea    (:$GITEA_PORT): 실행 중 (PID $gitea_pid)"
    else
        echo "  Gitea    (:$GITEA_PORT): 중지됨"
    fi
    if [ -n "$be_pid" ]; then
        echo "  백엔드 (:$BACKEND_PORT): 실행 중 (PID $be_pid)"
    else
        echo "  백엔드 (:$BACKEND_PORT): 중지됨"
    fi
    if [ -n "$fe_pid" ]; then
        echo "  프론트엔드 (:$FRONTEND_PORT): 실행 중 (PID $fe_pid)"
    else
        echo "  프론트엔드 (:$FRONTEND_PORT): 중지됨"
    fi
}

_stop() {
    echo "서비스 중지 중..."
    lsof -ti :$FRONTEND_PORT 2>/dev/null | xargs kill -TERM 2>/dev/null
    lsof -ti :$BACKEND_PORT 2>/dev/null | xargs kill -TERM 2>/dev/null
    brew services stop gitea 2>/dev/null
    sleep 2
    echo "중지 완료"
}

_start() {
    # Gitea 시작
    local gitea_pid=$(lsof -ti :$GITEA_PORT 2>/dev/null | head -1)
    if [ -n "$gitea_pid" ]; then
        echo "Gitea 이미 실행 중 (PID $gitea_pid)"
    else
        echo "Gitea 시작 중..."
        brew services start gitea >> "$LOG_DIR/gitea.log" 2>&1
        sleep 2
        if lsof -ti :$GITEA_PORT >/dev/null 2>&1; then
            echo "Gitea 시작 완료 (port $GITEA_PORT)"
        else
            echo "Gitea 시작 실패! 로그: $LOG_DIR/gitea.log"
        fi
    fi

    # 백엔드 시작
    local be_pid=$(lsof -ti :$BACKEND_PORT 2>/dev/null | head -1)
    if [ -n "$be_pid" ]; then
        echo "백엔드 이미 실행 중 (PID $be_pid)"
    else
        echo "백엔드 시작 중..."
        "$VENV/bin/python" -m coworker.server.run --host 0.0.0.0 --port $BACKEND_PORT \
            >> "$LOG_DIR/backend.log" 2>&1 &
        sleep 3
        if lsof -ti :$BACKEND_PORT >/dev/null 2>&1; then
            echo "백엔드 시작 완료 (port $BACKEND_PORT)"
        else
            echo "백엔드 시작 실패! 로그: $LOG_DIR/backend.log"
            return 1
        fi
    fi

    # 토큰 대기
    for i in $(seq 1 10); do
        [ -f "$TOKEN_FILE" ] && break
        sleep 1
    done

    # 프론트엔드 시작
    local fe_pid=$(lsof -ti :$FRONTEND_PORT 2>/dev/null | head -1)
    if [ -n "$fe_pid" ]; then
        echo "프론트엔드 이미 실행 중 (PID $fe_pid)"
    else
        echo "프론트엔드 시작 중..."
        local token=$(cat "$TOKEN_FILE" 2>/dev/null | tr -d '\n')
        cd "$GUI_DIR"
        VITE_COWORKER_API_TOKEN="$token" npx vite --host 0.0.0.0 --port $FRONTEND_PORT \
            >> "$LOG_DIR/frontend.log" 2>&1 &
        sleep 4
        if lsof -ti :$FRONTEND_PORT >/dev/null 2>&1; then
            echo "프론트엔드 시작 완료 (port $FRONTEND_PORT)"
        else
            echo "프론트엔드 시작 실패! 로그: $LOG_DIR/frontend.log"
            return 1
        fi
    fi

    echo ""
    echo "=== WeruBWorker 서비스 시작 완료 ==="
    echo "  Gitea: http://localhost:$GITEA_PORT"
    echo "  GUI:   http://localhost:$FRONTEND_PORT"
    echo "  API:   http://localhost:$BACKEND_PORT"
    echo "  로그:  $LOG_DIR/"
}

case "${1:-start}" in
    --stop|-s)    _stop ;;
    --restart|-r) _stop; sleep 1; _start ;;
    --status|-t)  _status ;;
    start|*)      _start ;;
esac
