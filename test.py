import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import re

# === НАСТРОЙКИ ===
YANDEX_API_KEY = "e43928ca-d7b8-47fc-a556-d13d59675c24"  # ⚠️ Замени на свой
GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"


# === Нормализация адреса с помощью регулярных выражений ===
def normalize_address(raw_address: str) -> str:
    # Удаляем индекс (6 цифр)
    address = re.sub(r'\b\d{6}\b,?\s*', '', raw_address).strip()
    # Удаляем лишние запятые и пробелы
    address = re.sub(r'\s+', ' ', address)
    address = re.sub(r'\s*,\s*', ', ', address)
    address = address.strip(' ,')

    # Замены сокращений
    replacements = {
        r'\bР\-Н\b': 'район',
        r'\bС\b': 'с.',
        r'\bП\b': 'п.',
        r'\bРП\b': 'рп',
        r'\bГ\b': 'г.',
        r'\bПГТ\b': 'пгт',
        r'\bУЛ\.?\b': 'ул.',
        r'\bД\.?\b': 'д.',
        r'\bДВЛД\.?\b': 'двлд.',
        r'\bЗД\.?\b': 'зд.',
        r'\bПЕР\.?\b': 'пер.',
        r'\bПЛ\.?\b': 'пл.',
        r'\bМКР\b': 'мкр',
        r'\bСЕЛЬСОВЕТ\b': 'с/с',
    }
    for pattern, repl in replacements.items():
        address = re.sub(pattern, repl, address, flags=re.IGNORECASE)

    return address.strip(' ,')


# === Геокодирование через Yandex ===
def geocode_address_yandex(address: str):
    try:
        params = {
            "apikey": YANDEX_API_KEY,
            "geocode": address,
            "format": "json",
            "results": 1
        }
        response = requests.get(GEOCODER_URL, params=params, timeout=10)
        if response.status_code != 200:
            return None, f"Ошибка: код {response.status_code}"

        data = response.json()
        try:
            obj = data["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]
            lon, lat = map(float, obj["Point"]["pos"].split())
            full_address = obj["metaDataProperty"]["GeocoderMetaData"]["text"]
            return (lat, lon, full_address), None
        except (KeyError, IndexError):
            return None, "Адрес не найден"
    except Exception as e:
        return None, f"Ошибка сети: {e}"


class AddressGeocoderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📍 Геокодер (Yandex API)")
        self.root.geometry("750x650")
        self.root.resizable(False, False)

        self.create_widgets()

    def create_widgets(self):
        # Заголовок
        title = tk.Label(self.root, text="Геокодер адресов (Yandex)", font=("Arial", 14, "bold"))
        title.pack(pady=10)

        # Поле ввода
        input_frame = tk.Frame(self.root)
        input_frame.pack(pady=10, padx=20, fill="x")

        tk.Label(input_frame, text="Введите адрес:", font=("Arial", 10)).pack(anchor="w")
        self.address_entry = tk.Entry(input_frame, font=("Arial", 11), width=80)
        self.address_entry.pack(fill="x", pady=5)
        self.setup_entry_bindings()

        # Кнопка
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=5)
        self.search_button = tk.Button(
            btn_frame,
            text="🔍 Найти координаты",
            font=("Arial", 10, "bold"),
            bg="#1E90FF",
            fg="white",
            command=self.geocode
        )
        self.search_button.pack()

        # Результат
        result_frame = tk.LabelFrame(self.root, text="Результат", padx=10, pady=10)
        result_frame.pack(pady=10, padx=20, fill="both", expand=True)

        self.result_text = scrolledtext.ScrolledText(result_frame, height=22, font=("Courier", 10))
        self.result_text.pack(fill="both", expand=True)

        # Контекстное меню
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Вставить", command=self.paste_text)
        self.context_menu.add_command(label="Копировать", command=self.copy_text)
        self.context_menu.add_command(label="Вырезать", command=self.cut_text)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Очистить", command=lambda: self.address_entry.delete(0, tk.END))
        self.context_menu.add_command(label="Копировать результат", command=self.copy_result)

    def setup_entry_bindings(self):
        self.address_entry.bind("<Control-v>", self.paste_text)
        self.address_entry.bind("<Control-c>", self.copy_text)
        self.address_entry.bind("<Control-x>", self.cut_text)
        self.address_entry.bind("<Button-3>", self.show_context_menu_input)
        self.result_text.bind("<Button-3>", self.show_context_menu_output)

    def paste_text(self, event=None):
        try:
            self.address_entry.insert(tk.INSERT, self.root.clipboard_get())
        except tk.TclError:
            pass
        return "break"

    def copy_text(self, event=None):
        try:
            selected = self.address_entry.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
        except tk.TclError:
            pass
        return "break"

    def cut_text(self, event=None):
        self.copy_text()
        try:
            self.address_entry.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        return "break"

    def show_context_menu_input(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def show_context_menu_output(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def copy_result(self):
        content = self.result_text.get(1.0, tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            messagebox.showinfo("Копирование", "Результат скопирован в буфер обмена!")

    def geocode(self):
        raw_address = self.address_entry.get().strip()
        if not raw_address:
            messagebox.showwarning("Ошибка", "Введите адрес!")
            return

        # Нормализация
        cleaned = normalize_address(raw_address)

        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"📝 Исходный: {raw_address}\n")
        self.result_text.insert(tk.END, f"✅ Очищенный: {cleaned}\n\n🔍 Поиск координат...\n")
        self.root.update()

        # Геокодирование
        coords, error = geocode_address_yandex(cleaned)

        if coords:
            lat, lon, full_found = coords
            result = (
                f"🎯 УСПЕШНО\n"
                f"Оригинал: {raw_address}\n"
                f"Очищено: {cleaned}\n"
                f"Найдено: {full_found}\n"
                f"Широта: {lat:.6f}\n"
                f"Долгота: {lon:.6f}\n"
                f"Точность: Высокая"
            )
        else:
            result = f"❌ Ошибка\n{error}\n\nПопробуйте изменить формулировку."

        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, result)


# === Запуск ===
if __name__ == "__main__":
    root = tk.Tk()
    app = AddressGeocoderApp(root)
    root.mainloop()