#!/bin/bash
# 🚀 Kvanet VPN Client Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/src" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="Kvanet VPN Client"

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не установлен. Установите его и попробуйте снова."
    exit 1
fi

# Создаём виртуальное окружение, если его нет
if [ ! -d "venv" ]; then
    echo "⚙️ Создание виртуального окружения..."
    python3 -m venv venv
    sudo ./venv/bin/pip install --upgrade pip
    sudo ./venv/bin/pip install -r requirements.txt
fi

echo "🔐 Запуск ${APP_NAME}..."
pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" bash -c "cd '$SCRIPT_DIR' && ../venv/bin/python3 kvanet_vpn.py"
