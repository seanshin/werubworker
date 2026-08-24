#!/bin/bash
# WeruBWorker 전체 서비스 시작 (백엔드 + 프론트엔드)
# Usage: ./start.sh [--stop] [--restart] [--status]

DIR="$(cd "$(dirname "$0")" && pwd)"

# launchd는 최소 PATH(/usr/bin:/bin:/usr/sbin:/sbin)로 실행하므로 brew,
# gitea-runner, npx를 찾지 못한다. 로그인 시 자동 시작이 조용히 실패하지
# 않도록 여기서 보강한다.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

BACKEND_PORT=8765
FRONTEND_PORT=1420
GITEA_PORT=3000
RUNNER_CONFIG="/opt/homebrew/etc/gitea-runner/config.yaml"
RUNNER_DIR="/opt/homebrew/etc/gitea-runner"
VENV="$DIR/.venv"
GUI_DIR="$DIR/surfaces/gui"
TOKEN_FILE="$HOME/.config/werubworker/sidecar-$BACKEND_PORT.token"
LOG_DIR="$HOME/.config/werubworker/logs"
mkdir -p "$LOG_DIR"

# 해당 포트를 LISTEN 중인 PID만 반환한다.
# `lsof -ti :PORT`는 그 포트에 '연결된' 클라이언트(브라우저 등)까지 함께
# 잡아내므로, 그대로 kill하면 엉뚱한 프로세스가 종료된다.
_port_pid() {
    lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null
}

# 포트가 LISTEN 상태가 될 때까지 최대 $2초(기본 20초) 기다린다.
# 고정 sleep은 콜드 스타트(로그인 직후 등)에서 너무 짧아 정상 기동을
# 실패로 오판한다.
_wait_port() {
    local port=$1 limit=${2:-20} i=0
    while [ $i -lt $limit ]; do
        _port_pid "$port" | grep -q . && return 0
        sleep 1
        i=$((i + 1))
    done
    return 1
}

_status() {
    local be_pid=$(_port_pid $BACKEND_PORT | head -1)
    local fe_pid=$(_port_pid $FRONTEND_PORT | head -1)
    local gitea_pid=$(_port_pid $GITEA_PORT | head -1)
    local runner_pid=$(pgrep -f "gitea-runner daemon" 2>/dev/null | head -1)
    echo "=== WeruBWorker 서비스 상태 ==="
    if [ -n "$gitea_pid" ]; then
        echo "  Gitea    (:$GITEA_PORT): 실행 중 (PID $gitea_pid)"
    else
        echo "  Gitea    (:$GITEA_PORT): 중지됨"
    fi
    if [ -n "$runner_pid" ]; then
        echo "  Runner          : 실행 중 (PID $runner_pid)"
    else
        echo "  Runner          : 중지됨"
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
    _port_pid $FRONTEND_PORT | xargs kill -TERM 2>/dev/null
    _port_pid $BACKEND_PORT | xargs kill -TERM 2>/dev/null
    pkill -f "gitea-runner daemon" 2>/dev/null
    brew services stop gitea 2>/dev/null
    sleep 2
    echo "중지 완료"
}

_start() {
    # Gitea 시작
    local gitea_pid=$(_port_pid $GITEA_PORT | head -1)
    if [ -n "$gitea_pid" ]; then
        echo "Gitea 이미 실행 중 (PID $gitea_pid)"
    else
        echo "Gitea 시작 중..."
        brew services start gitea >> "$LOG_DIR/gitea.log" 2>&1
        if _wait_port $GITEA_PORT 15; then
            echo "Gitea 시작 완료 (port $GITEA_PORT)"
        else
            echo "Gitea 시작 실패! 로그: $LOG_DIR/gitea.log"
        fi
    fi

    # Gitea Runner 시작
    local runner_pid=$(pgrep -f "gitea-runner daemon" 2>/dev/null | head -1)
    if [ -n "$runner_pid" ]; then
        echo "Runner 이미 실행 중 (PID $runner_pid)"
    else
        echo "Runner 시작 중..."
        cd "$RUNNER_DIR"
        gitea-runner daemon --config "$RUNNER_CONFIG" >> "$LOG_DIR/runner.log" 2>&1 &
        cd "$DIR"
        sleep 1
        if pgrep -f "gitea-runner daemon" >/dev/null 2>&1; then
            echo "Runner 시작 완료"
        else
            echo "Runner 시작 실패! 로그: $LOG_DIR/runner.log"
        fi
    fi

    # 백엔드 시작
    local be_pid=$(_port_pid $BACKEND_PORT | head -1)
    if [ -n "$be_pid" ]; then
        echo "백엔드 이미 실행 중 (PID $be_pid)"
    else
        echo "백엔드 시작 중..."
        "$VENV/bin/python" -m coworker.server.run --host 0.0.0.0 --port $BACKEND_PORT \
            >> "$LOG_DIR/backend.log" 2>&1 &
        if _wait_port $BACKEND_PORT 30; then
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
    local fe_pid=$(_port_pid $FRONTEND_PORT | head -1)
    if [ -n "$fe_pid" ]; then
        echo "프론트엔드 이미 실행 중 (PID $fe_pid)"
    else
        echo "프론트엔드 시작 중..."
        local token=$(cat "$TOKEN_FILE" 2>/dev/null | tr -d '\n')
        cd "$GUI_DIR"
        VITE_COWORKER_API_TOKEN="$token" npx vite --host 0.0.0.0 --port $FRONTEND_PORT \
            >> "$LOG_DIR/frontend.log" 2>&1 &
        if _wait_port $FRONTEND_PORT 30; then
            echo "프론트엔드 시작 완료 (port $FRONTEND_PORT)"
        else
            echo "프론트엔드 시작 실패! 로그: $LOG_DIR/frontend.log"
            return 1
        fi
    fi

    echo ""
    echo "=== WeruBWorker 서비스 시작 완료 ==="
    echo "  Gitea:  http://localhost:$GITEA_PORT"
    echo "  Runner: imac-runner (Actions)"
    echo "  GUI:    http://localhost:$FRONTEND_PORT"
    echo "  API:    http://localhost:$BACKEND_PORT"
    echo "  로그:   $LOG_DIR/"
}

case "${1:-start}" in
    --stop|-s)    _stop ;;
    --restart|-r) _stop; sleep 1; _start ;;
    --status|-t)  _status ;;
    start|*)      _start ;;
esac
