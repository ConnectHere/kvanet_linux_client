#!/bin/bash
set -e

echo "🔨 Сборка Kvanet VPN Client..."

# Активация виртуального окружения
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true

# Очистка старых сборок
rm -rf build dist

# Сборка
pyinstaller packaging/kvanet-vpn.spec

echo "✅ Сборка завершена! Бинарник: dist/kvanet-vpn"
