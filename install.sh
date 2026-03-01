#!/bin/bash
set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функции логирования
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
    error "Пожалуйста, запустите install.sh с правами root (sudo)."
fi

# Определение дистрибутива
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID=$ID
        DISTRO_VERSION=$VERSION_ID
    else
        error "Не удалось определить дистрибутив Linux."
    fi
}

# Установка системных пакетов
install_system_packages() {
    info "Установка системных зависимостей для $DISTRO_ID..."

    case "$DISTRO_ID" in
        arch|manjaro)
            pacman -Sy --noconfirm --needed \
                python python-pip python-virtualenv \
                openvpn v2ray iptables tk curl wget git
            ;;
        debian|ubuntu|linuxmint|pop)
            apt update
            apt install -y \
                python3 python3-pip python3-venv \
                openvpn v2ray iptables python3-tk curl wget git
            ;;
        fedora|centos|rhel)
            dnf install -y \
                python3 python3-pip python3-virtualenv \
                openvpn v2ray iptables python3-tkinter curl wget git
            ;;
        opensuse*)
            zypper install -y \
                python3 python3-pip python3-virtualenv \
                openvpn v2ray iptables python3-tk curl wget git
            ;;
        *)
            warn "Дистрибутив $DISTRO_ID не поддерживается автоматической установкой."
            warn "Пожалуйста, установите следующие пакеты вручную:"
            echo "  - python3, python3-pip, python3-venv (или python-virtualenv)"
            echo "  - openvpn, v2ray, iptables"
            echo "  - tkinter для Python3 (python3-tk / python3-tkinter / tk)"
            echo "  - curl, wget, git"
            read -p "Нажмите Enter, чтобы продолжить после установки зависимостей..."
            ;;
    esac
}

# Создание группы kvanet и добавление текущего пользователя
setup_group() {
    info "Настройка группы kvanet..."
    if ! getent group kvanet >/dev/null; then
        groupadd kvanet
        info "Группа kvanet создана."
    else
        info "Группа kvanet уже существует."
    fi

    # Определяем пользователя, который запустил sudo
    REAL_USER=${SUDO_USER:-$(who am i | awk '{print $1}')}
    if [ -z "$REAL_USER" ] || [ "$REAL_USER" = "root" ]; then
        warn "Не удалось определить реального пользователя. Пропускаем добавление в группу."
    else
        usermod -aG kvanet "$REAL_USER"
        info "Пользователь $REAL_USER добавлен в группу kvanet."
        warn "Для применения изменений группы может потребоваться перелогиниться."
    fi
}

