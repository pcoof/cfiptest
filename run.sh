#!/bin/bash
echo "[CF IP Tester] Installing dependencies..."
python3 -m pip install pywebview -q
echo "[CF IP Tester] Starting..."
python3 main.py "$@"
