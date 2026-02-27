#!/bin/bash
set -e

VERSION="2.4.0"
RELEASE_DIR="kvanet-vpn-${VERSION}"

echo "📦 Создание релиза ${VERSION}..."

# Создание структуры
mkdir -p ${RELEASE_DIR}
mkdir -p ${RELEASE_DIR}/dist

# Копирование файлов
cp dist/kvanet-vpn ${RELEASE_DIR}/dist/
cp -r installers ${RELEASE_DIR}/
cp -r resources ${RELEASE_DIR}/
cp README.md ${RELEASE_DIR}/
cp LICENSE ${RELEASE_DIR}/

# Создание архива
tar -czf ${RELEASE_DIR}.tar.gz ${RELEASE_DIR}/

# Создание самораспаковывающегося архива для Linux
if command -v makeself &> /dev/null; then
    makeself --notemp ${RELEASE_DIR} kvanet-vpn-installer.run "Kvanet VPN Client Installer" ./installers/linux/install.sh
fi

echo "✅ Релиз создан: ${RELEASE_DIR}.tar.gz"