# Копирование файлов приложения
copy_app_files() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    APP_DIR="/opt/kvanet-vpn"

    info "Копирование файлов приложения в $APP_DIR ..."
    mkdir -p "$APP_DIR"
    cp -r "$SCRIPT_DIR"/* "$APP_DIR/"
    chown -R root:root "$APP_DIR"
    chmod -R 755 "$APP_DIR"
}

# Создание виртуального окружения и установка Python-зависимостей
setup_venv() {
    info "Создание виртуального окружения Python..."
    VENV_DIR="/opt/kvanet-vpn/venv"
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"

    # Устанавливаем зависимости
    REQUIREMENTS="/opt/kvanet-vpn/packaging/requirements.txt"
    if [ -f "$REQUIREMENTS" ]; then
        pip install --upgrade pip
        pip install -r "$REQUIREMENTS"
    else
        warn "Файл requirements.txt не найден. Устанавливаем базовые пакеты вручную."
        pip install --upgrade pip
        pip install customtkinter Pillow requests psutil
    fi
    deactivate
    info "Python-зависимости установлены."
}

# Создание скрипта запуска
create_launcher() {
    info "Создание исполняемого скрипта /usr/local/bin/kvanet-vpn ..."
    cat > /usr/local/bin/kvanet-vpn << 'EOF'
#!/bin/bash
# Launcher for Kvanet VPN Client

APP_DIR="/opt/kvanet-vpn"
VENV_PYTHON="$APP_DIR/venv/bin/python3"
MAIN_SCRIPT="$APP_DIR/src/kvanet_vpn.py"

# Проверяем, что запущено от root (через sudo)
if [ "$EUID" -ne 0 ]; then
    # Если не root – перезапускаем через sudo (правило NOPASSWD уже должно быть настроено)
    exec sudo "$VENV_PYTHON" "$MAIN_SCRIPT"
else
    # Уже root – запускаем напрямую
    exec "$VENV_PYTHON" "$MAIN_SCRIPT"
fi
EOF
    chmod 755 /usr/local/bin/kvanet-vpn
    info "Скрипт запуска создан."
}

# Создание .desktop файла
create_desktop_entry() {
    info "Создание ярлыка в меню приложений..."
    DESKTOP_FILE="/usr/share/applications/kvanet-vpn.desktop"
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Kvanet VPN Client
Comment=VPN клиент с поддержкой OpenVPN и V2Ray
Exec=/usr/local/bin/kvanet-vpn
Icon=/opt/kvanet-vpn/icon.png
Terminal=false
Type=Application
Categories=Network;
StartupWMClass=Kvanet VPN Client
EOF

    # Если есть иконка – скопировать, иначе создадим пустую (или используем стандартную)
    if [ ! -f "/opt/kvanet-vpn/icon.png" ]; then
        # Можно создать простую иконку из флага, но для простоты используем системную
        # Вместо этого просто укажем стандартную иконку приложения
        sed -i 's|Icon=.*|Icon=applications-internet|' "$DESKTOP_FILE"
    fi
    chmod 644 "$DESKTOP_FILE"
    info "Ярлык создан: $DESKTOP_FILE"
}

# Настройка sudoers для беспарольного запуска
setup_sudoers() {
    info "Настройка sudoers для группы kvanet..."
    SUDOERS_FILE="/etc/sudoers.d/kvanet"
    cat > "$SUDOERS_FILE" << EOF
# Разрешить группе kvanet запускать VPN-клиент без пароля
%kvanet ALL=(ALL) NOPASSWD: /opt/kvanet-vpn/venv/bin/python3 /opt/kvanet-vpn/src/kvanet_vpn.py
EOF
    chmod 440 "$SUDOERS_FILE"
    info "Правило sudoers добавлено."
}

# Создание пользователя и группы для V2Ray (если не существуют)
setup_v2ray_user() {
    info "Проверка пользователя v2ray_tproxy..."
    V2RAY_GID=23333
    V2RAY_UID=23333
    V2RAY_USER="v2ray_tproxy"

    if ! getent group "$V2RAY_USER" >/dev/null; then
        groupadd -g "$V2RAY_GID" "$V2RAY_USER"
        info "Группа $V2RAY_USER создана."
    fi

    if ! id -u "$V2RAY_USER" >/dev/null 2>&1; then
        useradd -r -s /bin/false -g "$V2RAY_GID" -u "$V2RAY_UID" "$V2RAY_USER"
        info "Пользователь $V2RAY_USER создан."
    else
        info "Пользователь $V2RAY_USER уже существует."
    fi
}

# Функция очистки (на случай ошибки)
cleanup_on_error() {
    error "Произошла ошибка. Выполняется откат..."
    # Можно добавить удаление созданных файлов, но для простоты просто выходим
}

# Точка входа
main() {
    trap cleanup_on_error ERR

    detect_distro
    install_system_packages
    setup_group
    copy_app_files
    setup_venv
    create_launcher
    create_desktop_entry
    setup_sudoers
    setup_v2ray_user

    info "✅ Установка завершена!"
    echo ""
    echo "Для запуска приложения:"
    echo "  1. Если вы были добавлены в группу kvanet, выйдите и зайдите снова (или выполните 'newgrp kvanet')."
    echo "  2. Запустите команду: kvanet-vpn (или найдите приложение в меню)."
    echo ""
    echo "При первом запуске может потребоваться ввести пароль sudo для настройки системы (правило NOPASSWD уже добавлено)."
}

main "$@"
