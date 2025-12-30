import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk
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

# ------------------ Глобальные переменные ------------------
current_user_global = None
current_password_global = None
API_BASE_URL = "https://xn--80adkrr5a.xn--p1ai"

# Настройка темы приложения
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ------------------ VPN MANAGER ------------------
class VPNManager:
    def __init__(self):
        self.process = None
        self.is_connected = False
        self.log_callback = None
        self.status_callback = None
        self.temp_ovpn_path = None
        self.failed_attempts = 0
        self.expected_ip = None
        self.current_server = None

    def set_log_callback(self, cb):
        self.log_callback = cb

    def set_status_callback(self, cb):
        self.status_callback = cb

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def update_status(self, status, progress=None):
        if self.status_callback:
            self.status_callback(status, progress)

    def is_admin(self):
        try:
            return os.geteuid() == 0
        except:
            return False

    def is_openvpn_installed(self):
        return subprocess.run(["which", "openvpn"], capture_output=True).returncode == 0

    def get_public_ip(self):
        """Получение текущего публичного IP адреса"""
        for url in ["https://api.ipify.org", "https://ident.me", "https://icanhazip.com"]:
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    return r.text.strip()
            except:
                continue
        return None

    def connect(self, vpn_type, login, password):
        """vpn_type: 'ru' - для подключения к РФ (из-за границы), 'world' - для выхода из РФ"""
        if not self.is_admin():
            self.log("Требуются права root")
            return False

        # Устанавливаем ожидаемый IP в зависимости от сервера
        if vpn_type == "ru":
            self.expected_ip = "95.163.232.136"
            server_name = "Россия"
        else:  # world
            self.expected_ip = "147.45.255.17"
            server_name = "Нидерланды"

        self.current_server = server_name
        self.log(f"Подключение к {server_name}...")

        try:
            r = requests.post(
                f"{API_BASE_URL}/api/app/get-ovpn",
                json={
                    "login": login,
                    "password": password,
                    "type": vpn_type
                },
                timeout=10
            )
            data = r.json()
        except Exception as e:
            self.log(f"Ошибка API: {e}")
            self.failed_attempts += 1
            return False

        if not data.get("success"):
            error_msg = data.get("error", "Неизвестная ошибка")
            self.log(f"Ошибка сервера: {error_msg}")
            self.failed_attempts += 1
            return False

        ovpn_text = data["ovpn"]

        # Сохраняем временный конфиг
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ovpn")
        tmp.write(ovpn_text.encode())
        tmp.close()
        self.temp_ovpn_path = tmp.name

        threading.Thread(target=self._run_openvpn, args=(login, password, server_name), daemon=True).start()
        return True

    def _run_openvpn(self, login, password, server_name):
        """Запуск OpenVPN с проверкой IP"""
        try:
            self.log(f"Запуск OpenVPN...")

            cmd = f'echo -e "{login}\\n{password}" | openvpn --config {self.temp_ovpn_path} --auth-user-pass /dev/stdin --verb 1'
            self.process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            time.sleep(1)
            if os.path.exists(self.temp_ovpn_path):
                os.remove(self.temp_ovpn_path)

            connected = False
            start_time = time.time()

            # Читаем вывод OpenVPN
            for line in self.process.stdout:
                line = line.strip()

                if "Initialization Sequence Completed" in line:
                    # Подождать немного для установки соединения
                    time.sleep(2)

                    # Проверить IP
                    current_ip = self.get_public_ip()

                    if current_ip == self.expected_ip:
                        self.is_connected = True
                        connected = True
                        self.failed_attempts = 0
                        self.log(f"Успешно подключено к {server_name}")
                        self.log(f"Ваш IP: {current_ip}")
                    else:
                        self.log(f"Подключено, но IP не соответствует ({current_ip})")
                        self.log(f"Ожидался IP: {self.expected_ip}")
                        self.failed_attempts += 1
                        self.disconnect()

                    break

                if "AUTH_FAILED" in line:
                    self.log("Ошибка аутентификации")
                    self.failed_attempts += 1
                    break

                if "ERROR" in line and "tls" not in line.lower():
                    self.log(f"{line[:80]}")

                # Таймаут подключения
                if time.time() - start_time > 30:
                    self.log("Таймаут подключения")
                    break

            if not connected:
                self.failed_attempts += 1
                self.log("Не удалось подключиться")

                if self.failed_attempts >= 5:
                    config_type = "ru" if self.current_server == "Россия" else "world"
                    self.log(f"Слишком много неудачных попыток ({self.failed_attempts})")
                    self.log(f"Пожалуйста, перегенерируйте конфигурационный файл ({config_type})")
                    self.failed_attempts = 0

                if self.process:
                    self.process.terminate()

        except Exception as e:
            self.log(f"Ошибка: {e}")
            self.failed_attempts += 1

    def disconnect(self):
        """Отключение VPN соединения"""
        self.log("Отключение VPN...")

        # Принудительное завершение всех процессов OpenVPN
        self.kill_all_openvpn()

        self.is_connected = False
        self.process = None

    def kill_all_openvpn(self):
        """Принудительное завершение всех процессов OpenVPN"""
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
                self.log(f"Завершено процессов OpenVPN: {killed}")
        except Exception as e:
            self.log(f"Ошибка при завершении процессов: {e}")

