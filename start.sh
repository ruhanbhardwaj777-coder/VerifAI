#!/bin/bash
echo "────────────────────────────────────────"
echo " ⚡ Fact Checker AI"
echo "────────────────────────────────────────"
echo " Installing dependencies..."
pip install flask -q --break-system-packages 2>/dev/null || pip install flask -q
echo " Starting server on http://localhost:5050"
echo " Press Ctrl+C to stop."
echo "────────────────────────────────────────"
cd "$(dirname "$0")"
python3 app.py
