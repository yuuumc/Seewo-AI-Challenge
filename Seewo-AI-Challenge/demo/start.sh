#!/bin/bash
# 希沃智教π Demo 启动脚本 (macOS / Linux)
#
# P0-1 安全 Blocker：生产/对外演示优先用 gunicorn（多 worker 防单点崩溃），
# 本地开发可退回 python3 app.py（仅 127.0.0.1，已防 RCE）。
#
# MIG-02: 默认 DEMO_AUTH_OPEN=0（生产安全默认）。本脚本显式开启 demo bypass，
# 适合比赛演示/本地开发。生产部署切勿复用本脚本（应走 demo/../Dockerfile / gunicorn）。

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     希沃智教π — AI智能作业批改系统       ║"
echo "  ║              Demo 启动中...               ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# MIG-02: 显式开启 demo 模式（绕过 CSRF / 鉴权 / 限流），便于本地演示
export DEMO_AUTH_OPEN=1

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [✗] 未检测到 Python3，请先安装"
    exit 1
fi
echo "  [✓] Python3 已就绪"

# Install dependencies（含 gunicorn）
echo "  [→] 检查依赖..."
pip3 install -r requirements.txt -q 2>/dev/null
echo "  [✓] 依赖已就绪"

# 优先用 gunicorn（生产模式），降级到 dev server（仅 127.0.0.1）
if command -v gunicorn &> /dev/null; then
    WORKERS=${GUNICORN_WORKERS:-2}
    BIND=${GUNICORN_BIND:-127.0.0.1:5000}
    echo "  [→] 用 gunicorn 启动（workers=$WORKERS bind=$BIND）..."
    echo "  ─────────────────────────────────────────"
    echo "    教师端:  http://localhost:5000/teacher"
    echo "    学生端:  http://localhost:5000/student"
    echo "    学情:    http://localhost:5000/teacher/analytics/hw_001"
    echo "    API:     http://localhost:5000/api/analytics/hw_001"
    echo "    按 Ctrl+C 停止服务"
    echo "  ─────────────────────────────────────────"
    echo ""
    gunicorn -c ../../gunicorn.conf.py \
        --workers "$WORKERS" \
        --bind "$BIND" \
        --chdir "$(pwd)" \
        "demo.app:app"
else
    echo "  [!] gunicorn 未安装，降级到 Flask dev server（仅 127.0.0.1）"
    echo "  [→] 启动服务..."
    echo "  ─────────────────────────────────────────"
    echo "    教师端:  http://localhost:5000/teacher"
    echo "    学生端:  http://localhost:5000/student"
    echo "    学情:    http://localhost:5000/teacher/analytics/hw_001"
    echo "    API:     http://localhost:5000/api/analytics/hw_001"
    echo "    按 Ctrl+C 停止服务"
    echo "  ─────────────────────────────────────────"
    echo ""
    # Open browser
    sleep 1
    open http://localhost:5000 2>/dev/null || xdg-open http://localhost:5000 2>/dev/null &
    python3 app.py
fi