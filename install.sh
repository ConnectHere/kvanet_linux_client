#!/usr/bin/env bash
set -e

APP_NAME="kvanet-vpn"
INSTALL_DIR="/opt/kvanet-vpn"
DESKTOP_SYSTEM="/usr/share/applications/kvanet-vpn.desktop"

echo "=== Kvanet VPN installer ==="

# ------------------ ROOT CHECK ------------------
if [ "$EUID" -ne 0 ]; then
  echo "Запусти установку через sudo:"
  echo "sudo ./install.sh"
  exit 1
fi

# ------------------ DETECT DISTRO ------------------
echo "[1/6] Определение дистрибутива..."

if command -v pacman >/dev/null 2>&1; then
  PM="pacman"
elif command -v apt >/dev/null 2>&1; then
  PM="apt"
elif command -v dnf >/dev/null 2>&1; then
  PM="dnf"
else
  echo "❌ Неподдерживаемый дистрибутив"
  exit 1
fi

# ------------------ INSTALL SYSTEM DEPENDENCIES ------------------
echo "[2/6] Установка системных зависимостей..."

case "$PM" in
  pacman)
    pacman -Sy --noconfirm \
      python \
      python-virtualenv \
      openvpn \
      polkit \
      xdg-utils
    ;;
  apt)
    apt update
    apt install -y \
      python3 \
      python3-venv \
      python3-pip \
      openvpn \
      policykit-1 \
      xdg-utils
    ;;
  dnf)
    dnf install -y \
      python3 \
      python3-virtualenv \
      openvpn \
      polkit \
      xdg-utils
    ;;
esac

# ------------------ INSTALL APP FILES ------------------
echo "[3/6] Установка файлов приложения..."

mkdir -p "$INSTALL_DIR"
cp full.py "$INSTALL_DIR/"
cp icon.png "$INSTALL_DIR/"
cp titry.mp4 "$INSTALL_DIR/"
cp run_vpn.sh "$INSTALL_DIR/"

chmod 755 "$INSTALL_DIR/full.py"
chmod 755 "$INSTALL_DIR/run_vpn.sh"

# ------------------ CREATE VENV ------------------
echo "[4/6] Создание Python virtualenv..."

cd "$INSTALL_DIR"
python3 -m venv venv

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install \
  customtkinter \
  pillow \
  requests \
  psutil

# ------------------ CREATE DESKTOP ENTRY ------------------
echo "[5/6] Создание .desktop файла..."

cat > "$DESKTOP_SYSTEM" <<EOF
[Desktop Entry]
Name=Kvanet VPN
Comment=VPN клиент Kvanet
Exec= $INSTALL_DIR/run_vpn.sh
Icon=$INSTALL_DIR/icon.png
Terminal=false
Type=Application
Categories=Network;Security;
StartupNotify=true
EOF

chmod 644 "$DESKTOP_SYSTEM"

# ------------------ UPDATE DESKTOP DATABASE ------------------
echo "[6/6] Обновление базы приложений..."

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi

echo
echo "✅ Установка завершена"
echo "✅ Приложение доступно в меню приложений"
echo "✅ Root-пароль запрашивается через GUI"
