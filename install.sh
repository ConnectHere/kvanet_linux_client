#!/bin/bash
set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} Установка Kvanet VPN Client${NC}"
echo -e "${GREEN}========================================${NC}"

# Проверка root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Пожалуйста, запустите с sudo или от root${NC}"
    exit 1
fi

# Определение дистрибутива
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo -e "${RED}Не удалось определить ОС${NC}"
    exit 1
fi

# Установка системных зависимостей
echo -e "${YELLOW}📦 Установка OpenVPN и V2Ray...${NC}"
case $OS in
    ubuntu|debian)
        apt update
        apt install -y openvpn v2ray
        ;;
    fedora|centos|rhel)
        dnf install -y openvpn v2ray
        ;;
    arch)
        pacman -S --noconfirm openvpn v2ray
        ;;
    *)
        echo -e "${RED}❌ Неподдерживаемый дистрибутив. Установите OpenVPN и V2Ray вручную.${NC}"
        exit 1
        ;;
esac

# Копирование бинарника
echo -e "${YELLOW}📋 Копирование исполняемого файла...${NC}"
cp dist/kvanet-vpn /usr/local/bin/kvanet-vpn
chmod 755 /usr/local/bin/kvanet-vpn

# Создание .desktop файла
echo -e "${YELLOW}🖥️ Создание ярлыка в меню...${NC}"
cat > /usr/share/applications/kvanet-vpn.desktop <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Kvanet VPN
Comment=Kvanet VPN Client
Exec=pkexec env DISPLAY=\$DISPLAY XAUTHORITY=\$XAUTHORITY /usr/local/bin/kvanet-vpn
Icon=/usr/local/share/kvanet-vpn/icon.png
Terminal=false
Categories=Network;
EOF

# Создание иконки (если есть файл icon.png)
mkdir -p /usr/local/share/kvanet-vpn
if [ -f "icon.png" ]; then
    cp icon.png /usr/local/share/kvanet-vpn/
else
    # Скачать дефолтную иконку или использовать системную
    echo -e "${YELLOW}⚠️  Файл icon.png не найден, ярлык будет без иконки${NC}"
fi

# Настройка pkexec для беспарольного запуска (опционально)
echo -e "${YELLOW}🔐 Настройка прав для pkexec...${NC}"
cat > /usr/share/polkit-1/actions/org.kvanet.vpn.policy <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="org.kvanet.vpn.run">
    <description>Run Kvanet VPN Client</description>
    <message>Authentication is required to run Kvanet VPN Client</message>
    <defaults>
      <allow_any>auth_admin_keep</allow_any>
      <allow_inactive>auth_admin_keep</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/kvanet-vpn</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
EOF

echo -e "${GREEN}✅ Установка завершена!${NC}"
echo -e "${GREEN}Запустить можно из меню приложений или командой: pkexec kvanet-vpn${NC}"