# ------------------ Анимированные титры ------------------
class CreditsRollWindow(ctk.CTkToplevel):
    def __init__(self, parent, theme="dark"):
        """Показать видео титры"""
        import subprocess
        import os

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        video_file = os.path.join(BASE_DIR, "titry.mp4")

        if os.path.exists(video_file):
            try:
                # Открываем видео в отдельном процессе
                if sys.platform == "win32":
                    os.startfile(video_file)
                elif sys.platform == "darwin":
                    subprocess.call(['open', video_file])
                else:
                    subprocess.call(['xdg-open', video_file])
            except:
                # Если не удалось открыть видео, показываем анимацию
                self.show_fallback_animation()
        else:
            self.show_fallback_animation()

    def start_animation(self):
        """Показать видео титры"""
        import subprocess
        import os

        video_file = "titry.mp4"

        if os.path.exists(video_file):
            try:
                # Открываем видео в отдельном процессе
                if sys.platform == "win32":
                    os.startfile(video_file)
                elif sys.platform == "darwin":
                    subprocess.call(['open', video_file])
                else:
                    subprocess.call(['xdg-open', video_file])
            except:
                # Если не удалось открыть видео, показываем анимацию
                self.show_fallback_animation()
        else:
            self.show_fallback_animation()



# ------------------ ГЛАВНОЕ ПРИЛОЖЕНИЕ ------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Kvanet VPN Client")
        self.geometry("500x700")
        self.minsize(500, 700)

        # Текущая тема
        self.current_theme = "dark"

        # Инициализация VPN менеджера
        self.vpn = VPNManager()
        self.vpn.set_log_callback(self.add_log)

        self.current_user = None
        self.current_password = None
        self.is_authenticated = False

        # Флаг подключения
        self.is_connecting = False
        self.dot_counter = 0

        # Переменная для выбора сервера
        self.server_var = ctk.StringVar(value="world")  # По умолчанию Нидерланды

        # Создаем изображения флагов
        self.create_flag_images()

        # Настройка цветовой схемы
        self.setup_theme()

        # Построение интерфейса
        self.build_ui()

        # Запуск проверки IP для обновления кнопки
        self.start_ip_checker()

        # Показать окно входа
        self.show_login_screen()
        self.load_saved_credentials()

    def create_flag_images(self):
        """Создание изображений флагов"""
        # Флаг Нидерландов (красный-белый-синий горизонтальные полосы)
        nl_flag = Image.new('RGB', (40, 25), color='white')
        draw = ImageDraw.Draw(nl_flag)
        # Красная полоса
        draw.rectangle([0, 0, 40, 8], fill='#AE1C28')
        # Белая полоса (уже белый фон)
        draw.rectangle([0, 8, 40, 17], fill='white')
        # Синяя полоса
        draw.rectangle([0, 17, 40, 25], fill='#21468B')
        self.nl_flag_image = ImageTk.PhotoImage(nl_flag)

        # Флаг России (белый-синий-красный горизонтальные полосы)
        ru_flag = Image.new('RGB', (40, 25), color='white')
        draw = ImageDraw.Draw(ru_flag)
        # Белая полоса
        draw.rectangle([0, 0, 40, 8], fill='white')
        # Синяя полоса
        draw.rectangle([0, 8, 40, 17], fill='#0C47B7')
        # Красная полоса
        draw.rectangle([0, 17, 40, 25], fill='#E4181C')
        self.ru_flag_image = ImageTk.PhotoImage(ru_flag)

    def setup_theme(self):
        """Настройка цветовой схемы в зависимости от темы"""
        if self.current_theme == "dark":
            # ТЁМНАЯ ТЕМА (черный + фиолетовый)
            self.bg_color = "#0A0A0F"
            self.frame_bg = "#1A1A2E"
            self.text_color = "#E0E0E0"
            self.accent_color = "#BB86FC"
            self.button_color = "#2D2D44"
            self.hover_color = "#3D3D5C"
            self.switch_text_color = "#E0E0E0"
            ctk.set_appearance_mode("dark")
        else:
            # СВЕТЛАЯ ТЕМА
            self.bg_color = "#F5F5F7"
            self.frame_bg = "#FFFFFF"
            self.text_color = "#000000"
            self.accent_color = "#7B1FA2"
            self.button_color = "#F0F0F5"
            self.hover_color = "#E0E0E5"
            self.switch_text_color = "#000000"
            ctk.set_appearance_mode("light")

        self.configure(fg_color=self.bg_color)

    def build_ui(self):
        """Построение пользовательского интерфейса"""

        # ------------------ ЭКРАН ВХОДА ------------------
        self.login_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=15)

        # Логотип
        self.logo_label = ctk.CTkLabel(
            self.login_frame,
            text="Kvanet VPN",
            font=("Arial", 32, "bold"),
            text_color=self.accent_color
        )
        self.logo_label.pack(pady=(60, 40))

        # Поля ввода
        self.login_entry = ctk.CTkEntry(
            self.login_frame,
            placeholder_text="Логин",
            width=300,
            height=50,
            fg_color=self.button_color,
            border_color=self.accent_color,
            text_color=self.text_color,
            placeholder_text_color="#888888",
            font=("Arial", 14)
        )
        self.login_entry.pack(pady=10)

        self.password_entry = ctk.CTkEntry(
            self.login_frame,
            placeholder_text="Пароль",
            show="•",
            width=300,
            height=50,
            fg_color=self.button_color,
            border_color=self.accent_color,
            text_color=self.text_color,
            placeholder_text_color="#888888",
            font=("Arial", 14)
        )
        self.password_entry.pack(pady=10)

        # Кнопка входа
        self.login_btn = ctk.CTkButton(
            self.login_frame,
            text="Войти",
            command=self.login,
            width=300,
            height=50,
            fg_color=self.accent_color,
            hover_color="#9C4DFF" if self.current_theme == "dark" else "#7B1FA2",
            text_color="#FFFFFF",
            font=("Arial", 16, "bold")
        )
        self.login_btn.pack(pady=20)

        # Кнопка выхода из приложения
        self.exit_btn = ctk.CTkButton(
            self.login_frame,
            text="Выход",
            command=self.exit_app,
            width=300,
            height=50,
            fg_color="#FF4444",
            hover_color="#CC0000",
            text_color="#FFFFFF",
            font=("Arial", 16, "bold")
        )
        self.exit_btn.pack(pady=10)

        # ------------------ МЕНЮ (после входа) ------------------
        self.menu_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=10)

        menu_buttons = [
            ("Основной экран", self.show_main_screen),
            ("Настройки", self.show_settings),
            ("Выйти", self.logout)
        ]

        for text, command in menu_buttons:
            btn = ctk.CTkButton(
                self.menu_frame,
                text=text,
                command=command,
                fg_color=self.button_color,
                hover_color=self.hover_color,
                text_color=self.text_color,
                corner_radius=8,
                height=40,
                font=("Arial", 14)
            )
            btn.pack(side="left", padx=5, pady=5, expand=True)

        # ------------------ ОСНОВНОЙ ЭКРАН (ЦЕНТРИРОВАННЫЙ) ------------------
        self.main_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=15)

        # Центральный контейнер для всего контента
        self.center_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.center_container.pack(expand=True, fill="both")

        # Верхняя часть (отступ)
        top_space = ctk.CTkFrame(self.center_container, fg_color="transparent", height=60)
        top_space.pack(fill="x")

        # Логотип на основном экране
        self.main_logo = ctk.CTkLabel(
            self.center_container,
            text="Kvanet VPN",
            font=("Arial", 28, "bold"),
            text_color=self.accent_color
        )
        self.main_logo.pack(pady=(0, 60))

        # ПЕРЕКЛЮЧАТЕЛЬ СЕРВЕРА с флагами
        self.switch_container = ctk.CTkFrame(self.center_container, fg_color="transparent")
        self.switch_container.pack(pady=20)

        # Флаг Нидерландов слева
        self.nl_flag_label = ctk.CTkLabel(
            self.switch_container,
            text="",
            image=self.nl_flag_image
        )
        self.nl_flag_label.pack(side="left", padx=15)

        # Сам переключатель
        self.server_switch = ctk.CTkSwitch(
            self.switch_container,
            text="",
            command=self.on_server_switch,
            width=70,
            height=35,
            switch_width=80,
            switch_height=35,
            button_color=self.accent_color,
            button_hover_color="#9C4DFF" if self.current_theme == "dark" else "#7B1FA2",
            progress_color=self.accent_color
        )
        self.server_switch.pack(side="left", padx=10)

        # Флаг России справа
        self.ru_flag_label = ctk.CTkLabel(
            self.switch_container,
            text="",
            image=self.ru_flag_image
        )
        self.ru_flag_label.pack(side="left", padx=15)

        # Статус подключения (визуальный индикатор)
        self.status_indicator_frame = ctk.CTkFrame(self.center_container, fg_color="transparent")
        self.status_indicator_frame.pack(pady=30)

        self.status_indicator = ctk.CTkLabel(
            self.status_indicator_frame,
            text="●",
            font=("Arial", 28),
            text_color="#888888"
        )
        self.status_indicator.pack()

        self.status_text = ctk.CTkLabel(
            self.status_indicator_frame,
            text="Не подключено",
            font=("Arial", 16),
            text_color=self.text_color
        )
        self.status_text.pack(pady=10)

        # Большая центральная кнопка
        self.connect_toggle_btn = ctk.CTkButton(
            self.center_container,
            text="ПОДКЛЮЧИТЬСЯ",
            command=self.toggle_vpn_connection,
            width=280,
            height=70,
            font=("Arial", 20, "bold"),
            fg_color="#2E8B57",
            hover_color="#3CB371",
            text_color="#FFFFFF",
            corner_radius=15
        )
        self.connect_toggle_btn.pack(pady=30)

        # Нижняя часть (отступ)
        bottom_space = ctk.CTkFrame(self.center_container, fg_color="transparent", height=40)
        bottom_space.pack(fill="x")

        # ------------------ НАСТРОЙКИ ------------------
        self.settings_frame = ctk.CTkFrame(self, fg_color=self.frame_bg, corner_radius=15)

        # Центральный контейнер для настроек
        self.settings_center = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.settings_center.pack(expand=True, fill="both", padx=20, pady=20)

        # Заголовок настроек
        settings_title = ctk.CTkLabel(
            self.settings_center,
            text="Настройки",
            font=("Arial", 24, "bold"),
            text_color=self.accent_color
        )
        settings_title.pack(pady=(20, 40))

        # Выбор темы
        theme_frame = ctk.CTkFrame(self.settings_center, fg_color="transparent")
        theme_frame.pack(pady=20)

        # Исправляем: теперь text_color динамически меняется
        self.theme_label = ctk.CTkLabel(
            theme_frame,
            text="ТЕМА",
            font=("Arial", 18, "bold"),
            text_color=self.text_color  # Динамический цвет
        )
        self.theme_label.pack(pady=(0, 15))

        self.theme_var = ctk.StringVar(value=self.current_theme)

        theme_buttons_frame = ctk.CTkFrame(theme_frame, fg_color="transparent")
        theme_buttons_frame.pack()

        self.dark_btn = ctk.CTkButton(
            theme_buttons_frame,
            text="Тёмная",
            width=120,
            height=45,
            fg_color=self.accent_color if self.current_theme == "dark" else self.button_color,
            hover_color=self.hover_color,
            text_color="#FFFFFF" if self.current_theme == "dark" else self.text_color,
            font=("Arial", 14),
            command=lambda: self.set_theme("dark")
        )
        self.dark_btn.pack(side="left", padx=10)

        self.light_btn = ctk.CTkButton(
            theme_buttons_frame,
            text="Светлая",
            width=120,
            height=45,
            fg_color=self.accent_color if self.current_theme == "light" else self.button_color,
            hover_color=self.hover_color,
            text_color="#000000" if self.current_theme == "light" else self.text_color,
            font=("Arial", 14),
            command=lambda: self.set_theme("light")
        )
        self.light_btn.pack(side="left", padx=10)

        # Кнопка титров
        credits_btn = ctk.CTkButton(
            self.settings_center,
            text="Титры",
            command=self.show_rolling_credits,
            width=200,
            height=50,
            fg_color=self.accent_color,
            text_color="#FFFFFF",
            font=("Arial", 16, "bold"),
            corner_radius=10
        )
        credits_btn.pack(pady=60)

        # Нижние надписи (с динамическими цветами)
        bottom_frame = ctk.CTkFrame(self.settings_center, fg_color="transparent")
        bottom_frame.pack(side="bottom", pady=20)

        self.version_label = ctk.CTkLabel(
            bottom_frame,
            text="Kvanet VPN Client 2.1.5",
            font=("Arial", 12),
            text_color=self.text_color  # Динамический цвет
        )
        self.version_label.pack()

        self.made_label = ctk.CTkLabel(
            bottom_frame,
            text="Сделано в Лобачевском",
            font=("Arial", 11),
            text_color=self.text_color  # Динамический цвет
        )
        self.made_label.pack(pady=(5, 0))

    def on_server_switch(self):
        """Обработка переключения сервера"""
        if self.server_switch.get():
            self.server_var.set("ru")
        else:
            self.server_var.set("world")

    def set_theme(self, theme):
        """Установка темы через кнопки"""
        self.current_theme = theme
        self.theme_var.set(theme)
        self.setup_theme()
        self.update_theme_colors()

    def update_theme_colors(self):
        """Обновление цветов всех виджетов при смене темы"""
        # Обновление всех фреймов
        frames = [self.login_frame, self.menu_frame, self.main_frame, self.settings_frame]
        for frame in frames:
            if frame.winfo_exists():
                frame.configure(fg_color=self.frame_bg)

        # Обновление текстовых цветов
        text_widgets = [
            self.logo_label, self.main_logo,
            self.login_entry, self.password_entry,
            self.status_text, self.theme_label,
            self.version_label, self.made_label
        ]

        for widget in text_widgets:
            if widget.winfo_exists():
                if hasattr(widget, 'configure'):
                    try:
                        widget.configure(text_color=self.text_color)
                    except:
                        pass

        # Обновление кнопок меню
        for widget in self.menu_frame.winfo_children():
            if isinstance(widget, ctk.CTkButton):
                widget.configure(
                    fg_color=self.button_color,
                    hover_color=self.hover_color,
                    text_color=self.text_color
                )

        # Обновление кнопок темы в настройках
        if self.dark_btn.winfo_exists():
            self.dark_btn.configure(
                fg_color=self.accent_color if self.current_theme == "dark" else self.button_color,
                text_color="#FFFFFF"
            )

        if self.light_btn.winfo_exists():
            text_color = "#000000" if self.current_theme == "light" else self.text_color
            self.light_btn.configure(
                fg_color=self.accent_color if self.current_theme == "light" else self.button_color,
                text_color=text_color
            )

    # ------------------ АНИМАЦИЯ КНОПКИ ------------------
    def start_connecting_animation(self):
        """Запуск анимации точек при подключении"""
        if self.is_connecting:
            self.dot_counter = (self.dot_counter + 1) % 4
            dots = "." * self.dot_counter
            self.connect_toggle_btn.configure(text=f"ПОДКЛЮЧЕНИЕ{dots}")
            self.after(500, self.start_connecting_animation)

    def stop_connecting_animation(self):
        """Остановка анимации"""
        self.is_connecting = False
        self.dot_counter = 0

    def update_connect_button(self):
        """Обновление состояния кнопки"""
        if not self.current_user:
            return

        current_ip = self.vpn.get_public_ip()
        vpn_ips = ["147.45.255.17", "95.163.232.136"]

        if current_ip in vpn_ips:
            if self.is_connecting:
                self.is_connecting = False
                self.stop_connecting_animation()

            self.vpn.is_connected = True

            self.connect_toggle_btn.configure(
                text="ОТКЛЮЧИТЬСЯ",
                fg_color="#FF4444",
                hover_color="#CC0000",
                state="normal"
            )

            self.status_indicator.configure(text_color="#00FF00")
            self.status_text.configure(text="Подключено")

            self.is_connecting = False

        elif self.is_connecting:
            self.connect_toggle_btn.configure(
                fg_color="#FFA500",
                hover_color="#FF8C00",
                state="normal"
            )
            self.status_indicator.configure(text_color="#FFA500")
            self.status_text.configure(text="Подключение...")
        else:
            self.vpn.is_connected = False
            self.connect_toggle_btn.configure(
                text="ПОДКЛЮЧИТЬСЯ",
                fg_color="#2E8B57",
                hover_color="#3CB371",
                state="normal"
            )
            self.status_indicator.configure(text_color="#888888")
            self.status_text.configure(text="Не подключено")

    # ------------------ ОСНОВНЫЕ МЕТОДЫ ------------------
    def login(self):
        """Авторизация пользователя"""
        login = self.login_entry.get().strip()
        password = self.password_entry.get()

        if not login or not password:
            messagebox.showerror("Ошибка", "Введите логин и пароль")
            return

        try:
            r = requests.post(f"{API_BASE_URL}/api/app/login",
                            json={"login": login, "password": password})
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
        self.show_main_interface()
        self.add_log(f"Вход выполнен: {login}")

    def toggle_vpn_connection(self):
        """Переключение состояния VPN"""
        if not self.current_user:
            messagebox.showerror("Ошибка", "Сначала выполните вход")
            return

        current_ip = self.vpn.get_public_ip()
        vpn_ips = ["147.45.255.17", "95.163.232.136"]

        if current_ip in vpn_ips:
            self.vpn.disconnect()
            self.connect_toggle_btn.configure(
                text="ПОДКЛЮЧИТЬСЯ",
                fg_color="#2E8B57",
                hover_color="#3CB371"
            )
            self.status_indicator.configure(text_color="#888888")
            self.status_text.configure(text="Не подключено")
            self.is_connecting = False
            self.stop_connecting_animation()
        else:
            server_type = self.server_var.get()
            self.is_connecting = True
            self.start_connecting_animation()
            self.status_indicator.configure(text_color="#FFA500")
            self.status_text.configure(text="Подключение...")

            success = self.vpn.connect(server_type, self.current_user["login"], self.current_password)

            if not success:
                self.is_connecting = False
                self.stop_connecting_animation()
                self.connect_toggle_btn.configure(
                    text="ПОДКЛЮЧИТЬСЯ",
                    fg_color="#2E8B57",
                    hover_color="#3CB371"
                )
                self.status_indicator.configure(text_color="#888888")
                self.status_text.configure(text="Не подключено")

    def check_vpn_status(self):
        """Периодическая проверка статуса VPN"""
        if not self.current_user:
            self.after(2000, self.check_vpn_status)
            return

        self.update_connect_button()

        self.after(2000, self.check_vpn_status)

    def start_ip_checker(self):
        """Запуск периодической проверки IP"""
        self.check_vpn_status()

    def add_log(self, msg):
        """Вывод лога в терминал"""
        print(msg)

    def change_theme(self):
        """Смена темы приложения (старый метод)"""
        new_theme = self.theme_var.get()
        if new_theme != self.current_theme:
            self.current_theme = new_theme
            self.setup_theme()
            self.update_theme_colors()

    def show_rolling_credits(self):
        """Показать анимированные титры"""
        CreditsRollWindow(self, self.current_theme)

    # ------------------ УПРАВЛЕНИЕ ИНТЕРФЕЙСОМ ------------------
    def show_login_screen(self):
        """Показать экран входа"""
        self.hide_all_frames()
        self.login_frame.pack(expand=True, fill="both", padx=40, pady=40)

    def show_main_interface(self):
        """Показать основной интерфейс после входа"""
        self.hide_all_frames()
        self.menu_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.main_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))

        if self.server_var.get() == "ru":
            self.server_switch.select()
        else:
            self.server_switch.deselect()

    def show_main_screen(self):
        """Показать основной экран из меню"""
        self.hide_all_frames()
        self.menu_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.main_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))

    def show_settings(self):
        """Показать настройки"""
        self.hide_all_frames()
        self.menu_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.settings_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))

    def hide_all_frames(self):
        """Скрыть все фреймы"""
        frames = [self.login_frame, self.menu_frame, self.main_frame, self.settings_frame]
        for frame in frames:
            frame.pack_forget()

    def logout(self):
        """Выход из аккаунта"""
        if self.vpn.is_connected:
            self.vpn.disconnect()
            time.sleep(1)

        self.current_user = None
        self.current_password = None
        self.is_authenticated = False
        self.is_connecting = False

        global current_user_global, current_password_global
        current_user_global = None
        current_password_global = None

        self.clear_saved_credentials()
        self.add_log("Выход из аккаунта")
        self.show_login_screen()

    def exit_app(self):
        """Выход из приложения"""
        if self.vpn.is_connected:
            self.vpn.disconnect()
            time.sleep(1)

        self.destroy()
        sys.exit(0)
    def get_credentials_path(self):
        config_dir = Path.home() / ".config" / "kvanet"
        config_dir.mkdir(parents=True, exist_ok=True)
        cred_path = config_dir / "credentials.json"
        return cred_path

    def save_credentials(self, login, password):
        cred_path = self.get_credentials_path()
        data = {
            "login": login,
            "password": password
        }
        with open(cred_path, "w") as f:
            json.dump(data, f)
        os.chmod(cred_path, 0o600)

    def load_saved_credentials(self):
        cred_path = self.get_credentials_path()
        if not cred_path.exists():
            return
        try:
            with open(cred_path, "r") as f:
                data = json.load(f)
            self.login_entry.insert(0, data.get("login", ""))
            self.password_entry.insert(0, data.get("password", ""))
        except Exception as e:
            print(f"Не удалось загрузить учётные данные: {e}")

    def clear_saved_credentials(self):
        cred_path = self.get_credentials_path()
        if cred_path.exists():
            cred_path.unlink()

# ------------------ ТОЧКА ВХОДА ------------------
if __name__ == "__main__":
    if os.geteuid() != 0:
        messagebox.showerror(
            "Требуются права администратора",
            "Для работы VPN необходимы права администратора.\n\n"
            "Пожалуйста, запустите приложение через ярлык из меню."
        )
        sys.exit(1)

    app = App()
    app.mainloop()
