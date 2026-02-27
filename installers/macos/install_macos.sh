#!/bin/bash
set -e

echo "========================================"
echo " Установка Kvanet VPN Client для macOS"
echo "========================================"

# Проверка Homebrew
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew не установлен. Установите: https://brew.sh"
    exit 1
fi

# Установка OpenVPN
echo "📦 Установка OpenVPN..."
brew install openvpn

# Копирование бинарника
echo "📋 Копирование исполняемого файла..."
cp dist/kvanet-vpn /usr/local/bin/kvanet-vpn
chmod 755 /usr/local/bin/kvanet-vpn

# Создание .app пакета
APP_DIR="/Applications/KvanetVPN.app/Contents/MacOS"
mkdir -p "$APP_DIR"

cat > "$APP_DIR/KvanetVPN" <<EOF
#!/bin/bash
# Запрос прав администратора через AppleScript
osascript -e 'do shell script "/usr/local/bin/kvanet-vpn" with administrator privileges'
EOF
chmod +x "$APP_DIR/KvanetVPN"

# Info.plist
cat > "/Applications/KvanetVPN.app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>KvanetVPN</string>
    <key>CFBundleIdentifier</key>
    <string>org.kvanet.vpn</string>
    <key>CFBundleName</key>
    <string>KvanetVPN</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.10</string>
</dict>
</plist>
EOF

# Иконка (опционально)
if [ -f "icon.icns" ]; then
    mkdir -p "/Applications/KvanetVPN.app/Contents/Resources"
    cp icon.icns "/Applications/KvanetVPN.app/Contents/Resources/"
fi

# Добавляем OpenVPN в PATH для запуска через скрипт
# Можно также создать симлинк
if [ ! -f /usr/local/bin/openvpn ]; then
    ln -s "$(brew --prefix openvpn)/sbin/openvpn" /usr/local/bin/openvpn
fi

echo "✅ Установка завершена! Приложение в папке /Applications."
