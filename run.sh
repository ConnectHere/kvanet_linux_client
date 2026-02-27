#!/bin/bash
# 🚀 Kvanet VPN Client Launcher

# Определяем корневую директорию проекта (там, где лежит этот скрипт)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="Kvanet VPN Client"

# Проверяем наличие Python3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не установлен. Установите его и попробуйте снова."
    exit 1
fi

# Путь к виртуальному окружению
VENV_DIR="$SCRIPT_DIR/venv"

# 1. Создаём виртуальное окружение, если его нет
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙️ Создание виртуального окружения в $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Активируем виртуальное окружение
source "$VENV_DIR/bin/activate"

# 3. Обновляем pip и устанавливаем зависимости
echo "📦 Установка необходимых Python-пакетов..."
pip install --upgrade pip > /dev/null

# Проверяем наличие requirements.txt
REQUIREMENTS_FILE="$SCRIPT_DIR/packaging/requirements.txt"
if [ -f "$REQUIREMENTS_FILE" ]; then
    pip install -r "$REQUIREMENTS_FILE"
else
    echo "⚠️ Файл requirements.txt не найден. Устанавливаем базовые пакеты вручную..."
    pip install customtkinter Pillow requests psutil
fi
pip install customtkinter
pip install pillow
pip install requests
pip install psutil
# 4. Деактивируем окружение (оно больше не нужно в текущей оболочке)
deactivate

# 5. Запускаем приложение с правами root через pkexec
echo "🔐 Запуск ${APP_NAME}..."
pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" bash -c "cd '$SCRIPT_DIR' && $VENV_DIR/bin/python3 src/kvanet_vpn.py"
