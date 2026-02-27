# Kvanet VPN Client

Защищённый VPN клиент с поддержкой V2Ray (Linux) и OpenVPN (Linux/macOS).

## Системные требования

### Linux
- OpenVPN
- V2Ray (опционально, для быстрого подключения)
- iptables
- libcap (для установки capabilities)

### macOS
- OpenVPN (устанавливается через Homebrew)
- Homebrew

## Установка

### Linux
```bash
tar -xzf kvanet-vpn-2.4.0.tar.gz
cd kvanet-vpn-2.4.0
sudo ./installers/linux/install.sh
