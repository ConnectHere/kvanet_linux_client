#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kvanet VPN Client
Объединённая версия с поддержкой V2Ray (RU и NL) и OpenVPN
"""

import customtkinter as ctk
from PIL import Image, ImageDraw
import os
import time
import threading
import subprocess
import requests
import sys
import psutil
import tempfile
import json
from pathlib import Path
from tkinter import messagebox
import pwd
import grp
import ssl
import urllib3
import signal
import atexit
import re
import socket
import fcntl
import struct

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------ Глобальные переменные ------------------
current_user_global = None
current_password_global = None
API_BASE_URL = "https://xn--80adkrr5a.xn--p1ai"

# IP адреса серверов
SERVER_IP_RU = "95.163.232.136"
SERVER_IP_NL = "147.45.255.17"

# Настройка темы
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ------------------ VPN MANAGER (улучшенный) ------------------
class VPNManager:
    """
    Управление VPN подключениями с поддержкой V2Ray (RU и NL) и OpenVPN.
    Реализация V2Ray основана на отдельных скриптах vpn-activate-*.py
    """
    def __init__(self):
        # OpenVPN
        self.openvpn_process = None
        self.temp_ovpn_path = None
        self.openvpn_log_file = None

        # V2Ray
        self.v2ray_process = None
        self.v2ray_rules_cleanup_needed = False
        self.v2ray_pid = None
        self.v2ray_temp_config = None
        self.v2ray_log_file = "/var/log/v2ray-tproxy-debug.log"
        self.v2ray_pid_file = "/var/run/v2ray-tproxy.pid"

        # Общее состояние
        self.is_connected = False
        self.log_callback = None
        self.failed_attempts = 0
        self.expected_ip = None
        self.current_server = None
        self.current_login = None
        self.current_password = None
        self.current_vpn_type = None
        self.current_protocol = None  # 'v2ray' или 'openvpn'
        self.last_regeneration_time = 0
        
        # Параметры V2Ray
        self.TPROXY_PORT = 12345
        self.V2RAY_BIN = "v2ray"
        self.V2RAY_GID = 23333
        self.V2RAY_USER = "v2ray_tproxy"
        
        # Регистрируем очистку при выходе
        atexit.register(self.cleanup_all)

    def _check_and_fix_system_for_v2ray(self):
        """Проверка и настройка системы для работы V2Ray с TProxy"""
        self.log("🔧 Проверка системных параметров для V2Ray...")

        # 1. Загрузка модуля xt_TPROXY
        try:
            subprocess.run(['modprobe', 'xt_TPROXY'], check=False, stderr=subprocess.DEVNULL)
            self.log("✅ Модуль xt_TPROXY загружен (или уже загружен)")
        except Exception as e:
            self.log(f"⚠️ Ошибка загрузки xt_TPROXY: {e}")

        # 2. Включение IP forwarding
        try:
            subprocess.run(['sysctl', '-w', 'net.ipv4.ip_forward=1'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log("✅ IP forwarding включён")
        except Exception as e:
            self.log(f"⚠️ Не удалось включить IP forwarding: {e}")

        # 3. Разрешить маршрутизацию на loopback
        try:
            subprocess.run(['sysctl', '-w', 'net.ipv4.conf.lo.route_localnet=1'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log("✅ route_localnet на lo включён")
        except Exception as e:
            self.log(f"⚠️ Не удалось установить route_localnet: {e}")

        # 4. Установка rp_filter в 2 (широкий режим)
        try:
            subprocess.run(['sysctl', '-w', 'net.ipv4.conf.all.rp_filter=2'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['sysctl', '-w', 'net.ipv4.conf.default.rp_filter=2'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log("✅ Reverse path filter установлен в 2")
        except Exception as e:
            self.log(f"⚠️ Не удалось установить rp_filter: {e}")

        # 5. Проверка GID пользователя v2ray_tproxy
        try:
            user = pwd.getpwnam(self.V2RAY_USER)
            if user.pw_gid != self.V2RAY_GID:
                self.log(f"⚠️ GID пользователя {self.V2RAY_USER} не совпадает с {self.V2RAY_GID}. Попытка исправить...")
                # Меняем основную группу
                subprocess.run(['usermod', '-g', str(self.V2RAY_GID), self.V2RAY_USER], check=True)
                self.log("✅ GID исправлен")
            else:
                self.log(f"✅ GID пользователя {self.V2RAY_USER} корректен")
        except Exception as e:
            self.log(f"⚠️ Ошибка проверки GID: {e}")

        # 6. Установка capabilities для бинарника v2ray
        try:
            # Проверяем текущие capabilities
            result = subprocess.run(['getcap', self.V2RAY_BIN], capture_output=True, text=True)
            if 'cap_net_admin+ep' not in result.stdout:
                self.log("Устанавливаем cap_net_admin+ep для v2ray...")
                subprocess.run(['setcap', 'cap_net_admin+ep', self.V2RAY_BIN], check=True)
                self.log("✅ capabilities установлены")
            else:
                self.log("✅ capabilities уже установлены")
        except Exception as e:
            self.log(f"⚠️ Не удалось установить capabilities: {e}")

        # 7. Отключение известных фаерволов (аккуратно, чтобы не навредить)
        self._disable_firewalls()

    def _disable_firewalls(self):
        """Попытка отключить ufw и firewalld, если они активны"""
        # ufw
        try:
            result = subprocess.run(['ufw', 'status'], capture_output=True, text=True)
            if 'active' in result.stdout:
                self.log("🔴 Обнаружен ufw, отключаем...")
                subprocess.run(['ufw', 'disable'], check=True)
                self.log("✅ ufw отключён")
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"⚠️ Ошибка при отключении ufw: {e}")

        # firewalld
        try:
            result = subprocess.run(['systemctl', 'is-active', 'firewalld'], capture_output=True, text=True)
            if result.returncode == 0:
                self.log("🔴 Обнаружен firewalld, останавливаем...")
                subprocess.run(['systemctl', 'stop', 'firewalld'], check=True)
                subprocess.run(['systemctl', 'disable', 'firewalld'], check=True)
                self.log("✅ firewalld остановлен и отключён")
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"⚠️ Ошибка при остановке firewalld: {e}")

        # Также можно очистить все правила iptables (рискованно)
        # Лучше просто проверить, что политики ACCEPT
        try:
            # Сохраняем текущие правила на случай восстановления?
            subprocess.run(['iptables', '-P', 'INPUT', 'ACCEPT'], check=False)
            subprocess.run(['iptables', '-P', 'FORWARD', 'ACCEPT'], check=False)
            subprocess.run(['iptables', '-P', 'OUTPUT', 'ACCEPT'], check=False)
        except:
            pass

    
    def set_log_callback(self, cb):
        self.log_callback = cb

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        # Также пишем в общий лог-файл V2Ray для отладки
        try:
            with open(self.v2ray_log_file, 'a') as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except:
            pass

    def is_admin(self):
        try:
            return os.geteuid() == 0
        except:
            return False

    def is_openvpn_installed(self):
        result = subprocess.run(["which", "openvpn"], capture_output=True, text=True)
        self.log(f"🔍 Проверка OpenVPN: which openvpn -> {result.returncode}, path: {result.stdout.strip()}")
        return result.returncode == 0

    def is_v2ray_installed(self):
        return subprocess.run(["which", self.V2RAY_BIN], capture_output=True).returncode == 0

    def get_public_ip(self):
        """Получение текущего публичного IP с подробным логированием"""
        self.log("🌐 Запрос текущего публичного IP...")
        for url in ["https://api.ipify.org", "https://ident.me", "https://icanhazip.com"]:
            try:
                self.log(f"  ➜ Пробуем {url}")
                r = requests.get(url, timeout=5, verify=False)
                if r.status_code == 200:
                    ip = r.text.strip()
                    # Проверяем, что это валидный IP
                    try:
                        socket.inet_aton(ip)
                        self.log(f"  ✅ Получен IP: {ip}")
                        return ip
                    except socket.error:
                        self.log(f"  ❌ Получен невалидный IP: {ip}")
                        continue
            except requests.exceptions.Timeout:
                self.log(f"  ⏰ Таймаут {url}")
            except requests.exceptions.ConnectionError as e:
                self.log(f"  🔌 Ошибка подключения к {url}: {e}")
            except Exception as e:
                self.log(f"  ❌ Ошибка {url}: {e}")
        self.log("  ❌ Не удалось получить IP ни с одного сервера")
        return None

    def check_network_interfaces(self):
        """Проверка сетевых интерфейсов для диагностики"""
        try:
            self.log("🔍 Проверка сетевых интерфейсов:")
            result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'tun' in line or 'tap' in line or 'UP' in line:
                    self.log(f"  📡 {line.strip()}")
            
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True)
            self.log("📋 Таблица маршрутизации:")
            for line in result.stdout.split('\n')[:10]:  # Первые 10 строк
                if line.strip():
                    self.log(f"  🛣️  {line.strip()}")
        except Exception as e:
            self.log(f"⚠️ Ошибка проверки интерфейсов: {e}")

    # ------------------ OpenVPN методы (без изменений) ------------------
    def regenerate_ovpn_config(self, vpn_type, login, password):
        """Перегенерация OVPN конфига через API"""
        self.log(f"🔄 ЗАПРОС ПЕРЕГЕНЕРАЦИИ OVPN КОНФИГА ({vpn_type})")
        self.log(f"   Логин: {login}, Тип: {vpn_type}")
        
        try:
            self.log(f"   Отправка запроса на {API_BASE_URL}/api/app/regenerate-ovpn")
            r = requests.post(
                f"{API_BASE_URL}/api/app/regenerate-ovpn",
                json={
                    "login": login,
                    "password": password,
                    "type": vpn_type,
                    "reason": "manual"
                },
                timeout=15,
                verify=False
            )
            self.log(f"   Код ответа: {r.status_code}")
            
            data = r.json()
            self.log(f"   Ответ сервера: {data}")
            
            if data.get("success"):
                self.log(f"✅ OVPN конфиг перегенерирован успешно")
                return True
            else:
                self.log(f"❌ Ошибка сервера: {data.get('error')}")
                return False
                
        except requests.exceptions.Timeout:
            self.log("❌ Таймаут запроса перегенерации")
            return False
        except Exception as e:
            self.log(f"❌ Ошибка запроса перегенерации: {e}")
            return False

    def cleanup_temp_files(self):
        """Очистка старых временных OVPN файлов"""
        self.log("🧹 Очистка временных файлов...")
        try:
            temp_dir = tempfile.gettempdir()
            count = 0
            for filename in os.listdir(temp_dir):
                if filename.endswith('.ovpn') and 'tmp' in filename:
                    filepath = os.path.join(temp_dir, filename)
                    try:
                        if os.path.getmtime(filepath) < time.time() - 3600:
                            os.remove(filepath)
                            count += 1
                    except:
                        pass
            if count > 0:
                self.log(f"   Удалено старых файлов: {count}")
        except Exception as e:
            self.log(f"   Ошибка очистки: {e}")

    def test_vpn_connection_direct(self, server_ip, port=31337):
        """Прямая проверка доступности VPN сервера"""
        self.log(f"🔌 Проверка доступности сервера {server_ip}:{port}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((server_ip, port))
            if result == 0:
                self.log(f"  ✅ Сервер {server_ip}:{port} доступен")
                sock.close()
                return True
            else:
                self.log(f"  ❌ Сервер {server_ip}:{port} недоступен (код: {result})")
                sock.close()
                return False
        except Exception as e:
            self.log(f"  ❌ Ошибка проверки сервера: {e}")
            return False

    def connect_openvpn(self, vpn_type, login, password):
        """
        Подключение через OpenVPN (без изменений, сохранено из оригинала)
        """
        self.log("=" * 60)
        self.log("🔌 НАЧАЛО ПОДКЛЮЧЕНИЯ OPENVPN")
        self.log("=" * 60)
        
        if not self.is_admin():
            self.log("❌ НЕТ ПРАВ ROOT - требуется sudo")
            return False

        if not self.is_openvpn_installed():
            self.log("❌ OpenVPN НЕ УСТАНОВЛЕН")
            return False

        if vpn_type == "ru":
            self.expected_ip = SERVER_IP_RU
            server_name = "Россия"
            server_ip = SERVER_IP_RU
        else:
            self.expected_ip = SERVER_IP_NL
            server_name = "Нидерланды"
            server_ip = SERVER_IP_NL

        self.current_server = server_name
        self.current_vpn_type = vpn_type
        
        self.log(f"🌍 СЕРВЕР: {server_name}")
        self.log(f"🎯 ОЖИДАЕМЫЙ IP: {self.expected_ip}")
        self.log(f"🔢 ТЕКУЩИЙ ПОЛЬЗОВАТЕЛЬ: {login}")

        self.test_vpn_connection_direct(server_ip)
        self.check_network_interfaces()

        if self.failed_attempts >= 5:
            current_time = time.time()
            if current_time - self.last_regeneration_time > 1800:
                self.log(f"⚠️ МНОГО НЕУДАЧНЫХ ПОПЫТОК ({self.failed_attempts}), ПЕРЕГЕНЕРИРУЕМ КОНФИГ")
                success = self.regenerate_ovpn_config(vpn_type, login, password)
                if success:
                    self.log("✅ КОНФИГ ПЕРЕГЕНЕРИРОВАН")
                    time.sleep(2)
                else:
                    self.log("❌ НЕ УДАЛОСЬ ПЕРЕГЕНЕРИРОВАТЬ КОНФИГ")
                    self.failed_attempts += 1
                    return False
            else:
                self.log(f"⚠️ МНОГО НЕУДАЧНЫХ ПОПЫТОК, НО ПЕРЕГЕНЕРАЦИЯ БЫЛА НЕДАВНО")
                self.failed_attempts += 1
                return False

        self.cleanup_temp_files()

        self.log("📡 ЗАПРОС OVPN КОНФИГА С СЕРВЕРА...")
        try:
            self.log(f"   URL: {API_BASE_URL}/api/app/get-ovpn")
            self.log(f"   Данные: login={login}, type={vpn_type}")
            
            r = requests.post(
                f"{API_BASE_URL}/api/app/get-ovpn",
                json={
                    "login": login,
                    "password": password,
                    "type": vpn_type
                },
                timeout=15,
                verify=False
            )
            self.log(f"   Код ответа HTTP: {r.status_code}")
            
            data = r.json()
            self.log(f"   Ответ сервера: success={data.get('success')}")
            
            if 'error' in data:
                self.log(f"   Ошибка сервера: {data['error']}")
                
        except requests.exceptions.Timeout:
            self.log("❌ ТАЙМАУТ ЗАПРОСА КОНФИГА")
            self.failed_attempts += 1
            return False
        except Exception as e:
            self.log(f"❌ ОШИБКА API: {e}")
            self.failed_attempts += 1
            return False

        if not data.get("success"):
            self.log(f"❌ НЕУСПЕШНЫЙ ОТВЕТ СЕРВЕРА")
            self.failed_attempts += 1
            return False

        ovpn_text = data["ovpn"]
        self.log(f"📄 ПОЛУЧЕН КОНФИГ, РАЗМЕР: {len(ovpn_text)} БАЙТ")
        
        first_lines = ovpn_text.split('\n')[:5]
        self.log("📋 ПЕРВЫЕ СТРОКИ КОНФИГА:")
        for i, line in enumerate(first_lines):
            self.log(f"   {i+1}: {line[:50]}..." if len(line) > 50 else f"   {i+1}: {line}")

        self.log("💾 СОХРАНЕНИЕ ВРЕМЕННОГО КОНФИГА...")
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ovpn", mode='w')
            tmp.write(ovpn_text)
            tmp.close()
            self.temp_ovpn_path = tmp.name
            self.log(f"📁 ПУТЬ К КОНФИГУ: {self.temp_ovpn_path}")
            
            if os.path.exists(self.temp_ovpn_path):
                self.log(f"   ✅ Файл создан, размер: {os.path.getsize(self.temp_ovpn_path)} байт")
                stats = os.stat(self.temp_ovpn_path)
                self.log(f"   🔐 Права: {oct(stats.st_mode)[-3:]}, владелец: {stats.st_uid}")
            else:
                self.log(f"   ❌ Файл НЕ создан!")
                
        except Exception as e:
            self.log(f"❌ ОШИБКА СОЗДАНИЯ ВРЕМЕННОГО ФАЙЛА: {e}")
            self.failed_attempts += 1
            return False

        self.log("🚀 ЗАПУСК ПОТОКА OPENVPN...")
        thread = threading.Thread(target=self._run_openvpn, args=(login, password, server_name), daemon=True)
        thread.start()
        self.log("✅ ПОТОК ЗАПУЩЕН")
        
        return True

    def _run_openvpn(self, login, password, server_name):
        """Запуск OpenVPN (без изменений, сохранено из оригинала)"""
        self.log("-" * 60)
        self.log(f"🔧 ЗАПУСК ПРОЦЕССА OPENVPN (поток {threading.current_thread().name})")
        self.log("-" * 60)
        
        if not os.path.exists(self.temp_ovpn_path):
            self.log(f"❌ ВРЕМЕННЫЙ ФАЙЛ НЕ СУЩЕСТВУЕТ: {self.temp_ovpn_path}")
            return

        cmd = f'echo -e "{login}\\n{password}" | openvpn --config {self.temp_ovpn_path} --auth-user-pass /dev/stdin --verb 3'
        self.log(f"💻 КОМАНДА: {cmd[:100]}...")
        
        log_file = f"/tmp/openvpn_{int(time.time())}.log"
        self.openvpn_log_file = log_file
        self.log(f"📝 ЛОГ-ФАЙЛ OPENVPN: {log_file}")
        
        try:
            self.log("🚀 ЗАПУСК ПРОЦЕССА...")
            self.openvpn_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )
            
            pid = self.openvpn_process.pid
            self.log(f"📊 PID ПРОЦЕССА: {pid}")
            
            time.sleep(1)
            if self.openvpn_process.poll() is None:
                self.log(f"✅ ПРОЦЕСС ЗАПУЩЕН И РАБОТАЕТ (PID: {pid})")
            else:
                return_code = self.openvpn_process.poll()
                self.log(f"❌ ПРОЦЕСС ЗАВЕРШИЛСЯ С КОДОМ: {return_code}")
                stdout, stderr = self.openvpn_process.communicate(timeout=1)
                self.log(f"📋 ВЫВОД ПРОЦЕССА:\n{stdout}")
                return

            time.sleep(2)
            if os.path.exists(self.temp_ovpn_path):
                try:
                    os.remove(self.temp_ovpn_path)
                    self.log(f"🗑️ ВРЕМЕННЫЙ КОНФИГ УДАЛЁН")
                except Exception as e:
                    self.log(f"⚠️ НЕ УДАЛОСЬ УДАЛИТЬ ВРЕМЕННЫЙ ФАЙЛ: {e}")

            with open(log_file, 'w') as log_f:
                log_f.write(f"=== OpenVPN запущен {time.ctime()} ===\n")
                log_f.write(f"Команда: {cmd}\n")
                log_f.write(f"PID: {pid}\n\n")

            connected = False
            start_time = time.time()
            line_count = 0
            
            self.log("⏳ ОЖИДАНИЕ ВЫВОДА OPENVPN...")
            
            for line in self.openvpn_process.stdout:
                line = line.strip()
                line_count += 1
                
                with open(log_file, 'a') as log_f:
                    log_f.write(f"{line}\n")
                
                if line_count % 10 == 0:
                    self.log(f"📋 [{line_count}] {line[:80]}...")
                
                if "Initialization Sequence Completed" in line:
                    self.log("🎉 ПОЛУЧЕНО СООБЩЕНИЕ ОБ УСПЕШНОМ ПОДКЛЮЧЕНИИ!")
                    self.log(f"📋 [{line_count}] {line}")
                    
                    time.sleep(3)
                    
                    self.log("🔍 ПРОВЕРКА IP ПОСЛЕ ПОДКЛЮЧЕНИЯ...")
                    current_ip = self.get_public_ip()
                    
                    self.log(f"📊 ТЕКУЩИЙ IP: {current_ip}, ОЖИДАЕМЫЙ IP: {self.expected_ip}")
                    
                    if current_ip == self.expected_ip:
                        self.is_connected = True
                        self.current_protocol = 'openvpn'
                        connected = True
                        self.failed_attempts = 0
                        self.log(f"✅ УСПЕШНО ПОДКЛЮЧЕНО К {server_name}")
                        self.log(f"🌐 IP: {current_ip}")
                        
                        with open(log_file, 'a') as log_f:
                            log_f.write(f"\n=== УСПЕШНОЕ ПОДКЛЮЧЕНИЕ {time.ctime()} ===\n")
                            log_f.write(f"IP: {current_ip}\n")
                    else:
                        self.log(f"⚠️ IP НЕ СОВПАДАЕТ! Текущий: {current_ip}, Ожидаемый: {self.expected_ip}")
                        self.failed_attempts += 1
                        self.check_network_interfaces()
                        self.disconnect_openvpn()
                    break

                elif "AUTH_FAILED" in line:
                    self.log("❌ ОШИБКА АУТЕНТИФИКАЦИИ")
                    self.log(f"📋 {line}")
                    self.failed_attempts += 1
                    with open(log_file, 'a') as log_f:
                        log_f.write(f"\n❌ ОШИБКА АУТЕНТИФИКАЦИИ: {line}\n")
                    break

                elif "ERROR" in line and "tls" not in line.lower():
                    self.log(f"⚠️ ОШИБКА: {line[:80]}")
                    
                elif "ROUTE" in line and "gateway" in line.lower():
                    self.log(f"🛣️ МАРШРУТ: {line}")

                elapsed = time.time() - start_time
                if elapsed > 30:
                    self.log(f"⏰ ТАЙМАУТ ПОДКЛЮЧЕНИЯ ({elapsed:.1f} сек)")
                    self.failed_attempts += 1
                    with open(log_file, 'a') as log_f:
                        log_f.write(f"\n⏰ ТАЙМАУТ ПОДКЛЮЧЕНИЯ {elapsed:.1f} сек\n")
                    break

            if not connected:
                self.log("❌ НЕ УДАЛОСЬ ПОДКЛЮЧИТЬСЯ")
                try:
                    with open(log_file, 'r') as log_f:
                        lines = log_f.readlines()
                        last_lines = lines[-20:] if len(lines) > 20 else lines
                        self.log("📋 ПОСЛЕДНИЕ СТРОКИ ЛОГА OPENVPN:")
                        for l in last_lines:
                            self.log(f"   {l.strip()}")
                except:
                    pass
                
                if self.failed_attempts >= 3:
                    self.log(f"⚠️ УЖЕ {self.failed_attempts} НЕУДАЧНЫХ ПОПЫТОК")

                if self.openvpn_process:
                    self.log("🛑 ЗАВЕРШЕНИЕ ПРОЦЕССА OPENVPN...")
                    try:
                        os.killpg(os.getpgid(self.openvpn_process.pid), signal.SIGTERM)
                    except:
                        self.openvpn_process.terminate()

        except Exception as e:
            self.log(f"❌ КРИТИЧЕСКАЯ ОШИБКА В ПОТОКЕ OPENVPN: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.failed_attempts += 1

    def disconnect_openvpn(self):
        """Отключение OpenVPN (без изменений)"""
        self.log("🔌 НАЧАЛО ОТКЛЮЧЕНИЯ OPENVPN")
        
        if self.openvpn_process:
            pid = self.openvpn_process.pid
            self.log(f"📊 ПРОЦЕСС OPENVPN НАЙДЕН (PID: {pid})")
            
            try:
                self.log(f"🛑 ОТПРАВКА SIGTERM ПРОЦЕССУ {pid}...")
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    self.log(f"   SIGTERM отправлен группе процессов")
                except:
                    self.openvpn_process.terminate()
                    self.log(f"   terminate() выполнен")
                
                self.log("⏳ ОЖИДАНИЕ ЗАВЕРШЕНИЯ ПРОЦЕССА...")
                self.openvpn_process.wait(timeout=5)
                self.log(f"✅ ПРОЦЕСС {pid} ЗАВЕРШЕН")
                
            except subprocess.TimeoutExpired:
                self.log(f"⚠️ ТАЙМАУТ ОЖИДАНИЯ, ПРИНУДИТЕЛЬНОЕ ЗАВЕРШЕНИЕ...")
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except:
                    self.openvpn_process.kill()
                self.log(f"💥 ПРОЦЕСС {pid} УБИТ")
            except Exception as e:
                self.log(f"⚠️ ОШИБКА ПРИ ЗАВЕРШЕНИИ: {e}")
        else:
            self.log("ℹ️ ПРОЦЕСС OPENVPN НЕ НАЙДЕН (openvpn_process = None)")

        self.kill_all_openvpn()

        if self.temp_ovpn_path and os.path.exists(self.temp_ovpn_path):
            try:
                os.remove(self.temp_ovpn_path)
                self.log(f"🗑️ ВРЕМЕННЫЙ КОНФИГ УДАЛЁН: {self.temp_ovpn_path}")
            except Exception as e:
                self.log(f"⚠️ ОШИБКА УДАЛЕНИЯ КОНФИГА: {e}")

        if self.openvpn_log_file and os.path.exists(self.openvpn_log_file):
            try:
                with open(self.openvpn_log_file, 'a') as log_f:
                    log_f.write(f"\n=== ОТКЛЮЧЕНИЕ {time.ctime()} ===\n")
                self.log(f"📝 ЛОГ-ФАЙЛ СОХРАНЁН: {self.openvpn_log_file}")
            except:
                pass

        if self.current_protocol == 'openvpn':
            self.is_connected = False
            self.current_protocol = None

        self.openvpn_process = None
        self.temp_ovpn_path = None
        
        self.log("✅ OPENVPN ПОЛНОСТЬЮ ОТКЛЮЧЁН")
        
        time.sleep(2)
        final_ip = self.get_public_ip()
        self.log(f"📡 IP ПОСЛЕ ОТКЛЮЧЕНИЯ: {final_ip}")

    def kill_all_openvpn(self):
        """Принудительное завершение всех процессов OpenVPN"""
        self.log("🔍 ПОИСК ВСЕХ ПРОЦЕССОВ OPENVPN...")
        try:
            killed = 0
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    is_openvpn = False
                    if proc.info['name'] and 'openvpn' in proc.info['name'].lower():
                        is_openvpn = True
                        self.log(f"   Найден по имени: {proc.info['name']} (PID: {proc.info['pid']})")
                    elif proc.info['cmdline']:
                        cmdline = ' '.join(proc.info['cmdline']).lower()
                        if 'openvpn' in cmdline:
                            is_openvpn = True
                            self.log(f"   Найден по cmdline: {cmdline[:50]}... (PID: {proc.info['pid']})")
                    
                    if is_openvpn:
                        proc.kill()
                        killed += 1
                        self.log(f"   ✅ Убит PID: {proc.info['pid']}")
                        
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied:
                    self.log(f"   ⚠️ Нет прав на убийство PID {proc.info['pid']}")
                except Exception as e:
                    self.log(f"   ⚠️ Ошибка при убийстве PID {proc.info['pid']}: {e}")
            
            if killed > 0:
                self.log(f"🛑 ВСЕГО УБИТО ПРОЦЕССОВ OPENVPN: {killed}")
            else:
                self.log("ℹ️ ПРОЦЕССОВ OPENVPN НЕ НАЙДЕНО")
                
        except Exception as e:
            self.log(f"⚠️ КРИТИЧЕСКАЯ ОШИБКА ПРИ ПОИСКЕ ПРОЦЕССОВ: {e}")

    # ------------------ Улучшенные V2Ray методы (на основе скриптов) ------------------
    def _ensure_v2ray_user(self):
        """Создание пользователя и группы для V2Ray (как в скриптах)"""
        try:
            # Создаём группу, если нет
            try:
                grp.getgrgid(self.V2RAY_GID)
                self.log(f"✅ Группа с GID {self.V2RAY_GID} уже существует")
            except KeyError:
                subprocess.run(['groupadd', '-g', str(self.V2RAY_GID), self.V2RAY_USER], check=True)
                self.log(f"✅ Создана группа {self.V2RAY_USER} с GID {self.V2RAY_GID}")

            # Создаём пользователя, если нет
            try:
                pwd.getpwnam(self.V2RAY_USER)
                self.log(f"✅ Пользователь {self.V2RAY_USER} уже существует")
            except KeyError:
                # В скриптах используется UID 0, но это небезопасно. Оставим UID = GID как в оригинале.
                # Для совместимости со скриптами можно создать пользователя с UID 0, но это плохая практика.
                # Оставляем как было: UID = GID.
                subprocess.run([
                    'useradd', '-r', '-s', '/bin/false',
                    '-g', str(self.V2RAY_GID),
                    '-u', str(self.V2RAY_GID),
                    self.V2RAY_USER
                ], check=True)
                self.log(f"✅ Создан пользователь {self.V2RAY_USER} с UID {self.V2RAY_GID}")

            # Увеличиваем лимит открытых файлов (как в скриптах)
            try:
                subprocess.run('ulimit -SHn 1000000', shell=True, executable='/bin/bash')
                result = subprocess.run('ulimit -n', shell=True, capture_output=True, text=True, executable='/bin/bash')
                self.log(f"Лимит открытых файлов: {result.stdout.strip()}")
            except Exception as e:
                self.log(f"⚠️ Ошибка установки лимита: {e}")

            return True
        except Exception as e:
            self.log(f"❌ Ошибка создания пользователя V2Ray: {e}")
            return False

    def _setup_v2ray_rules(self, proxy_ip):
        """Настройка правил iptables для TProxy (как в скриптах)"""
        try:
            self.log(f"Настройка iptables правил для V2Ray (прокси IP: {proxy_ip})...")
        
        # Сброс предыдущих правил
            subprocess.run(['ip', 'rule', 'del', 'fwmark', '1', 'table', '100'], stderr=subprocess.DEVNULL)
            subprocess.run(['ip', 'route', 'del', 'local', '0.0.0.0/0', 'dev', 'lo', 'table', '100'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-F', 'XRAY'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-F', 'XRAY_MASK'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-X', 'XRAY'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-X', 'XRAY_MASK'], stderr=subprocess.DEVNULL)

            # Создаём новую таблицу маршрутизации
            subprocess.run(['ip', 'rule', 'add', 'fwmark', '1', 'table', '100'], stderr=subprocess.DEVNULL)
            subprocess.run(['ip', 'route', 'add', 'local', '0.0.0.0/0', 'dev', 'lo', 'table', '100'], stderr=subprocess.DEVNULL)

        # Создаём цепочки (игнорируем ошибки, если уже существуют)
            subprocess.run(['iptables', '-t', 'mangle', '-N', 'XRAY'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-N', 'XRAY_MASK'], stderr=subprocess.DEVNULL)

        # Правила для XRAY (PREROUTING)
            self.log("Добавление правил в цепочку XRAY (PREROUTING)")
            for net in ['0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16',
                        '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4', '240.0.0.0/4']:
                subprocess.run(['iptables', '-t', 'mangle', '-A', 'XRAY', '-d', net, '-j', 'RETURN'], stderr=subprocess.DEVNULL)
    
            subprocess.run(['iptables', '-t', 'mangle', '-A', 'XRAY', '-d', proxy_ip, '-j', 'RETURN'], stderr=subprocess.DEVNULL)
    
            subprocess.run([
                'iptables', '-t', 'mangle', '-A', 'XRAY', '-p', 'tcp',
                '-j', 'TPROXY', '--on-port', str(self.TPROXY_PORT), '--tproxy-mark', '1'
            ], stderr=subprocess.DEVNULL)
            
            subprocess.run([
                'iptables', '-t', 'mangle', '-A', 'XRAY', '-p', 'udp',
                '-j', 'TPROXY', '--on-port', str(self.TPROXY_PORT), '--tproxy-mark', '1'
            ], stderr=subprocess.DEVNULL)
    
            subprocess.run(['iptables', '-t', 'mangle', '-A', 'PREROUTING', '-j', 'XRAY'], stderr=subprocess.DEVNULL)
    
            # Правила для XRAY_MASK (OUTPUT)
            self.log("Добавление правил в цепочку XRAY_MASK (OUTPUT)")
            subprocess.run([
                'iptables', '-t', 'mangle', '-A', 'XRAY_MASK',
                '-m', 'owner', '--gid-owner', str(self.V2RAY_GID), '-j', 'RETURN'
            ], stderr=subprocess.DEVNULL)
    
            for net in ['0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16',
                        '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4', '240.0.0.0/4']:
                subprocess.run(['iptables', '-t', 'mangle', '-A', 'XRAY_MASK', '-d', net, '-j', 'RETURN'], stderr=subprocess.DEVNULL)
    
            subprocess.run(['iptables', '-t', 'mangle', '-A', 'XRAY_MASK', '-d', proxy_ip, '-j', 'RETURN'], stderr=subprocess.DEVNULL)
            
            subprocess.run(['iptables', '-t', 'mangle', '-A', 'XRAY_MASK', '-j', 'MARK', '--set-mark', '1'], stderr=subprocess.DEVNULL)
    
            subprocess.run(['iptables', '-t', 'mangle', '-A', 'OUTPUT', '-p', 'tcp', '-j', 'XRAY_MASK'], stderr=subprocess.DEVNULL)
            
            subprocess.run(['iptables', '-t', 'mangle', '-A', 'OUTPUT', '-p', 'udp', '-j', 'XRAY_MASK'], stderr=subprocess.DEVNULL)
    
            # Проверка правил (опционально)
            self.log("Текущие правила iptables (цепочка XRAY):")
            result = subprocess.run(['iptables', '-t', 'mangle', '-L', 'XRAY', '-n', '-v'],
                                capture_output=True, text=True)
            for line in result.stdout.split('\n')[:15]:
                if line.strip():
                    self.log(f"  {line}")
    
            self.v2ray_rules_cleanup_needed = True
            self.log("✅ Правила iptables для V2Ray настроены")
            return True
    
        except Exception as e:
            self.log(f"❌ Ошибка настройки iptables: {e}")
            return False

    def _cleanup_v2ray_rules(self):
        """Очистка правил iptables (как в скриптах)"""
        if not self.v2ray_rules_cleanup_needed:
            return

        self.log("Очистка правил iptables...")
        try:
            subprocess.run(['ip', 'rule', 'del', 'fwmark', '1', 'table', '100'], stderr=subprocess.DEVNULL)
            subprocess.run(['ip', 'route', 'del', 'local', '0.0.0.0/0', 'dev', 'lo', 'table', '100'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-D', 'PREROUTING', '-j', 'XRAY'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-F', 'XRAY'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-X', 'XRAY'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-F', 'XRAY_MASK'], stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'mangle', '-X', 'XRAY_MASK'], stderr=subprocess.DEVNULL)

            self.v2ray_rules_cleanup_needed = False
            self.log("✅ Правила iptables очищены")
        except Exception as e:
            self.log(f"⚠️ Ошибка при очистке iptables: {e}")

    def _get_v2ray_config(self, vpn_type, login, password):
        """
        Получение конфига V2Ray через API.
        Пробуем прямой IP с Host header, затем домен.
        """
        self.log(f"Запрос V2Ray конфига для {vpn_type.upper()}, пользователь {login}...")
        
        # Определяем endpoint и IP в зависимости от типа
        if vpn_type == 'ru':
            server_ip = SERVER_IP_RU
            endpoint = "/api/app/get-v2ray-ru"
        else:  # 'world' или 'nl'
            server_ip = SERVER_IP_NL
            endpoint = "/api/app/get-v2ray-nl"
        
        # Пробуем прямой IP
        url = f"https://95.163.232.136{endpoint}"
        self.log(f"Попытка 1: прямой IP {url}")
        
        try:
            response = requests.post(
                url,
                json={"login": login, "password": password},
                timeout=15,
                verify=False,
                headers={'Host': 'xn--80adkrr5a.xn--p1ai'}  # Важно для SNI
            )
            self.log(f"Код ответа: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.log("✅ Конфиг получен через прямой IP")
                    return json.loads(data["v2ray"])
                else:
                    self.log(f"⚠️ Ошибка API через прямой IP: {data.get('error')}")
            else:
                self.log(f"⚠️ HTTP ошибка через прямой IP: {response.status_code}")
        except requests.exceptions.RequestException as e:
            self.log(f"⚠️ Ошибка запроса через прямой IP: {e}")

        # Пробуем через домен
        url = f"{API_BASE_URL}{endpoint}"
        self.log(f"Попытка 2: домен {url}")
        try:
            response = requests.post(
                url,
                json={"login": login, "password": password},
                timeout=15,
                verify=False
            )
            self.log(f"Код ответа: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.log("✅ Конфиг получен через домен")
                    return json.loads(data["v2ray"])
                else:
                    self.log(f"❌ Ошибка API через домен: {data.get('error')}")
            else:
                self.log(f"❌ HTTP ошибка через домен: {response.status_code}")
        except requests.exceptions.RequestException as e:
            self.log(f"❌ Ошибка запроса через домен: {e}")

        self.log("❌ Не удалось получить V2Ray конфиг ни одним способом")
        return None

    def _run_v2ray_process(self):
        """Запуск V2Ray процесса (как в скриптах)"""
        try:
            self.log("Запуск V2Ray процесса...")
            
            if not os.path.exists(self.v2ray_temp_config):
                self.log(f"❌ Конфиг не найден: {self.v2ray_temp_config}")
                return False

            # Проверяем наличие v2ray
            result = subprocess.run(['which', self.V2RAY_BIN], capture_output=True, text=True)
            if result.returncode != 0:
                self.log(f"❌ V2Ray не найден. Установите: sudo apt install v2ray")
                return False
            v2ray_path = result.stdout.strip()
            self.log(f"✅ V2Ray найден: {v2ray_path}")

            # Показываем версию
            try:
                version_result = subprocess.run([v2ray_path, 'version'], capture_output=True, text=True)
                if version_result.returncode == 0:
                    self.log(f"Версия: {version_result.stdout.strip()}")
            except:
                pass

            # Проверяем, не занят ли порт
            ss_result = subprocess.run(['ss', '-tuln'], capture_output=True, text=True)
            if f":{self.TPROXY_PORT}" in ss_result.stdout:
                self.log(f"⚠️ Порт {self.TPROXY_PORT} уже занят")

            # Команда запуска
            cmd = ['sudo', '-u', self.V2RAY_USER, v2ray_path, 'run', '-c', self.v2ray_temp_config]
            self.log(f"Команда: {' '.join(cmd)}")

            # Запускаем процесс (без setpgid, чтобы избежать проблем с правами)
            self.v2ray_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.v2ray_pid = self.v2ray_process.pid
            self.log(f"✅ V2Ray запущен, PID: {self.v2ray_pid}")

            # Сохраняем PID в файл
            try:
                with open(self.v2ray_pid_file, 'w') as f:
                    f.write(str(self.v2ray_pid))
            except:
                pass

            # Ждём инициализации
            time.sleep(3)

            # Проверяем, жив ли процесс
            if self.v2ray_process.poll() is None:
                self.log("✅ Процесс работает")
                
                # Показываем информацию о процессе
                try:
                    ps_result = subprocess.run(['ps', '-fp', str(self.v2ray_pid)], capture_output=True, text=True)
                    for line in ps_result.stdout.split('\n'):
                        if line.strip():
                            self.log(line)
                except:
                    pass

                # Показываем открытые порты
                try:
                    ss_result = subprocess.run(['ss', '-tulpn'], capture_output=True, text=True)
                    for line in ss_result.stdout.split('\n'):
                        if str(self.TPROXY_PORT) in line or 'v2ray' in line.lower():
                            self.log(f"  📡 {line}")
                except:
                    pass

                return True
            else:
                stdout, stderr = self.v2ray_process.communicate(timeout=1)
                self.log(f"❌ Процесс завершился с кодом {self.v2ray_process.returncode}")
                self.log(f"Вывод: {stdout}")
                return False

        except Exception as e:
            self.log(f"❌ Ошибка запуска V2Ray: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False

    def connect_v2ray(self, vpn_type, login, password):
        """
        Подключение через V2Ray (улучшенная версия на основе скриптов)
        Поддерживает оба типа: ru и world/nl
        """
        self.log("=" * 60)
        self.log(f"🔌 НАЧАЛО ПОДКЛЮЧЕНИЯ V2RAY ДЛЯ {vpn_type.upper()}")
        self.log("=" * 60)
        
        if not self.is_admin():
            self.log("❌ НЕТ ПРАВ ROOT")
            return False

        if not self.is_v2ray_installed():
            self.log("❌ V2RAY НЕ УСТАНОВЛЕН")
            return False

        self._check_and_fix_system_for_v2ray()
        
        # Устанавливаем ожидаемый IP
        if vpn_type == 'ru':
            proxy_ip = SERVER_IP_RU
            server_name = "Россия (V2Ray)"
        else:
            proxy_ip = SERVER_IP_NL
            server_name = "Нидерланды (V2Ray)"

        self.expected_ip = proxy_ip
        self.current_server = server_name
        self.current_vpn_type = vpn_type

        self.log(f"🌍 СЕРВЕР: {self.current_server}")
        self.log(f"🎯 ОЖИДАЕМЫЙ IP: {self.expected_ip}")

        # 1. Создаём пользователя и настраиваем систему
        if not self._ensure_v2ray_user():
            return False

        # 2. Получаем конфиг
        config = self._get_v2ray_config(vpn_type, login, password)
        if not config:
            self.log("❌ Не удалось получить V2Ray конфиг")
            return False

        # 3. Сохраняем временный конфиг
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(config, f, indent=2)
                self.v2ray_temp_config = f.name
            self.log(f"📁 Временный конфиг: {self.v2ray_temp_config}")
            
            # Проверяем валидность JSON
            with open(self.v2ray_temp_config, 'r') as f:
                json.load(f)
            self.log("✅ Проверка JSON пройдена")
            
            # Даём права на чтение всем
            os.chmod(self.v2ray_temp_config, 0o644)
        except Exception as e:
            self.log(f"❌ Ошибка сохранения конфига: {e}")
            return False

        # 4. Настраиваем правила iptables
        if not self._setup_v2ray_rules(proxy_ip):
            self.log("❌ Не удалось настроить iptables")
            self._cleanup_v2ray_temp_config()
            return False

        # 5. Запускаем V2Ray
        if not self._run_v2ray_process():
            self.log("❌ Не удалось запустить V2Ray")
            self._cleanup_v2ray_rules()
            self._cleanup_v2ray_temp_config()
            return False

        # 6. Проверяем IP несколько раз
        self.log("Ожидание стабилизации соединения (5 сек)...")
        time.sleep(5)

        max_attempts = 6
        for attempt in range(max_attempts):
            self.log(f"🔄 Проверка подключения (попытка {attempt + 1}/{max_attempts})...")
            
            # Проверяем, жив ли процесс
            if self.v2ray_process and self.v2ray_process.poll() is not None:
                self.log("❌ Процесс V2Ray неожиданно завершился!")
                self.disconnect_v2ray()
                return False

            current_ip = self.get_public_ip()
            
            if current_ip == self.expected_ip:
                self.is_connected = True
                self.current_protocol = 'v2ray'
                self.current_login = login
                self.current_password = password
                self.failed_attempts = 0
                self.log(f"✅ УСПЕШНО ПОДКЛЮЧЕНО К {server_name}")
                self.log(f"🌐 IP: {current_ip}")
                self.log(f"📝 Лог V2Ray: {self.v2ray_log_file}")
                return True
            
            if attempt < max_attempts - 1:
                self.log(f"⏳ Ждём 3 секунды перед следующей проверкой...")
                time.sleep(3)

        self.log(f"❌ IP не изменился после {max_attempts} попыток")
        self.disconnect_v2ray()
        return False

    def _cleanup_v2ray_temp_config(self):
        """Удаление временного конфига V2Ray"""
        if self.v2ray_temp_config and os.path.exists(self.v2ray_temp_config):
            try:
                os.unlink(self.v2ray_temp_config)
                self.log(f"🗑️ Временный конфиг V2Ray удалён")
                self.v2ray_temp_config = None
            except Exception as e:
                self.log(f"⚠️ Ошибка удаления конфига V2Ray: {e}")

    def disconnect_v2ray(self):
        """Отключение V2Ray и очистка правил (как в скриптах)"""
        self.log("🔌 ОТКЛЮЧЕНИЕ V2RAY...")
        
        # Остановка процесса
        if self.v2ray_process:
            try:
                self.v2ray_process.terminate()
                try:
                    self.v2ray_process.wait(timeout=5)
                    self.log("✅ Процесс V2Ray остановлен")
                except subprocess.TimeoutExpired:
                    self.log("⚠️ Таймаут ожидания, принудительное завершение...")
                    self.v2ray_process.kill()
                    self.v2ray_process.wait(timeout=2)
                    self.log("💥 Процесс V2Ray принудительно убит")
            except Exception as e:
                self.log(f"⚠️ Ошибка при остановке процесса: {e}")
            self.v2ray_process = None
            self.v2ray_pid = None

        # Также убиваем все процессы v2ray от пользователя v2ray_tproxy
        try:
            result = subprocess.run(['pgrep', '-u', self.V2RAY_USER, 'v2ray'], capture_output=True, text=True)
            if result.returncode == 0:
                for pid in result.stdout.strip().split('\n'):
                    if pid:
                        self.log(f"Убиваем процесс v2ray (PID: {pid})")
                        os.kill(int(pid), signal.SIGKILL)
        except:
            pass

        # Удаляем PID файл
        try:
            if os.path.exists(self.v2ray_pid_file):
                os.unlink(self.v2ray_pid_file)
        except:
            pass

        # Очистка iptables
        self._cleanup_v2ray_rules()

        # Удаление временного конфига
        self._cleanup_v2ray_temp_config()

        if self.current_protocol == 'v2ray':
            self.is_connected = False
            self.current_protocol = None
            self.log("✅ V2Ray отключён")

    # ------------------ Основные методы ------------------
    def connect(self, vpn_type, login, password):
        if self.is_connected:
            self.log("⚠️ Уже подключено")
            return True
    
        self.current_login = login
        self.current_password = password
        self.current_vpn_type = vpn_type
    
        # Определяем платформу
        import platform
        system = platform.system().lower()
    
        if system == 'linux':
            # Пробуем V2Ray, затем OpenVPN
            self.log(f"🔄 ПРОБУЕМ V2RAY ДЛЯ {vpn_type.upper()}...")
            if self.connect_v2ray(vpn_type, login, password):
                return True
            self.log("⚠️ V2RAY НЕ УДАЛСЯ, ПРОБУЕМ OPENVPN...")
            time.sleep(2)
            return self.connect_openvpn(vpn_type, login, password)
    
        elif system == 'darwin':  # macOS
            self.log("🍏 macOS обнаружена, используем только OpenVPN")
            return self.connect_openvpn(vpn_type, login, password)
    
        else:
            self.log(f"❌ Неподдерживаемая платформа: {system}")
            return False

    def disconnect(self):
        """
        Отключение текущего подключения.
        Определяет текущий протокол и отключает только его.
        """
        if not self.is_connected:
            self.log("⚠️ Не подключено")
            return

        self.log("🔌 ОТКЛЮЧЕНИЕ ПО ЗАПРОСУ ПОЛЬЗОВАТЕЛЯ...")
        
        if self.current_protocol == 'v2ray':
            self.disconnect_v2ray()
        elif self.current_protocol == 'openvpn':
            self.disconnect_openvpn()
        else:
            self.log("⚠️ НЕИЗВЕСТНЫЙ ПРОТОКОЛ, ЧИСТИМ ВСЁ")
            self.disconnect_v2ray()
            self.disconnect_openvpn()
            
        self.is_connected = False
        self.current_protocol = None
        self.log("✅ VPN ПОЛНОСТЬЮ ОТКЛЮЧЁН")

    def cleanup_all(self):
        """Полная очистка при выходе"""
        self.log("🧹 ПОЛНАЯ ОЧИСТКА ПРИ ВЫХОДЕ...")
        if self.is_connected:
            self.disconnect()
        self.disconnect_v2ray()
        self.disconnect_openvpn()

# ------------------ Класс для флагов ------------------
class FlagImages:
    def __init__(self):
        # Флаг Нидерландов
        nl_flag = Image.new('RGB', (40, 25), color='white')
        draw = ImageDraw.Draw(nl_flag)
        draw.rectangle([0, 0, 40, 8], fill='#AE1C28')
        draw.rectangle([0, 8, 40, 17], fill='white')
        draw.rectangle([0, 17, 40, 25], fill='#21468B')
        self.nl = ctk.CTkImage(light_image=nl_flag, dark_image=nl_flag, size=(40, 25))

        # Флаг России
        ru_flag = Image.new('RGB', (40, 25), color='white')
        draw = ImageDraw.Draw(ru_flag)
        draw.rectangle([0, 0, 40, 8], fill='white')
        draw.rectangle([0, 8, 40, 17], fill='#0C47B7')
        draw.rectangle([0, 17, 40, 25], fill='#E4181C')
        self.ru = ctk.CTkImage(light_image=ru_flag, dark_image=ru_flag, size=(40, 25))

# ------------------ ГЛАВНОЕ ПРИЛОЖЕНИЕ ------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Kvanet VPN Client")
        self.geometry("500x700")
        self.minsize(500, 700)

        self.current_theme = "dark"
        self.current_user = None
        self.current_password = None
        self.is_authenticated = False
        self.is_connecting = False
        self.dot_counter = 0
        self.server_var = ctk.StringVar(value="world")

        self.flags = FlagImages()
        self.vpn = VPNManager()
        self.vpn.set_log_callback(self.log_to_console)

        self.setup_theme()
        self.build_ui()
        self.start_ip_checker()
        self.show_login_screen()
        self.load_saved_credentials()

    def setup_theme(self):
        if self.current_theme == "dark":
            self.bg_color = "#0A0A0F"
            self.frame_bg = "#1A1A2E"
            self.text_color = "#E0E0E0"
            self.accent_color = "#BB86FC"
            self.button_color = "#2D2D44"
            self.hover_color = "#3D3D5C"
            ctk.set_appearance_mode("dark")
        else:
            self.bg_color = "#F5F5F7"
            self.frame_bg = "#FFFFFF"
            self.text_color = "#000000"
            self.accent_color = "#7B1FA2"
            self.button_color = "#F0F0F5"
            self.hover_color = "#E0E0E5"
            ctk.set_appearance_mode("light")
        self.configure(fg_color=self.bg_color)

    def build_ui(self):
        # Экран входа
        self.login_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=15)
        
        ctk.CTkLabel(
            self.login_frame, text="Kvanet VPN",
            font=("Arial", 32, "bold"), text_color=self.accent_color
        ).pack(pady=(60, 40))

        self.login_entry = ctk.CTkEntry(
            self.login_frame, placeholder_text="Логин", width=300, height=50,
            fg_color=self.button_color, border_color=self.accent_color,
            text_color=self.text_color, placeholder_text_color="#888888", font=("Arial", 14)
        )
        self.login_entry.pack(pady=10)

        self.password_entry = ctk.CTkEntry(
            self.login_frame, placeholder_text="Пароль", show="•",
            width=300, height=50, fg_color=self.button_color,
            border_color=self.accent_color, text_color=self.text_color,
            placeholder_text_color="#888888", font=("Arial", 14)
        )
        self.password_entry.pack(pady=10)

        ctk.CTkButton(
            self.login_frame, text="Войти", command=self.login,
            width=300, height=50, fg_color=self.accent_color,
            hover_color="#9C4DFF" if self.current_theme == "dark" else "#7B1FA2",
            text_color="#FFFFFF", font=("Arial", 16, "bold")
        ).pack(pady=20)

        ctk.CTkButton(
            self.login_frame, text="Выход", command=self.exit_app,
            width=300, height=50, fg_color="#FF4444",
            hover_color="#CC0000", text_color="#FFFFFF", font=("Arial", 16, "bold")
        ).pack(pady=10)

        # Меню
        self.menu_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=10)
        for text, cmd in [("Основной", self.show_main_screen),
                          ("Настройки", self.show_settings),
                          ("Выйти", self.logout)]:
            ctk.CTkButton(
                self.menu_frame, text=text, command=cmd,
                fg_color=self.button_color, hover_color=self.hover_color,
                text_color=self.text_color, corner_radius=8, height=40, font=("Arial", 14)
            ).pack(side="left", padx=5, pady=5, expand=True)

        # Основной экран
        self.main_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=15)
        container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        container.pack(expand=True, fill="both")

        ctk.CTkFrame(container, fg_color="transparent", height=60).pack(fill="x")

        ctk.CTkLabel(
            container, text="Kvanet VPN",
            font=("Arial", 28, "bold"), text_color=self.accent_color
        ).pack(pady=(0, 60))

        # Переключатель сервера
        switch_frame = ctk.CTkFrame(container, fg_color="transparent")
        switch_frame.pack(pady=20)

        ctk.CTkLabel(switch_frame, text="", image=self.flags.nl).pack(side="left", padx=15)

        self.server_switch = ctk.CTkSwitch(
            switch_frame, text="", command=self.on_server_switch,
            width=70, height=35, switch_width=80, switch_height=35,
            button_color=self.accent_color,
            button_hover_color="#9C4DFF" if self.current_theme == "dark" else "#7B1FA2",
            progress_color=self.accent_color
        )
        self.server_switch.pack(side="left", padx=10)

        ctk.CTkLabel(switch_frame, text="", image=self.flags.ru).pack(side="left", padx=15)

        # Индикатор статуса
        status_frame = ctk.CTkFrame(container, fg_color="transparent")
        status_frame.pack(pady=30)

        self.status_indicator = ctk.CTkLabel(
            status_frame, text="●", font=("Arial", 28), text_color="#888888"
        )
        self.status_indicator.pack()

        self.status_text = ctk.CTkLabel(
            status_frame, text="Не подключено",
            font=("Arial", 16), text_color=self.text_color
        )
        self.status_text.pack(pady=10)

        self.protocol_label = ctk.CTkLabel(
            status_frame, text="",
            font=("Arial", 12), text_color="#AAAAAA"
        )
        self.protocol_label.pack()

        # Кнопка подключения
        self.connect_btn = ctk.CTkButton(
            container, text="ПОДКЛЮЧИТЬСЯ", command=self.toggle_vpn,
            width=280, height=70, font=("Arial", 20, "bold"),
            fg_color="#2E8B57", hover_color="#3CB371", text_color="#FFFFFF", corner_radius=15
        )
        self.connect_btn.pack(pady=30)

        ctk.CTkFrame(container, fg_color="transparent", height=40).pack(fill="x")

        # Экран настроек
        self.settings_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=15)
        settings_container = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        settings_container.pack(expand=True, fill="both", padx=20, pady=20)

        ctk.CTkLabel(
            settings_container, text="Настройки",
            font=("Arial", 24, "bold"), text_color=self.accent_color
        ).pack(pady=(20, 40))

        # Выбор темы
        theme_frame = ctk.CTkFrame(settings_container, fg_color="transparent")
        theme_frame.pack(pady=20)

        ctk.CTkLabel(
            theme_frame, text="ТЕМА", font=("Arial", 18, "bold"), text_color=self.text_color
        ).pack(pady=(0, 15))

        btn_frame = ctk.CTkFrame(theme_frame, fg_color="transparent")
        btn_frame.pack()

        self.dark_btn = ctk.CTkButton(
            btn_frame, text="Тёмная", width=120, height=45,
            fg_color=self.accent_color if self.current_theme == "dark" else self.button_color,
            hover_color=self.hover_color,
            text_color="#FFFFFF" if self.current_theme == "dark" else self.text_color,
            font=("Arial", 14), command=lambda: self.set_theme("dark")
        )
        self.dark_btn.pack(side="left", padx=10)

        self.light_btn = ctk.CTkButton(
            btn_frame, text="Светлая", width=120, height=45,
            fg_color=self.accent_color if self.current_theme == "light" else self.button_color,
            hover_color=self.hover_color,
            text_color="#000000" if self.current_theme == "light" else self.text_color,
            font=("Arial", 14), command=lambda: self.set_theme("light")
        )
        self.light_btn.pack(side="left", padx=10)

        # Кнопка перегенерации
        ctk.CTkButton(
            settings_container, text="Перегенерировать OpenVPN",
            command=self.regenerate_ovpn,
            width=200, height=50, fg_color=self.accent_color,
            hover_color="#9C4DFF" if self.current_theme == "dark" else "#7B1FA2",
            text_color="#FFFFFF", font=("Arial", 16, "bold"), corner_radius=10
        ).pack(pady=30)

        # Версия
        ctk.CTkLabel(
            settings_container, text="Kvanet VPN Client 2.4.0",
            font=("Arial", 12), text_color=self.text_color
        ).pack(side="bottom", pady=20)

    def on_server_switch(self):
        self.server_var.set("ru" if self.server_switch.get() else "world")

    def set_theme(self, theme):
        self.current_theme = theme
        self.setup_theme()
        self.update_theme_colors()

    def update_theme_colors(self):
        frames = [self.login_frame, self.menu_frame, self.main_frame, self.settings_frame]
        for frame in frames:
            if frame.winfo_exists():
                frame.configure(fg_color=self.frame_bg)

        for child in self.menu_frame.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(
                    fg_color=self.button_color,
                    hover_color=self.hover_color,
                    text_color=self.text_color
                )

        self.dark_btn.configure(
            fg_color=self.accent_color if self.current_theme == "dark" else self.button_color,
            text_color="#FFFFFF"
        )
        text_color = "#000000" if self.current_theme == "light" else self.text_color
        self.light_btn.configure(
            fg_color=self.accent_color if self.current_theme == "light" else self.button_color,
            text_color=text_color
        )

    def start_connecting_animation(self):
        if self.is_connecting:
            self.dot_counter = (self.dot_counter + 1) % 4
            self.connect_btn.configure(text=f"ПОДКЛЮЧЕНИЕ{'.' * self.dot_counter}")
            self.after(500, self.start_connecting_animation)

    def stop_connecting_animation(self):
        self.is_connecting = False
        self.dot_counter = 0

    def update_ui_state(self):
        if not self.current_user:
            return

        current_ip = self.vpn.get_public_ip()
        vpn_ips = [SERVER_IP_NL, SERVER_IP_RU]

        if current_ip in vpn_ips:
            if self.is_connecting:
                self.is_connecting = False
                self.stop_connecting_animation()
            
            self.connect_btn.configure(
                text="ОТКЛЮЧИТЬСЯ",
                fg_color="#FF4444",
                hover_color="#CC0000"
            )
            self.status_indicator.configure(text_color="#00FF00")
            self.status_text.configure(text="Подключено")
            
            if self.vpn.current_protocol:
                protocol_display = "V2Ray" if self.vpn.current_protocol == 'v2ray' else "OpenVPN"
                self.protocol_label.configure(text=f"Протокол: {protocol_display}")
                
        elif self.is_connecting:
            self.connect_btn.configure(fg_color="#FFA500", hover_color="#FF8C00")
            self.status_indicator.configure(text_color="#FFA500")
            self.status_text.configure(text="Подключение...")
            self.protocol_label.configure(text="")
        else:
            self.vpn.is_connected = False
            self.connect_btn.configure(
                text="ПОДКЛЮЧИТЬСЯ",
                fg_color="#2E8B57",
                hover_color="#3CB371"
            )
            self.status_indicator.configure(text_color="#888888")
            self.status_text.configure(text="Не подключено")
            self.protocol_label.configure(text="")

    def login(self):
        login = self.login_entry.get().strip()
        password = self.password_entry.get()
        
        if not login or not password:
            messagebox.showerror("Ошибка", "Введите логин и пароль")
            return

        self.log_to_console(f"🔐 Вход: {login}")

        try:
            r = requests.post(
                f"{API_BASE_URL}/api/app/login",
                json={"login": login, "password": password},
                verify=False,
                timeout=10
            )
            data = r.json()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка подключения: {e}")
            return

        if not data.get("success"):
            messagebox.showerror("Ошибка", "Неверный логин или пароль")
            return

        if not data["user"].get("subscription"):
            messagebox.showerror("Ошибка", "Подписка неактивна")
            return

        self.current_user = data["user"]
        self.current_password = password
        self.is_authenticated = True

        global current_user_global, current_password_global
        current_user_global = self.current_user
        current_password_global = password

        self.save_credentials(login, password)
        self.log_to_console(f"✅ Вход выполнен")
        self.show_main_interface()

    def toggle_vpn(self):
        if not self.current_user:
            messagebox.showerror("Ошибка", "Сначала выполните вход")
            return

        current_ip = self.vpn.get_public_ip()
        vpn_ips = [SERVER_IP_NL, SERVER_IP_RU]

        if current_ip in vpn_ips:
            self.log_to_console("🔌 Отключение по запросу пользователя")
            self.vpn.disconnect()
            self.stop_connecting_animation()
            self.update_ui_state()
        else:
            server_type = self.server_var.get()
            self.is_connecting = True
            self.start_connecting_animation()
            self.update_ui_state()

            def connect_thread():
                success = self.vpn.connect(server_type, self.current_user["login"], self.current_password)
                if not success:
                    self.is_connecting = False
                    self.stop_connecting_animation()
                self.update_ui_state()

            threading.Thread(target=connect_thread, daemon=True).start()

    def regenerate_ovpn(self):
        if not self.current_user:
            messagebox.showerror("Ошибка", "Сначала выполните вход")
            return

        if messagebox.askyesno("Подтверждение", "Перегенерировать OpenVPN конфиг?"):
            self.log_to_console("🔄 Перегенерация OpenVPN...")
            success = self.vpn.regenerate_ovpn_config(
                self.vpn.current_vpn_type or self.server_var.get(),
                self.current_user["login"],
                self.current_password
            )
            if success:
                messagebox.showinfo("Успех", "Конфиг перегенерирован")
            else:
                messagebox.showerror("Ошибка", "Не удалось перегенерировать")

    def check_vpn_status(self):
        if self.current_user:
            self.update_ui_state()
        self.after(2000, self.check_vpn_status)

    def start_ip_checker(self):
        self.check_vpn_status()

    def log_to_console(self, msg):
        print(msg)

    def show_login_screen(self):
        self.hide_all_frames()
        self.login_frame.pack(expand=True, fill="both", padx=40, pady=40)

    def show_main_interface(self):
        self.hide_all_frames()
        self.menu_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.main_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))
        
        if self.server_var.get() == "ru":
            self.server_switch.select()
        else:
            self.server_switch.deselect()

    def show_main_screen(self):
        self.hide_all_frames()
        self.menu_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.main_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))

    def show_settings(self):
        self.hide_all_frames()
        self.menu_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.settings_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))

    def hide_all_frames(self):
        for frame in [self.login_frame, self.menu_frame, self.main_frame, self.settings_frame]:
            frame.pack_forget()

    def logout(self):
        if self.vpn.is_connected:
            self.vpn.disconnect()
        self.current_user = None
        self.current_password = None
        self.is_authenticated = False
        self.is_connecting = False
        
        global current_user_global, current_password_global
        current_user_global = None
        current_password_global = None
        
        self.clear_saved_credentials()
        self.log_to_console("👋 Выход из аккаунта")
        self.show_login_screen()

    def exit_app(self):
        if self.vpn.is_connected:
            self.vpn.disconnect()
        self.destroy()
        sys.exit(0)

    def get_credentials_path(self):
        config_dir = Path.home() / ".config" / "kvanet"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "credentials.json"

    def save_credentials(self, login, password):
        try:
            path = self.get_credentials_path()
            with open(path, "w") as f:
                json.dump({"login": login, "password": password}, f)
            os.chmod(path, 0o600)
        except Exception as e:
            self.log_to_console(f"⚠️ Не удалось сохранить учётные данные: {e}")

    def load_saved_credentials(self):
        path = self.get_credentials_path()
        if not path.exists():
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.login_entry.insert(0, data.get("login", ""))
            self.password_entry.insert(0, data.get("password", ""))
        except Exception as e:
            print(f"⚠️ Не удалось загрузить учётные данные: {e}")

    def clear_saved_credentials(self):
        path = self.get_credentials_path()
        if path.exists():
            path.unlink()

# ------------------ Точка входа ------------------
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("❌ Требуются права root для работы VPN")
        print("Запустите с sudo или через ярлык из меню")
        sys.exit(1)

    app = App()
    app.mainloop()
