#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
    ubuntu|debian|linuxmint|pop|elementary|kali)
        apt update
        apt install -y openvpn v2ray iptables libcap2-bin procps
        ;;
    fedora|centos|rhel|rocky|almalinux)
        dnf install -y openvpn v2ray iptables libcap procps-ng
        ;;
    arch|manjaro|archcraft|endeavouros)
        pacman -S --noconfirm openvpn v2ray iptables libcap procps-ng
        ;;
    opensuse*|suse)
        zypper install -y openvpn v2ray iptables libcap procps
        ;;
    *)
        echo -e "${RED}❌ Неподдерживаемый дистрибутив. Установите вручную: openvpn, v2ray, iptables, libcap${NC}"
        exit 1
        ;;
esac

# Копирование бинарника
echo -e "${YELLOW}📋 Копирование исполняемого файла...${NC}"
cp dist/kvanet-vpn /usr/local/bin/kvanet-vpn
chmod 755 /usr/local/bin/kvanet-vpn

# Установка capabilities для v2ray (если бинарник уже есть)
if command -v v2ray &> /dev/null; then
    setcap cap_net_admin+ep /usr/bin/v2ray
    echo -e "${GREEN}✅ capabilities установлены для v2ray${NC}"
fi

# Создание пользователя v2ray_tproxy (если не существует)
if ! id -u v2ray_tproxy &>/dev/null; then
    useradd -r -s /bin/false -u 23333 v2ray_tproxy
    echo -e "${GREEN}✅ Пользователь v2ray_tproxy создан${NC}"
fi

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
StartupNotify=true
EOF

# Иконка (если есть)
mkdir -p /usr/local/share/kvanet-vpn
if [ -f "icon.png" ]; then
    cp icon.png /usr/local/share/kvanet-vpn/
fi

# Политика pkexec для беспарольного запуска (опционально)
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

# Включаем IP forwarding в sysctl (постоянно)
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.d/99-kvanet.conf
echo "net.ipv4.conf.lo.route_localnet=1" >> /etc/sysctl.d/99-kvanet.conf
echo "net.ipv4.conf.all.rp_filter=2" >> /etc/sysctl.d/99-kvanet.conf
echo "net.ipv4.conf.default.rp_filter=2" >> /etc/sysctl.d/99-kvanet.conf
sysctl -p /etc/sysctl.d/99-kvanet.conf

# Загружаем модуль xt_TPROXY при старте
echo "xt_TPROXY" >> /etc/modules-load.d/kvanet.conf
modprobe xt_TPROXY

echo -e "${GREEN}✅ Установка завершена!${NC}"
echo -e "${GREEN}Запустить можно из меню приложений или командой: pkexec kvanet-vpn${NC}"
