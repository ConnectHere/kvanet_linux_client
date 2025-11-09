import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk
import os
import time
import threading
import subprocess
import requests
import json
from tkinter import filedialog, messagebox, scrolledtext
import sys
import psutil
import tempfile

# Глобалки
current_user_global = None
current_password_global = None

# Устанавливаем тему и режим
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

API_BASE_URL = "https://xn--80adkrr5a.xn--p1ai"

class VPNManager:
    """Класс для управления VPN соединениями"""

    def __init__(self):
        self.process = None
        self.is_connected = False
        self.log_callback = None
        self.status_callback = None
        self.connection_timeout = 45
        self.auth_file_path = None
        self.current_user = None
        self.current_password = None
    
    def set_log_callback(self, callback):
        self.log_callback = callback

    def set_status_callback(self, callback):
        self.status_callback = callback

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def update_status(self, status, progress=None):
        if self.status_callback:
            self.status_callback(status, progress)

    def is_admin(self):
        try:
            return os.geteuid() == 0
        except AttributeError:
            # Windows не поддерживает os.geteuid()
            return False

    def is_openvpn_installed(self):
        try:
            result = subprocess.run(['which', 'openvpn'], capture_output=True, text=True)
            return result.returncode == 0
        except:
            return False

    def get_openvpn_path(self):
        try:
            result = subprocess.run(['which', 'openvpn'], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
            return '/usr/bin/openvpn'
        except:
            return '/usr/bin/openvpn'

    def install_openvpn(self):
        try:
            self.log("📥 Начинаем установку OpenVPN...")
            self.update_status("Установка OpenVPN...", 0.3)

            update_result = subprocess.run(
                ['sudo', 'pacman', '-Sy'],
                capture_output=True,
                text=True,
                timeout=300
            )
            if update_result.returncode != 0:
                self.log("❌ Ошибка обновления базы данных пакетов")
                return False

            self.update_status("Установка OpenVPN...", 0.6)

            install_result = subprocess.run(
                ['sudo', 'pacman', '-S', '--noconfirm', 'openvpn'],
                capture_output=True,
                text=True,
                timeout=300
            )

            if install_result.returncode == 0:
                self.log("✅ OpenVPN успешно установлен!")
                self.update_status("OpenVPN установлен", 1.0)
                time.sleep(2)
                return True
            else:
                self.log(f"❌ Ошибка установки OpenVPN: {install_result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.log("❌ Таймаут при установке OpenVPN")
            return False
        except Exception as e:
            self.log(f"❌ Ошибка при установке OpenVPN: {str(e)}")
            return False

    def run_as_admin(self):
        try:
            if os.geteuid() != 0:
                os.execvp('sudo', ['sudo', sys.executable] + sys.argv)
            return True
        except Exception as e:
            self.log(f"❌ Ошибка перезапуска с правами root: {str(e)}")
            return False

    def create_auth_file(self, username, password):
        """Создаёт временный файл с логином и паролем для OpenVPN"""
        auth_file = tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8')
        auth_file.write(f"{username}\n{password}\n")
        auth_file.close()
        self.auth_file_path = auth_file.name
        return self.auth_file_path

    def connect(self, ovpn_file_path):
        if not os.path.exists(ovpn_file_path):
            self.log(f"❌ Файл {ovpn_file_path} не найден")
            return False
        if not ovpn_file_path.endswith('.ovpn'):
            self.log("❌ Файл должен иметь расширение .ovpn")
            return False
        if not self.is_openvpn_installed():
            self.log("❌ OpenVPN не установлен")
            return False
        if not self.is_admin():
            self.log("❌ Требуются права root")
            return False
    
        username = self.current_user['login'] if self.current_user else (
            current_user_global['login'] if current_user_global else None
        )
        password = self.current_password if self.current_password else current_password_global
    
        if not username or not password:
            self.log("❌ Нет данных для авторизации")
            return False
    
        # Создаем временный auth-файл
        self.create_auth_file(username, password)
    
        # Запускаем подключение в отдельном потоке
        threading.Thread(
            target=self.run_connection,
            args=(ovpn_file_path, username, password)
        ).start()
    
        return True
    


    def run_connection(self, ovpn_file_path, username, password):
        global current_user_global, current_password_global
        try:
            if username is None or password is None:
                # Берем из глобальных переменных
                if current_user_global is None or current_password_global is None:
                    self.log("❌ Не указаны учетные данные")
                    return False
                username = current_user_global.get('login', '')
                password = current_password_global
            else:
                # Обновляем глобальные переменные
                current_user_global = {'login': username}
                current_password_global = password            
            self.log("🔍 Проверка файла конфигурации...")
            self.update_status("Проверка файла...", 0.2)
            time.sleep(1)
    
            log_dir = os.path.join(os.path.expanduser("~"), "KvanetVPN")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "openvpn.log")
    
            self.log("🚀 Запуск OpenVPN...")
            self.update_status("Запуск OpenVPN...", 0.4)
    
            login = current_user_global.get('login', '')
            password = current_password_global
            
            self.log(f"login: {login}; password:{password}")
            self.process = subprocess.Popen(
                f'echo -e "{login}\\n{password}" | sudo {self.get_openvpn_path()} --config {ovpn_file_path} --log {log_file} --verb 3 --auth-user-pass /dev/stdin',
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            connection_established = False
            start_time = time.time()
            timeout = 10  # таймаут подключения в секундах
            
            # --- Проверяем IP через несколько секунд после запуска ---
            def delayed_ip_check():
                try:
                    time.sleep(8)  # подождём 8 секунд (время на установку соединения)
                    if self.process and self.process.poll() is None:  # процесс жив
                        current_ip = self.get_public_ip()
                        if current_ip == "147.45.255.17":
                            self.log(f"✅ Подключено! IP: {current_ip}")
                            self.update_status("Подключено", 1.0)
                            self.is_connected = True
                        else:
                            self.log(f"⚠️ IP пока не совпадает (текущий: {current_ip})")
                except Exception as e:
                    self.log(f"⚠️ Ошибка проверки IP после запуска: {e}")

            threading.Thread(target=delayed_ip_check, daemon=True).start()

            # Читаем вывод в цикле
            while True:
                # Проверяем таймаут
                if time.time() - start_time > timeout and not connection_established:
                    self.log("❌ Таймаут подключения")
                    self.update_status("Таймаут подключения", 0.0)
                    self.process.terminate()
                    break
    
                # Проверяем статус процесса
                if self.process.poll() is not None:
                    self.log("❌ OpenVPN завершился неожиданно")
                    self.update_status("Ошибка подключения", 0.0)
                    break
    
                # Читаем строку (неблокирующее чтение)
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)  # небольшая пауза если нет вывода
                    continue
    
                cleaned_line = line.strip()
                self.log(cleaned_line)
    
#                if 'Initialization Sequence Completed' in cleaned_line:
#                    self.is_connected = True
#                    connection_established = True
#                    self.log("✅ Успешно подключено!")
#                    self.update_status("Подключено", 1.0)
#                    try:
#                        public_ip = self.get_public_ip()
#                        if public_ip:
#                            self.log(f"🌐 Ваш IP: {public_ip}")
#                        else:
#                            self.log("⚠️ Не удалось определить IP")
#                    except Exception as e:
#                        self.log(f"⚠️ Ошибка проверки IP: {e}")
#                    break




                


                if 'ERROR' in cleaned_line or 'AUTH_FAILED' in cleaned_line:
                    self.log(f"❌ Ошибка: {cleaned_line}")
                    self.update_status("Ошибка подключения", 0.0)
                    self.process.terminate()
                    #break
    
                # Обновляем прогресс если подключение устанавливается
                elif 'Waiting for' in cleaned_line or 'Reconnecting' in cleaned_line:
                    self.update_status("Установка соединения...", 0.6)
                elif 'TCP/UDP' in cleaned_line:
                    self.update_status("Настройка сети...", 0.8)
    
        except Exception as e:
            self.log(f"❌ Ошибка подключения: {str(e)}")
            self.is_connected = False
            self.update_status("Ошибка", 0.0)
        finally:
            # Убираем удаление auth_file_path так как мы не создаем файл
            pass
    
    def get_public_ip(self):
        try:
            services = ['https://api.ipify.org', 'https://ident.me', 'https://checkip.amazonaws.com']
            for service in services:
                try:
                    r = requests.get(service, timeout=10)
                    if r.status_code == 200:
                        return r.text.strip()
                except:
                    continue
            return None
        except:
            return None

    def disconnect(self):
        self.update_status("Отключение...", 0.5)
        self.log("🔌 Отключение VPN...")
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                    self.log("✅ Отключено")
                    self.update_status("Не подключено", 0.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.log("⚠️ Принудительное отключение")
                    self.update_status("Не подключено", 0.0)
            except Exception as e:
                self.log(f"❌ Ошибка при отключении: {str(e)}")
        self.is_connected = False
        self.process = None

    def get_status(self):
        return self.is_connected

    def kill_all_openvpn(self):
        try:
            killed = 0
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and 'openvpn' in proc.info['name'].lower():
                    try:
                        proc.kill()
                        killed += 1
                    except:
                        pass
            if killed > 0:
                self.log(f"🔧 Завершено процессов OpenVPN: {killed}")
            else:
                self.log("🔧 Процессы OpenVPN не найдены")
        except Exception as e:
            self.log(f"⚠️ Ошибка при завершении процессов: {e}")

# ------------------ Приложение ------------------

class App(ctk.CTk):
    width = 1000
    height = 700

    def __init__(self):
        super().__init__()
        self.title("Kvanet VPN Client")
        self.geometry(f"{self.width}x{self.height}")
        self.minsize(900, 650)
        self.resizable(True, True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.canvas = ctk.CTkCanvas(self, width=self.width, height=self.height, highlightthickness=0, bg="#141428")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.create_gradient()

        self.pixel_font = ctk.CTkFont(family="DejaVu Sans Mono", size=20, weight="bold")
        self.text_font = ctk.CTkFont(family="DejaVu Sans", size=14)
        self.small_font = ctk.CTkFont(family="DejaVu Sans", size=12)

        self.vpn_manager = VPNManager()
        self.vpn_manager.set_log_callback(self.add_log_message)
        self.vpn_manager.set_status_callback(self.update_status)

        self.current_ovpn_file = None
        self.current_user = None

        self.create_widgets()
        self.check_openvpn_installation()

    # ------------------ UI методы ------------------

    def create_widgets(self):
        # Поле для выбора OVPN файла
        self.file_entry = ctk.CTkEntry(self, width=400)
        self.file_entry.place(x=50, y=50)
        
        browse_button = ctk.CTkButton(self, text="Обзор", command=self.on_browse_button_clicked)
        browse_button.place(x=460, y=50)
    
        # Кнопка подключения
        self.connect_button = ctk.CTkButton(self, text="Подключиться", command=self.on_connect_button_clicked)
        self.connect_button.place(x=50, y=100)
    
        # Лог
        self.log_text = scrolledtext.ScrolledText(self, width=80, height=20)
        self.log_text.place(x=50, y=150)
    
        # Статус
        self.status_label = ctk.CTkLabel(self, text="Статус: Не подключено")
        self.status_label.place(x=50, y=500)
    
        # Прогресс бар
        self.progress_bar = ctk.CTkProgressBar(self, width=400)
        self.progress_bar.place(x=50, y=530)
    

    def create_gradient(self):
        width, height = self.width, self.height
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        start_color = (20, 20, 40)
        end_color = (100, 60, 150)
        for y in range(height):
            r = int(start_color[0] + (end_color[0]-start_color[0])*y/height)
            g = int(start_color[1] + (end_color[1]-start_color[1])*y/height)
            b = int(start_color[2] + (end_color[2]-start_color[2])*y/height)
            draw.line((0,y,width,y), fill=(r,g,b))
        self.gradient_image = ImageTk.PhotoImage(image)
        self.canvas.create_image(0,0,image=self.gradient_image, anchor="nw")
        self.canvas.bind("<Configure>", self.resize_gradient)

    def resize_gradient(self, event):
        width = event.width if event.width > 0 else self.width
        height = event.height if event.height > 0 else self.height
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        start_color = (20, 20, 40)
        end_color = (100, 60, 150)
        for y in range(height):
            r = int(start_color[0] + (end_color[0]-start_color[0])*y/height)
            g = int(start_color[1] + (end_color[1]-start_color[1])*y/height)
            b = int(start_color[2] + (end_color[2]-start_color[2])*y/height)
            draw.line((0,y,width,y), fill=(r,g,b))
        self.gradient_image = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0,0,image=self.gradient_image, anchor="nw")


    def create_widgets(self):
        """Создание всех элементов интерфейса"""
        # Фрейм для входа
        self.sign_in_frame = ctk.CTkFrame(self, corner_radius=15, fg_color="#2A2A3A")
        self.sign_in_frame.grid_columnconfigure(0, weight=1)

        self.sign_in_label = ctk.CTkLabel(self.sign_in_frame, text="Вход", font=self.pixel_font, text_color="#28A745")
        self.sign_in_label.grid(row=0, column=0, padx=30, pady=(15, 15))

        self.username_entry = ctk.CTkEntry(self.sign_in_frame, width=250, placeholder_text="Логин", font=self.text_font,
                                          fg_color="#3A3A50", border_color="#28A745", border_width=2)
        self.username_entry.grid(row=1, column=0, padx=30, pady=(15, 15))

        self.password_entry = ctk.CTkEntry(self.sign_in_frame, width=250, show="*", placeholder_text="Пароль", font=self.text_font,
                                          fg_color="#3A3A50", border_color="#28A745", border_width=2)
        self.password_entry.grid(row=2, column=0, padx=30, pady=(0, 15))

        # Метка для ошибок входа
        self.login_error_label = ctk.CTkLabel(self.sign_in_frame, text="", font=self.small_font, text_color="#FF4444")
        self.login_error_label.grid(row=3, column=0, padx=30, pady=(5, 5))

        self.sign_in_button = ctk.CTkButton(self.sign_in_frame, text="Войти", command=self.sign_in_event, width=250,
                                           fg_color="#28A745", hover_color="#218838", text_color="#1E1E2F")
        self.sign_in_button.grid(row=4, column=0, padx=30, pady=(15, 15))

        self.sign_in_label_info = ctk.CTkLabel(self.sign_in_frame, text="Нет аккаунта? Регистрируйтесь на нашем сайте",
                                             font=self.text_font, text_color="#FFFFFF")
        self.sign_in_label_info.grid(row=5, column=0, padx=30, pady=(15, 15))

        # Главный фрейм для VPN
        self.main_frame = ctk.CTkFrame(self, corner_radius=15, fg_color="#2A2A3A")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=1)

        # Заголовок
        self.main_label = ctk.CTkLabel(self.main_frame, text="Kvanet VPN Client", font=self.pixel_font, text_color="#28A745")
        self.main_label.grid(row=0, column=0, columnspan=2, pady=(20, 10), sticky="n")

        # Информация о пользователе
        self.user_info_label = ctk.CTkLabel(self.main_frame, text="", font=self.text_font, text_color="#FFFFFF")
        self.user_info_label.grid(row=1, column=0, columnspan=2, pady=(5, 10), sticky="n")

        # Фрейм прав root
        root_frame = ctk.CTkFrame(self.main_frame, fg_color="#8B0000" if not self.vpn_manager.is_admin() else "#2E8B57")
        root_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=5)

        root_text = "🛡️ Запущено с правами root" if self.vpn_manager.is_admin() else "⚠️ Требуются права root"
        root_label = ctk.CTkLabel(root_frame, text=root_text, font=ctk.CTkFont(weight="bold"))
        root_label.pack(padx=10, pady=10)

        if not self.vpn_manager.is_admin():
            root_button = ctk.CTkButton(
                root_frame,
                text="Перезапустить с правами root",
                command=self.restart_as_admin,
                fg_color="#DC143C",
                hover_color="#FF4500"
            )
            root_button.pack(padx=10, pady=(0, 10))

        # Фрейм выбора файла
        file_frame = ctk.CTkFrame(self.main_frame)
        file_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=5)

        ctk.CTkLabel(file_frame, text="Файл конфигурации (.ovpn):",
                    font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))

        file_selection_frame = ctk.CTkFrame(file_frame, fg_color="transparent")
        file_selection_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.file_entry = ctk.CTkEntry(file_selection_frame, placeholder_text="Выберите .ovpn файл...")
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.browse_button = ctk.CTkButton(
            file_selection_frame,
            text="Обзор",
            width=80,
            command=self.on_browse_button_clicked
        )
        self.browse_button.pack(side="right")

        # Фрейм установки OpenVPN
        self.install_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B")

        info_text = """OpenVPN не установлен. Для работы приложения необходимо установить OpenVPN."""

        info_label = ctk.CTkLabel(self.install_frame, text=info_text, justify="left")
        info_label.pack(padx=10, pady=10)

        install_button_frame = ctk.CTkFrame(self.install_frame, fg_color="transparent")
        install_button_frame.pack(padx=10, pady=(0, 10))

        self.install_button = ctk.CTkButton(
            install_button_frame,
            text="📥 Установить OpenVPN автоматически",
            command=self.install_openvpn,
            fg_color="#1E90FF",
            hover_color="#4169E1"
        )
        self.install_button.pack(side="left", padx=(0, 10))

        self.manual_install_button = ctk.CTkButton(
            install_button_frame,
            text="📖 Установить вручную",
            command=self.install_openvpn_manual,
            fg_color="#32CD32",
            hover_color="#228B22"
        )
        self.manual_install_button.pack(side="left")

        # Фрейм управления
        control_frame = ctk.CTkFrame(self.main_frame)
        control_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        control_buttons_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        control_buttons_frame.pack(fill="x", padx=10, pady=10)

        self.connect_button = ctk.CTkButton(
            control_buttons_frame,
            text="Подключиться",
            command=self.on_connect_button_clicked,
            fg_color="#2E8B57",
            hover_color="#3CB371",
            state="disabled"
        )
        self.connect_button.pack(side="left", padx=(0, 10))

        self.kill_all_button = ctk.CTkButton(
            control_buttons_frame,
            text="Отключиться",
            command=self.on_kill_all_clicked,
            fg_color="#DC143C",
            hover_color="#FF4500",
        )
        self.kill_all_button.pack(side="left", padx=(0, 10))

        self.clear_logs_button = ctk.CTkButton(
            control_buttons_frame,
            text="Очистить логи",
            command=self.on_clear_logs_button_clicked
        )
        self.clear_logs_button.pack(side="left")

        # Прогресс бар и статус
        status_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        status_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.status_label = ctk.CTkLabel(status_frame, text="Проверка OpenVPN...",
                                       font=ctk.CTkFont(weight="bold"))
        self.status_label.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(status_frame)
        self.progress_bar.pack(fill="x", pady=(5, 0))
        self.progress_bar.set(0)

        # Фрейм логов - ЗНАЧИТЕЛЬНО УВЕЛИЧЕН
        log_frame = ctk.CTkFrame(self.main_frame)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_rowconfigure(5, weight=1)  # Даем логам больше места

        log_header_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(log_header_frame, text="Логи подключения:",
                    font=ctk.CTkFont(weight="bold")).pack(side="left")

        # Кнопка проверки IP
        self.check_ip_button = ctk.CTkButton(
            log_header_frame,
            text="🌐 Проверить IP",
            command=self.check_current_ip,
            width=100,
            fg_color="#4169E1",
            hover_color="#6495ED"
        )
        self.check_ip_button.pack(side="right")
        # Рядом с кнопкой проверки IP в log_header_frame
        self.check_subscription_button = ctk.CTkButton(
            log_header_frame,
            text="🔄 Проверить подписку",
            command=self.check_subscription_status,
            width=120,
            fg_color="#FFA500",
            hover_color="#FF8C00"
        )
        self.check_subscription_button.pack(side="right", padx=(5, 0))
        # Текстовое поле для логов - УВЕЛИЧЕНО
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            bg="#1E1E1E",
            fg="#FFFFFF",
            insertbackground="#FFFFFF",
            font=("DejaVu Sans Mono", 10),
            height=20,  # Увеличил высоту
            width=100   # Увеличил ширину
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Кнопка выхода
        self.back_button = ctk.CTkButton(self.main_frame, text="Выход", command=self.back_event,
                                        fg_color="#FF4444", hover_color="#CC0000", corner_radius=10, width=120)
        self.back_button.grid(row=6, column=1, pady=10, padx=10, sticky="e")

        # Показываем страницу входа по умолчанию
        self.show_sign_in()



    def check_current_ip(self):
        """Проверка текущего IP адреса"""
        def check_ip_thread():
            self.add_log_message("🔍 Проверка текущего IP-адреса...")
            try:
                public_ip = self.vpn_manager.get_public_ip()
                if public_ip:
                    self.add_log_message(f"🌐 Текущий публичный IP: {public_ip}")
                else:
                    self.add_log_message("❌ Не удалось определить публичный IP")
            except Exception as e:
                self.add_log_message(f"❌ Ошибка при проверке IP: {str(e)}")

        thread = threading.Thread(target=check_ip_thread)
        thread.daemon = True
        thread.start()

    def sign_in_event(self):
        global current_user_global, current_password_global
        #"Вход через API с проверкой подписки"""
        login = self.username_entry.get().strip()
        password = self.password_entry.get()

        if not login or not password:
            self.login_error_label.configure(text="Логин и пароль обязательны")
            return
        else:
            self.login_error_label.configure(text="")

        self.sign_in_button.configure(state="disabled", text="Вход...")

        try:
            response = requests.post(f"{API_BASE_URL}/api/app/login",
                                json={'login': login, 'password': password})
            result = response.json()

            if result.get('success'):
                self.current_user = result['user']
                self.current_password = password

                # Сохраняем всё в глобалки
                current_user_global = result['user']
                current_password_global = password
                # Добавляем проверку подписки
                subscription_status = result['user'].get('subscription', False)
                self.current_user['subscription'] = subscription_status

                self.add_log_message("✅ Вход успешен!")
                self.add_log_message(f"📊 Статус подписки: {'Активна' if subscription_status else 'Неактивна'}")

                if not subscription_status:
                    self.add_log_message("❌ Подписка неактивна. Обратитесь к администратору.")

                self.login_error_label.configure(text="")
                self.show_main_frame()
            else:
                error_msg = result.get('error', 'Ошибка входа')
                self.login_error_label.configure(text=error_msg)
                self.add_log_message(f"❌ {error_msg}")

        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка подключения к серверу: {str(e)}"
            self.login_error_label.configure(text=error_msg)
            self.add_log_message(f"❌ {error_msg}")
        except Exception as e:
            error_msg = f"Неожиданная ошибка: {str(e)}"
            self.login_error_label.configure(text=error_msg)
            self.add_log_message(f"❌ {error_msg}")
        finally:
            self.sign_in_button.configure(state="normal", text="Войти")



    def install_openvpn(self):
        #"""Установка OpenVPN автоматически через pacman"""
        if not self.vpn_manager.is_admin():
            messagebox.showerror("Ошибка", "Для установки OpenVPN требуются права root")
            return

        self.install_button.configure(state="disabled", text="⏳ Установка...")

        def install_thread():
            success = self.vpn_manager.install_openvpn()
            if success:
                self.add_log_message("✅ Установка завершена успешно!")
                self.after(0, self.check_openvpn_installation)
            else:
                self.add_log_message("❌ Ошибка установки OpenVPN")
                self.after(0, lambda: self.install_button.configure(state="normal", text="📥 Установить OpenVPN автоматически"))

        thread = threading.Thread(target=install_thread)
        thread.daemon = True
        thread.start()

    def install_openvpn_manual(self):
        """Показывает инструкции по ручной установке"""
        instructions = """
        Для установки OpenVPN вручную выполните в терминале:

        1. Обновите систему:
        sudo pacman -Syu

        2. Установите OpenVPN:
            sudo pacman -S openvpn

        3. (Опционально) Установите сетевой менеджер:
            sudo pacman -S networkmanager-openvpn

        После установки перезапустите приложение.
        """
        messagebox.showinfo("Ручная установка OpenVPN", instructions)
        self.add_log_message("📖 Показаны инструкции по ручной установке")

    def check_openvpn_installation(self):
        """Проверяем установку OpenVPN"""
        def check_thread():
            self.add_log_message("🔍 Проверка установки OpenVPN...")
            time.sleep(1)

            if self.vpn_manager.is_openvpn_installed():
                openvpn_path = self.vpn_manager.get_openvpn_path()
                self.add_log_message(f"✅ OpenVPN найден: {openvpn_path}")

                # Скрываем фрейм установки
                self.install_frame.grid_forget()

                if self.vpn_manager.is_admin():
                    self.add_log_message("✅ Права root подтверждены")
                    self.update_status("Готов к работе", 0.0)
                else:
                    self.add_log_message("⚠️ Запустите приложение с правами root")
                    self.update_status("Требуются права root", 0.0)
            else:
                self.add_log_message("❌ OpenVPN не установлен")
                # Показываем фрейм установки
                self.install_frame.grid(row=7, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
                self.update_status("Требуется установка OpenVPN", 0.0)
                self.connect_button.configure(state="disabled")

        thread = threading.Thread(target=check_thread)
        thread.daemon = True
        thread.start()

    def on_kill_all_clicked(self):
        #"""Принудительное отключение всех VPN соединений"""
        def kill_thread():
            self.add_log_message("🛑 Принудительное отключение всех VPN соединений...")
            self.vpn_manager.kill_all_openvpn()
            self.vpn_manager.is_connected = False
            self.update_status("Не подключено", 0.0)

        thread = threading.Thread(target=kill_thread)
        thread.daemon = True
        thread.start()

    def on_clear_logs_button_clicked(self):
        """Очистка логов"""
        self.log_text.delete("1.0", "end")
        self.add_log_message("🧹 Логи очищены")


    def check_subscription_status(self):
        """Проверка статуса подписки у сервера"""
        if not self.current_user:
            self.add_log_message("❌ Нет данных пользователя для проверки подписки")
            return

        def check_thread():
            try:
                self.add_log_message("🔍 Проверка статуса подписки...")

                # Для проверки подписки нам нужен тот же endpoint что и для входа
                # но нам не нужно сохранять сессию, просто получаем актуальные данные
                response = requests.post(f"{API_BASE_URL}/api/app/login",
                                    json={
                                        'login': self.current_user['login'],
                                        'password': ''  # Пустой пароль не сработает
                                    },
                                    timeout=10)

                # Если запрос с пустым паролем не работает, попробуем другой подход
                # Давай просто получим обновленные данные пользователя через тот же endpoint
                # но с текущими credentials (если они сохранены)

                # Временно используем тот же логин/пароль что при входе
                # В реальном приложении нужно хранить токен или сессию
                self.add_log_message("⚠️ Для проверки подписки требуется повторная аутентификация")
                self.add_log_message("ℹ️ Функция проверки подписки требует доработки сервера")

                # Временное решение: просто показываем текущий статус
                current_status = self.current_user.get('subscription', False)
                status_text = "активна" if current_status else "неактивна"
                self.add_log_message(f"📊 Текущий статус подписки: {status_text}")
                self.add_log_message("💡 Для актуального статуса выполните выход и вход заново")

            except requests.exceptions.RequestException as e:
                self.add_log_message(f"❌ Ошибка сети при проверке подписки: {str(e)}")
            except Exception as e:
                self.add_log_message(f"⚠️ Ошибка при проверке подписки: {str(e)}")

        thread = threading.Thread(target=check_thread)
        thread.daemon = True
        thread.start()

    def back_event(self):
        """Выход из аккаунта"""
        self.current_user = None
        self.main_frame.grid_forget()
        self.show_sign_in()

    def show_sign_in(self):
        """Показ формы входа"""
        self.main_frame.grid_forget()
        self.sign_in_frame.grid(row=0, column=0, padx=200, pady=100, sticky="nsew")
        self.username_entry.delete(0, 'end')
        self.password_entry.delete(0, 'end')

    def show_main_frame(self):
        """Показ главного фрейма с данными пользователя"""
        self.sign_in_frame.grid_forget()
        self.main_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")  # Уменьшил отступы для большего пространства
        self.update_user_display()

    def update_user_display(self):
        """Обновление отображения данных пользователя"""
        if self.current_user:
            subscription_status = self.current_user.get('subscription', False)
            status_text = "Активна" if subscription_status else "Неактивна"
            status_color = "#28A745" if subscription_status else "#FF4444"

            self.user_info_label.configure(
                text=f"Пользователь: {self.current_user['login']} | Монеты: {self.current_user['coin']} | Подписка: {status_text}"
            )

    def back_event(self):
        """Выход из аккаунта"""
        self.current_user = None
        self.main_frame.grid_forget()
        self.show_sign_in()



















    # ------------------ Лог и статус ------------------

    def add_log_message(self, message):
        def safe_add():
            self.log_text.insert("end", f"{message}\n")
            self.log_text.see("end")
            self.log_text.update_idletasks()
        self.after(0, safe_add)

    def update_status(self, status, progress=None):
        def safe_update():
            self.status_label.configure(text=status)
            if progress is not None:
                self.progress_bar.set(progress)
            can_connect = (self.current_ovpn_file is not None and
                           self.vpn_manager.is_openvpn_installed() and
                           self.vpn_manager.is_admin() and
                           self.current_user and self.current_user.get('subscription', False) and
                           not self.vpn_manager.get_status())
            self.connect_button.configure(state="normal" if can_connect else "disabled")
        self.after(0, safe_update)






    # ------------------ Действия ------------------

    def on_browse_button_clicked(self):
        file_path = filedialog.askopenfilename(title="Выберите OVPN файл",initialdir="/",
                                               filetypes=[("OVPN файлы","*.ovpn"),("Все файлы","*.*")])
        if file_path:
            self.current_ovpn_file = file_path
            self.file_entry.delete(0,"end")
            self.file_entry.insert(0,file_path)
            self.add_log_message(f"📁 Выбран файл: {os.path.basename(file_path)}")
            self.update_status("Готов к подключению",0.0)

    def on_connect_button_clicked(self):
        if not self.current_ovpn_file:
            self.add_log_message("❌ Выберите .ovpn файл")
            return
        if not self.current_user or not self.current_user.get('subscription', False):
            self.add_log_message("❌ Подключение невозможно: подписка неактивна")
            return
        
        # Обновляем глобальные переменные
        global current_user_global, current_password_global
        current_user_global = self.current_user
        current_password_global = self.current_password
        
        def thread_connect():
            success = self.vpn_manager.connect(self.current_ovpn_file)
            if not success:
                self.add_log_message("❌ Не удалось запустить подключение")
        
        t = threading.Thread(target=thread_connect)
        t.daemon = True
        t.start()





# ------------------ Запуск ------------------

if __name__ == "__main__":
    if sys.platform != "linux":
        print("❌ Только Linux поддерживается!")
        sys.exit(1)
    app = App()
    app.mainloop()
