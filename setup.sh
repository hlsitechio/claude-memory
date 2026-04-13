#!/bin/bash
# Memory Engine — Linux/Mac Quick Setup
set -e

echo "[*] Memory Engine — Setup"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[-] Python3 not found"
    exit 1
fi

# Install deps
echo "[*] Installing dependencies..."
pip3 install -r requirements.txt
echo

# Run setup
echo "[*] Running setup..."
python3 setup.py
echo

echo "[+] Done!"
echo "[>] Start viewer: python3 memory_engine/viewer.py"
echo "[i] Dashboard: http://localhost:37888"
