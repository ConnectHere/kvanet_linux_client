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
    OS_LIKE=$ID_LIKE
else
    echo -e "${RED}Не удалось определить ОС${NC}"
    exit 1
fi

# Функция установки пакетов
install_packages() {
    case $1 in
        debian|ubuntu|linuxmint|pop|elementary|kali)
            apt update
            apt install -y openvpn v2ray iptables libcap2-bin procps
            ;;
        fedora|centos|rhel|rocky|almalinux)
            dnf install -y openvpn v2ray iptables libcap procps-ng
            ;;
        arch|manjaro|archcraft|endeavouros|artix)
            pacman -S --noconfirm openvpn v2ray iptables libcap procps-ng
            ;;
        opensuse*|suse)
            zypper install -y openvpn v2ray iptables libcap procps
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

# Установка системных зависимостей
echo -e "${YELLOW}📦 Установка OpenVPN и V2Ray...${NC}"
if ! install_packages $OS; then
    if [ -n "$OS_LIKE" ]; then
        for like in $OS_LIKE; do
            if install_packages $like; then
                break
            fi
        done
    else
        echo -e "${RED}❌ Неподдерживаемый дистрибутив. Установите вручную: openvpn, v2ray, iptables, libcap${NC}"
        exit 1
    fi
fi

# Копирование бинарника
echo -e "${YELLOW}📋 Копирование исполняемого файла...${NC}"
cp ../../dist/kvanet-vpn /usr/local/bin/kvanet-vpn
chmod 755 /usr/local/bin/kvanet-vpn

# Установка capabilities для v2ray
if command -v v2ray &> /dev/null; then
    setcap cap_net_admin+ep /usr/bin/v2ray 2>/dev/null || echo -e "${YELLOW}⚠️ Не удалось установить capabilities для v2ray${NC}"
    echo -e "${GREEN}✅ capabilities установлены для v2ray${NC}"
fi

# Создание пользователя v2ray_tproxy
if ! id -u v2ray_tproxy &>/dev/null; then
    useradd -r -s /bin/false -u 23333 v2ray_tproxy 2>/dev/null || useradd -r -s /bin/false v2ray_tproxy
    echo -e "${GREEN}✅ Пользователь v2ray_tproxy создан${NC}"
fi

# Создание .desktop файла
echo -e "${YELLOW}🖥️ Создание ярлыка в меню...${NC}"
mkdir -p /usr/share/applications
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

# Иконка
mkdir -p /usr/local/share/kvanet-vpn
if [ -f "../../resources/icons/icon.png" ]; then
    cp ../../resources/icons/icon.png /usr/local/share/kvanet-vpn/
fi

# Политика pkexec
mkdir -p /usr/share/polkit-1/actions
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

# Настройка sysctl
cat > /etc/sysctl.d/99-kvanet.conf <<EOF
net.ipv4.ip_forward=1
net.ipv4.conf.lo.route_localnet=1
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
EOF
sysctl -p /etc/sysctl.d/99-kvanet.conf 2>/dev/null || echo -e "${YELLOW}⚠️ Перезагрузите систему для применения sysctl параметров${NC}"

# Загрузка модуля
mkdir -p /etc/modules-load.d
echo "xt_TPROXY" >> /etc/modules-load.d/kvanet.conf
modprobe xt_TPROXY 2>/dev/null || echo -e "${YELLOW}⚠️ Модуль xt_TPROXY не загружен (возможно, не требуется)${NC}"

echo -e "${GREEN}✅ Установка завершена!${NC}"
echo -e "${GREEN}Запустить можно из меню приложений или командой: pkexec kvanet-vpn${NC}"
