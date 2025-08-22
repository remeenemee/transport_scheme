import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
from geopy.geocoders import Nominatim
from tenacity import retry, stop_after_attempt, wait_fixed
import openrouteservice
from openrouteservice import convert
import time
import random
from datetime import datetime
import traceback
import io
import base64
from PIL import Image
import os

# --- Настройка страницы ---
st.set_page_config(layout="wide", page_title="Транспортная схема доставки", page_icon="🚚")

# --- Инициализация сессии ---
if 'delivery_data' not in st.session_state:
    st.session_state.delivery_data = []

if 'geocode_cache' not in st.session_state:
    st.session_state.geocode_cache = {}

# Инициализация лога ошибок
if 'error_log' not in st.session_state:
    st.session_state.error_log = []

if 'debug_mode' not in st.session_state:
    st.session_state.debug_mode = False

    if 'ors_api_key' not in st.session_state:
        st.session_state.ors_api_key = ""

# --- Функции для логирования ---
def log_error(message, error_type="ERROR", details=None):
    """Добавляет ошибку в лог с временной меткой"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    error_entry = {
        "time": timestamp,
        "type": error_type,
        "message": message,
        "details": details if details else ""
    }
    st.session_state.error_log.append(error_entry)
    # Ограничиваем размер лога (последние 50 записей)
    if len(st.session_state.error_log) > 50:
        st.session_state.error_log = st.session_state.error_log[-50:]

def log_info(message):
    """Добавляет информационное сообщение в лог"""
    log_error(message, "INFO")

def log_warning(message, details=None):
    """Добавляет предупреждение в лог"""
    log_error(message, "WARNING", details)

def log_api_error(api_name, error, details=None):
    """Специальная функция для логирования ошибок API"""
    error_message = f"Ошибка API {api_name}: {str(error)}"
    full_details = f"Подробности: {details}\nТрассировка: {traceback.format_exc()}" if details else traceback.format_exc()
    log_error(error_message, "API_ERROR", full_details)

# --- Словари ---
MATERIAL_COLORS = {
    "Асфальтобетон": "black",
    "Песок, щебень, грунт": "brown",
    "Трубопроводы": "blue",
    "Металлопрокатные изделия": "red",
    "Бетон": "gray"
}

MATERIALS = list(MATERIAL_COLORS.keys())

# --- Утилиты ---

def normalize_address(addr):
    addr = addr.strip()
    addr = addr.replace("  ", " ")
    addr = addr.replace("г.", "город")
    addr = addr.replace("пос.", "посёлок")
    addr = addr.replace("обл.", "область")
    addr = addr.replace("ул.", "улица")
    return addr

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def geocode_address(address):
    user_agent = f"transport_app_{random.randint(1000, 9999)}"
    geolocator = Nominatim(user_agent=user_agent)
    try:
        log_info(f"Запрос геокодирования для адреса: {address}")
        time.sleep(1.5 + random.uniform(0.5, 1.0))
        location = geolocator.geocode(address, timeout=10)
        if location:
            log_info(f"Геокодирование успешно: {location.address}")
            return (location.latitude, location.longitude), location.address
        else:
            log_warning(f"Геокодирование не дало результатов для адреса: {address}")
            return None, None
    except Exception as e:
        log_api_error("Nominatim", e, f"Адрес: {address}")
        return None, None

def geocode_address_cached(address):
    normalized = normalize_address(address)
    if normalized in st.session_state.geocode_cache:
        log_info(f"Использование кэшированных координат для: {normalized}")
        return st.session_state.geocode_cache[normalized]
    coords, full_addr = geocode_address(normalized)
    st.session_state.geocode_cache[normalized] = (coords, full_addr)
    return coords, full_addr

# --- Запрос API-ключа если не задан ---
def init_ors_client():
    try:
        if st.session_state.ors_api_key:
            ors_client = openrouteservice.Client(key=st.session_state.ors_api_key)
            log_info("Подключение к OpenRouteService успешно")
            return ors_client
        else:
            return None
    except Exception as e:
        log_api_error("OpenRouteService", e, "Ошибка инициализации клиента")
        return None

# Получаем клиент ORS если API-ключ уже установлен
ors_client = init_ors_client()

def get_route_ors(origin_coords, destination_coords):
    """
    origin_coords: (lat, lon)
    destination_coords: (lat, lon)
    Возвращает: маршрут (список координат), расстояние в км
    """
    try:
        log_info(f"Запрос маршрута ORS от {origin_coords} до {destination_coords}")
        coords = [(origin_coords[1], origin_coords[0]), (destination_coords[1], destination_coords[0])]

        # Подробное логирование запроса
        log_info(f"Параметры запроса ORS: coordinates={coords}, profile='driving-car'")

        # Убираем некорректный параметр extra_info
        result = ors_client.directions(
            coordinates=coords,
            profile='driving-car',
            format='geojson'
            # Убрали: extra_info=['total_distance'] - этот параметр вызывает ошибку 2003
        )

        log_info("Получен успешный ответ от ORS API")

        geometry = result['features'][0]['geometry']

        # Проверяем тип геометрии и декодируем соответственно
        if geometry['type'] == 'LineString':
            # Обычная LineString геометрия - используем координаты напрямую
            route_coords = [(point[1], point[0]) for point in geometry['coordinates']]  # (lat, lon)
        else:
            # Если геометрия закодирована - декодируем
            decoded = convert.decode_polyline(geometry)
            route_coords = [(point[1], point[0]) for point in decoded['coordinates']]  # (lat, lon)

        # Получаем расстояние из свойств маршрута
        distance_meters = result['features'][0]['properties']['segments'][0]['distance']
        distance_km = round(distance_meters / 1000, 2)

        log_info(f"Маршрут построен успешно, расстояние: {distance_km} км, точек: {len(route_coords)}")
        return route_coords, distance_km

    except Exception as e:
        # Детальное логирование ошибки API
        error_details = f"От: {origin_coords}, До: {destination_coords}"
        if hasattr(e, 'response') and e.response:
            error_details += f"\nHTTP статус: {e.response.status_code}"
            try:
                error_details += f"\nОтвет сервера: {e.response.json()}"
            except:
                error_details += f"\nОтвет сервера: {e.response.text}"
        elif hasattr(e, 'args') and e.args:
            error_details += f"\nДетали ошибки: {e.args[0]}"

        log_api_error("OpenRouteService", e, error_details)

        # Резерв: расстояние по прямой
        try:
            from geopy.distance import geodesic
            dist = round(geodesic(origin_coords, destination_coords).kilometers, 2)
            log_warning(f"Используется расчёт по прямой: {dist} км", "Ошибка ORS API")
            return None, dist
        except Exception as fallback_error:
            log_api_error("Geopy", fallback_error, "Ошибка при расчёте расстояния по прямой")
            return None, 0

# --- Интерфейс ---
st.title("🚚 Транспортная схема доставки материалов")

# --- Запрос API-ключа, если не установлен ---
if not st.session_state.ors_api_key:
    st.warning("⚠️ Для работы приложения необходим API-ключ OpenRouteService")

    with st.form("api_key_form"):
        api_key = st.text_input(
            "Введите API-ключ OpenRouteService",
            help="Получите бесплатный ключ на сайте https://openrouteservice.org/dev/#/signup",
            type="password"
        )

        sample_key = st.checkbox("Использовать демо-ключ")

        submit = st.form_submit_button("Подтвердить")

        if submit:
            if sample_key:
                api_key = ""

            if api_key:
                st.session_state.ors_api_key = api_key
                try:
                    ors_client = openrouteservice.Client(key=api_key)
                    st.success("✅ API-ключ установлен успешно!")
                    st.rerun()
                except Exception as e:
                    log_api_error("OpenRouteService", e, "Ошибка при проверке API-ключа")
                    st.error(f"❌ Ошибка при проверке API-ключа: {str(e)}")
            else:
                st.error("❌ Пожалуйста, введите API-ключ")

    st.markdown("""
    ### Как получить API-ключ OpenRouteService
    1. Перейдите на сайт [OpenRouteService](https://openrouteservice.org/dev/#/signup)
    2. Зарегистрируйтесь или войдите в существующий аккаунт
    3. Перейдите в раздел "Dashboard" и создайте новый токен
    4. Скопируйте токен и вставьте его в поле выше
    """)

    st.stop()  # Останавливаем выполнение до ввода API-ключа

# --- Панель отладки ---
with st.sidebar:
    st.header("🐛 Панель отладки")

    # Переключатель режима отладки
    debug_mode = st.checkbox("Показать детальные логи", value=st.session_state.debug_mode)
    st.session_state.debug_mode = debug_mode

    # Кнопки управления логом
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Очистить лог"):
            st.session_state.error_log = []
            st.rerun()

    with col2:
        if st.button("📋 Экспорт лога"):
            if st.session_state.error_log:
                log_text = "\n".join([
                    f"[{entry['time']}] {entry['type']}: {entry['message']}"
                    + (f"\n{entry['details']}" if entry['details'] else "")
                    for entry in st.session_state.error_log
                ])
                st.text_area("Экспорт лога ошибок", log_text, height=200)

    # Отображение лога ошибок
    st.subheader("📋 Лог событий")

    if st.session_state.error_log:
        # Фильтрация по типам сообщений
        filter_types = st.multiselect(
            "Фильтр по типам:",
            ["ERROR", "API_ERROR", "WARNING", "INFO"],
            default=["ERROR", "API_ERROR", "WARNING"] if not debug_mode else ["ERROR", "API_ERROR", "WARNING", "INFO"]
        )

        filtered_log = [entry for entry in st.session_state.error_log if entry['type'] in filter_types]

        # Показываем последние записи в обратном порядке
        for entry in reversed(filtered_log[-20:]):  # Последние 20 записей
            if entry['type'] == 'ERROR' or entry['type'] == 'API_ERROR':
                st.error(f"**[{entry['time']}]** {entry['message']}")
            elif entry['type'] == 'WARNING':
                st.warning(f"**[{entry['time']}]** {entry['message']}")
            elif entry['type'] == 'INFO' and debug_mode:
                st.info(f"**[{entry['time']}]** {entry['message']}")

            # Показываем детали если они есть и включен режим отладки
            if entry['details'] and debug_mode:
                with st.expander("Подробности"):
                    st.code(entry['details'], language="text")
    else:
        st.info("Лог пуст")

# --- Основной интерфейс ---
st.header("1. Добавьте поставщика")

col1, col2 = st.columns(2)

with col1:
    material = st.selectbox("Наименование материала", MATERIALS, key="mat")
    work_type = st.text_input(
        "Вид работ",
        value="Устройство дорожной одежды",
        help="Например: Устройство насыпи, основания, подстилающего слоя"
    )
    supplier_name = st.text_input(
        "Наименование поставщика",
        value="ГПКО \"ДЭП №2\"",
        help="Например: ООО \"САНТЕРМО\""
    )
    supplier_address = st.text_area(
        "Адрес поставщика",
        value="Правдинский район, город Правдинск, Электрическая ул., д.1",
        height=100
    )

with col2:
    st.subheader("📍 Адрес объекта (место размещения)")
    use_object_coords = st.checkbox("Ввести координаты объекта вручную")
    if use_object_coords:
        obj_coord_input = st.text_input("Координаты объекта (широта, долгота)", "")
    else:
        object_address = st.text_input(
            "Адрес объекта",
            value="Калининградская обл., Гурьевский район, пос. Невское, ул. Гагарина, д. ЗД. 229"
        )

# --- Кнопка добавления ---
if st.button("➕ Добавить поставщика"):
    log_info("Начало процесса добавления поставщика")

    # Геокодирование объекта
    if use_object_coords:
        try:
            lat, lon = map(float, [x.strip() for x in obj_coord_input.split(",")])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                obj_coords = (lat, lon)
                obj_full_addr = f"Координаты: {lat:.5f}, {lon:.5f}"
                log_info(f"Введены координаты объекта вручную: {obj_coords}")
            else:
                error_msg = "Координаты объекта вне допустимого диапазона."
                log_error(error_msg)
                st.error(error_msg)
                st.stop()
        except Exception as e:
            error_msg = "Некорректный формат координат объекта"
            log_error(error_msg, details=str(e))
            st.error("Введите корректные координаты объекта: например, 54.7100, 20.4800")
            st.stop()
    else:
        obj_coords, obj_full_addr = geocode_address_cached(object_address)
        if obj_coords is None:
            error_msg = f"Не удалось определить координаты объекта: {object_address}"
            log_error(error_msg)
            st.error("Не удалось определить координаты объекта. Проверьте адрес или введите координаты вручную.")
            st.stop()

    # Геокодирование поставщика
    use_supplier_coords = st.checkbox("Ввести координаты поставщика вручную", key="supp_coords")
    if use_supplier_coords:
        supp_coord_input = st.text_input("Координаты поставщика (широта, долгота)", key="supp_input")
        try:
            lat, lon = map(float, [x.strip() for x in supp_coord_input.split(",")])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                sup_coords = (lat, lon)
                sup_full_addr = f"Координаты: {lat:.5f}, {lon:.5f}"
                log_info(f"Введены координаты поставщика вручную: {sup_coords}")
            else:
                error_msg = "Координаты поставщика вне допустимого диапазона."
                log_error(error_msg)
                st.error(error_msg)
                st.stop()
        except Exception as e:
            error_msg = "Некорректный формат координат поставщика"
            log_error(error_msg, details=str(e))
            st.error("Введите корректные координаты поставщика: например, 54.7100, 20.4800")
            st.stop()
    else:
        sup_coords, sup_full_addr = geocode_address_cached(supplier_address)
        if sup_coords is None:
            error_msg = f"Не удалось определить координаты поставщика: {supplier_address}"
            log_error(error_msg)
            st.error("Не удалось определить координаты поставщика. Проверьте адрес или введите координаты вручную.")
            st.stop()

    # Расчёт маршрута по дорогам
    log_info("Начало расчёта маршрута")
    route_coords, road_distance = get_route_ors(sup_coords, obj_coords)

    # Сохранение
    idx = len(st.session_state.delivery_data) + 1
    st.session_state.delivery_data.append({
        "№ п/п": idx,
        "Наименование материала": material,
        "% от общей потребности": 100,
        "Вид работ": work_type,
        "Наименование поставщика": supplier_name,
        "Адрес": sup_full_addr,
        "Вид \"франко\" для данного материала": "-",
        "Железнодорожные перевозки %": "-",
        "Станции назначения, на которую прибывает материал": obj_full_addr,
        "Расстояние перевозки, км": road_distance,
        "Автомобильные перевозки %": 100,
        "Средняя дальность возки, км": road_distance,
        "Цвет": MATERIAL_COLORS[material],
        "supplier_coords": sup_coords,
        "object_coords": obj_coords,
        "route_coords": route_coords
    })

    log_info(f"Поставщик добавлен успешно: {supplier_name}, расстояние: {road_distance} км")

    success_msg = f"✅ Поставщик «{supplier_name}» добавлен! Расстояние "
    if route_coords:
        success_msg += f"по дорогам: {road_distance} км"
    else:
        success_msg += f"по прямой: {road_distance} км (маршрут по дорогам недоступен)"

    st.success(success_msg)

# --- Функции для экспорта данных ---
def export_to_excel(df, columns_to_show):
    """Экспортирует данные в Excel файл и возвращает их в виде скачиваемой ссылки"""
    # Создаем DataFrame только с нужными колонками
    export_df = df[columns_to_show].copy()

    # Создаем буфер для хранения Excel-файла
    output = io.BytesIO()

    # Используем pandas для создания Excel файла
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        export_df.to_excel(writer, sheet_name='Ведомость поставщиков', index=False)

        # Получаем объект workbook и worksheet
        workbook = writer.book
        worksheet = writer.sheets['Ведомость поставщиков']

        # Автоматическая настройка ширины столбцов
        for i, col in enumerate(export_df.columns):
            column_width = max(export_df[col].astype(str).map(len).max(), len(col) + 2)
            worksheet.set_column(i, i, column_width)

    # Получаем содержимое буфера
    processed_data = output.getvalue()

    # Создаем ссылку для скачивания
    b64 = base64.b64encode(processed_data).decode()
    href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="Ведомость_поставщиков.xlsx">📥 Скачать Excel-файл</a>'

    return href

    # Функция удалена, т.к. tkinter не доступен в окружении

def save_map_screenshot(html_content, width=1200, height=800):
    """Сохраняет HTML-версию карты для скачивания"""
    try:
        # Кодируем HTML в base64 для скачивания
        b64 = base64.b64encode(html_content.encode()).decode()
        href = f'<a href="data:text/html;charset=utf-8;base64,{b64}" download="transport_map.html">📥 Скачать HTML карты</a>'
        st.markdown(href, unsafe_allow_html=True)

        # Дополнительная информация для пользователя
        st.info("Сохраните карту и откройте файл в любом браузере для просмотра интерактивной карты.")

        return True
    except Exception as e:
        log_error(f"Ошибка при сохранении карты: {str(e)}")
        return False

# --- Отображение результатов ---
st.header("📋 Ведомость доставки материалов")

if st.session_state.delivery_data:
    df = pd.DataFrame(st.session_state.delivery_data)
    columns_to_show = [
        "№ п/п",
        "Наименование материала",
        "% от общей потребности",
        "Вид работ",
        "Наименование поставщика",
        "Адрес",
        "Вид \"франко\" для данного материала",
        "Железнодорожные перевозки %",
        "Станции назначения, на которую прибывает материал",
        "Расстояние перевозки, км",
        "Автомобильные перевозки %",
        "Средняя дальность возки, км"
    ]
    st.dataframe(df[columns_to_show], use_container_width=True)

    # Кнопка экспорта в Excel
    excel_href = export_to_excel(df, columns_to_show)
    st.markdown(excel_href, unsafe_allow_html=True)

    # --- Карта ---
    st.header("🗺️ Транспортная схема доставки")
    first_obj = st.session_state.delivery_data[0]
    m = folium.Map(location=first_obj["object_coords"], zoom_start=10)

    # Объект - теперь маленькая красная точка
    folium.CircleMarker(
        first_obj["object_coords"],
        radius=5,  # Маленький радиус
        color="red",
        fill=True,
        fill_opacity=1.0,
        popup="Место размещения объекта",
        tooltip="Объект"
    ).add_to(m)

    # Поставщики и маршруты
    for record in st.session_state.delivery_data:
        sup_coords = record["supplier_coords"]
        color = record["Цвет"]
        idx = record["№ п/п"]

        # Убрали стандартный маркер поставщика, оставляем только номер

        # Номер поставщика с попапом информации
        folium.Marker(
            sup_coords,
            popup=f"№{idx}: {record['Наименование поставщика']}",
            tooltip=f"Поставщик №{idx}",
            icon=folium.DivIcon(html=f"""
            <div style="
                background: {color};
                color: white;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                text-align: center;
                line-height: 24px;
                font-weight: bold;
                font-size: 14px;
                box-shadow: 1px 1px 3px rgba(0,0,0,0.4);
            ">{idx}</div>""")
        ).add_to(m)

        # Маршрут
        route_coords = record.get("route_coords")
        if route_coords:
            folium.PolyLine(
                locations=route_coords,
                weight=5,
                color=color,
                opacity=0.8,
                tooltip=f"{record['Наименование материала']} → {record['Расстояние перевозки, км']} км (по дорогам)"
            ).add_to(m)
        else:
            # Резерв — прямая
            folium.PolyLine(
                locations=[sup_coords, record["object_coords"]],
                weight=3,
                color=color,
                dash_array="10",
                opacity=0.6,
                tooltip=f"{record['Наименование материала']} → {record['Расстояние перевозки, км']} км (по прямой)"
            ).add_to(m)

    # Сохраняем объект карты в session_state для доступа к HTML
    folium_map = st_folium(m, width="100%", height=600, returned_objects=["last_object_clicked"])

    # Добавляем кнопки экспорта и скриншота
    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 Сохранить карту"):
            # Получаем HTML карты
            map_html = m._repr_html_()
            save_map_screenshot(map_html)
            st.success("✅ Ссылка для скачивания карты создана!")

    with col2:
        # Очистка
        if st.button("🗑️ Очистить все данные"):
            log_info("Очистка всех данных")
            st.session_state.delivery_data = []
            st.session_state.geocode_cache = {}
            st.rerun()

else:
    st.info("Добавьте поставщиков, чтобы увидеть ведомость и транспортную схему.")

# --- Статистика в подвале ---
if st.session_state.error_log:
    error_count = len([e for e in st.session_state.error_log if e['type'] in ['ERROR', 'API_ERROR']])
    warning_count = len([e for e in st.session_state.error_log if e['type'] == 'WARNING'])

    if error_count > 0 or warning_count > 0:
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Ошибки", error_count)
        with col2:
            st.metric("Предупреждения", warning_count)
        with col3:
            st.metric("Всего событий", len(st.session_state.error_log))