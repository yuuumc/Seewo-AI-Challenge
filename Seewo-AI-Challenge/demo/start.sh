#!/bin/bash
# 希沃智教π Demo 启动脚本 (macOS / Linux)

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     希沃智教π — AI智能作业批改系统       ║"
echo "  ║              Demo 启动中...               ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [✗] 未检测到 Python3，请先安装"
    exit 1
fi
echo "  [✓] Python3 已就绪"

# Install dependencies
echo "  [→] 检查依赖..."
pip3 install flask -q 2>/dev/null
echo "  [✓] 依赖已就绪"

# Open browser
echo "  [→] 即将打开浏览器..."
sleep 1
open http://localhost:5000 2>/dev/null || xdg-open http://localhost:5000 2>/dev/null &

# Start Flask
echo "  [→] 启动服务..."
echo "  ─────────────────────────────────────────"
echo "    教师端:  http://localhost:5000/teacher"
echo "    学生端:  http://localhost:5000/student"
echo "    学情:    http://localhost:5000/teacher/analytics/hw_001"
echo "    API:     http://localhost:5000/api/analytics/hw_001"
echo "    按 Ctrl+C 停止服务"
echo "  ─────────────────────────────────────────"
echo ""
python3 app.py
