#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    error "Пожалуйста, запустите uninstall.sh с правами root (sudo)."
fi

confirm() {
    read -p "$1 (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        return 1
    fi
}

# Удаление файлов приложения
remove_app_files() {
    info "Удаление файлов приложения из /opt/kvanet-vpn ..."
    rm -rf /opt/kvanet-vpn
}

# Удаление скрипта запуска
remove_launcher() {
    info "Удаление /usr/local/bin/kvanet-vpn ..."
    rm -f /usr/local/bin/kvanet-vpn
}

# Удаление .desktop файла
remove_desktop() {
    info "Удаление ярлыка из меню ..."
    rm -f /usr/share/applications/kvanet-vpn.desktop
}

# Удаление правила sudoers
remove_sudoers() {
    info "Удаление правила sudoers ..."
    rm -f /etc/sudoers.d/kvanet
}

# Удаление пользователя и группы v2ray_tproxy
remove_v2ray_user() {
    if confirm "Удалить пользователя и группу v2ray_tproxy?"; then
        if id -u v2ray_tproxy >/dev/null 2>&1; then
            userdel v2ray_tproxy
            info "Пользователь v2ray_tproxy удалён."
        fi
        if getent group v2ray_tproxy >/dev/null; then
            groupdel v2ray_tproxy
            info "Группа v2ray_tproxy удалена."
        fi
    else
        info "Пользователь v2ray_tproxy оставлен."
    fi
}

# Удаление группы kvanet
remove_kvanet_group() {
    if confirm "Удалить группу kvanet? (Внимание: все пользователи будут исключены из группы)"; then
        # Удаляем группу только если она пуста или после удаления пользователей
        # Но проще удалить принудительно (groupdel удалит, если группа не является primary ни для одного пользователя)
        if getent group kvanet >/dev/null; then
            groupdel kvanet
            info "Группа kvanet удалена."
        else
            info "Группа kvanet не существует."
        fi
    else
        info "Группа kvanet оставлена."
    fi
}

# (Опционально) удаление установленных пакетов
remove_packages() {
    if confirm "Удалить системные пакеты (python3, openvpn, v2ray и т.д.)? Это может затронуть другие программы."; then
        warn "Удаление пакетов не реализовано автоматически, чтобы не сломать систему."
        warn "Вы можете удалить их вручную через ваш пакетный менеджер."
    fi
}

main() {
    remove_app_files
    remove_launcher
    remove_desktop
    remove_sudoers
    remove_v2ray_user
    remove_kvanet_group
    remove_packages

    info "✅ Удаление завершено."
}

main "$@"
