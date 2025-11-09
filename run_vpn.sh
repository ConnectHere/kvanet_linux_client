#!/bin/bash
# 🚀 Kvanet VPN Client Launcher

# Определяем директорию, где лежит скрипт
cd "$(dirname "$0")"

APP_NAME="Kvanet VPN Client"

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не установлен. Установите его и попробуйте снова."
    exit 1
fi

# Проверяем наличие OpenVPN
if ! command -v openvpn &> /dev/null; then
    echo "⚠️ OpenVPN не найден. Приложение может установить его автоматически."
fi

# Создаём виртуальное окружение, если его нет
if [ ! -d "venv" ]; then
    echo "⚙️ Создание виртуального окружения..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
fi

# Запуск приложения с правами суперпользователя
echo "🔐 Запуск ${APP_NAME}..."
sudo ./venv/bin/python3 full.py
