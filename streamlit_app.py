import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
from PIL import Image
import os

# Импортируем наши модули
from utils import (
    log_error, log_info, log_warning, log_api_error, 
    geocode_address_cached, init_ors_client, get_route_ors,
    MATERIAL_COLORS, AVAILABLE_COLORS, MATERIALS
)
from export_utils import export_to_excel, save_map_screenshot
from debug_ui import display_debug_sidebar, display_error_stats

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

    # Отображение панели отладки
    if 'show_debug' not in st.session_state:
        st.session_state.show_debug = False

if 'ors_api_key' not in st.session_state:
    st.session_state.ors_api_key = ""
    # Пробуем получить API ключ из secrets
    try:
        if 'api_keys' in st.secrets and 'ors_api_key' in st.secrets['api_keys']:
            st.session_state.ors_api_key = st.secrets['api_keys']['ors_api_key']
            log_info(st.session_state, "API ключ получен из secrets")
    except Exception as e:
        log_warning(st.session_state, "Не удалось получить API ключ из secrets")

# Получаем клиент ORS если API-ключ уже установлен
ors_client = init_ors_client(st.session_state)

# --- Интерфейс ---
st.title("🚚 Транспортная схема доставки материалов")

# Добавляем большую кнопку для ссылки на GitHub репозиторий
col1, col2 = st.columns([3, 1])
with col2:
    st.link_button(
        "Ссылка на github",
        "https://github.com/remeenemee/transport_scheme",
        use_container_width=True,
        type="primary"
    )

# Добавляем кнопку справки
with st.expander("📘 Инструкция по использованию"):
    st.markdown("""
    ## 📋 Пошаговая инструкция

    ### 1️⃣ Выберите наименование материала
    - В выпадающем списке выберите тип материала или введите свое название
    - Отметьте галочку "Использовать собственное наименование материала", если нужного материала нет в списке

    ### 1.1️⃣ Выберите цвет линии маршрута
    - Выберите один из 10 доступных цветов для отображения маршрута на карте
    - Цвет будет использован для линии маршрута на карте и в легенде

    ### 2️⃣ Опишите вид работ
    - Укажите, для каких работ используется материал
    - **Примеры**: Устройство дорожной одежды, монтаж трубопровода

    ### 3️⃣ Укажите наименование поставщика
    - Введите полное название организации

    ### 4️⃣ Укажите адрес поставщика
    - **Текстом**: в формате ГОРОД, УЛИЦА, ДОМ
    - **Координатами**: активируйте чекбокс "Ввести координаты поставщика вручную"

    ### 5️⃣ Укажите адрес объекта проектирования
    - Место доставки материалов (строительная площадка)

    ### 6️⃣ Нажмите "➕ Добавить поставщика"
    - Программа автоматически рассчитает маршрут и расстояние

    > 💡 **Совет**: Для точного определения координат используйте Google или Яндекс Карты
    """)

    st.markdown("""
    ## 💾 Экспорт данных

    - **📥 Excel**: Нажмите "📥 Скачать Excel-файл"
    - **🗺️ Карта**: Нажмите "💾 Сохранить карту" и скачайте HTML-файл
    """)

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
                    ors_client = init_ors_client(st.session_state, api_key)
                    st.success("✅ API-ключ установлен успешно!")
                    st.rerun()
                except Exception as e:
                    log_api_error(st.session_state, "OpenRouteService", e, "Ошибка при проверке API-ключа")
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
display_debug_sidebar(st.session_state)

# --- Основной интерфейс ---
if 'page' not in st.session_state:
    st.session_state.page = "manual"  # Устанавливаем страницу по умолчанию

if st.session_state.page == "manual":
    st.header("➕ Добавление поставщиков вручную")

    col1, col2 = st.columns(2)

    with col1:
        use_custom_material = st.checkbox("Использовать собственное наименование материала", key="custom_mat_check")

        if use_custom_material:
            material = st.text_input("Наименование материала", key="custom_mat")
        else:
            material = st.selectbox("Наименование материала", MATERIALS, key="mat")

        color_name = st.selectbox("Цвет линии маршрута", list(AVAILABLE_COLORS.keys()), key="color_select")
        selected_color = AVAILABLE_COLORS[color_name]

        # Предпросмотр выбранного цвета
        st.markdown(f"<div style='background-color: {selected_color}; width: 100%; height: 20px; border-radius: 5px;'></div>", unsafe_allow_html=True)

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
        log_info(st.session_state, "Начало процесса добавления поставщика")

        # Геокодирование объекта
        if use_object_coords:
            try:
                lat, lon = map(float, [x.strip() for x in obj_coord_input.split(",")])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    obj_coords = (lat, lon)
                    obj_full_addr = f"Координаты: {lat:.5f}, {lon:.5f}"
                    log_info(st.session_state, f"Введены координаты объекта вручную: {obj_coords}")
                else:
                    error_msg = "Координаты объекта вне допустимого диапазона."
                    log_error(st.session_state, error_msg)
                    st.error(error_msg)
                    st.stop()
            except Exception as e:
                error_msg = "Некорректный формат координат объекта"
                log_error(st.session_state, error_msg, details=str(e))
                st.error("Введите корректные координаты объекта: например, 54.7100, 20.4800")
                st.stop()
        else:
            obj_coords, obj_full_addr = geocode_address_cached(st.session_state, object_address)
            if obj_coords is None:
                error_msg = f"Не удалось определить координаты объекта: {object_address}"
                log_error(st.session_state, error_msg)
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
                    log_info(st.session_state, f"Введены координаты поставщика вручную: {sup_coords}")
                else:
                    error_msg = "Координаты поставщика вне допустимого диапазона."
                    log_error(st.session_state, error_msg)
                    st.error(error_msg)
                    st.stop()
            except Exception as e:
                error_msg = "Некорректный формат координат поставщика"
                log_error(st.session_state, error_msg, details=str(e))
                st.error("Введите корректные координаты поставщика: например, 54.7100, 20.4800")
                st.stop()
        else:
            sup_coords, sup_full_addr = geocode_address_cached(st.session_state, supplier_address)
            if sup_coords is None:
                error_msg = f"Не удалось определить координаты поставщика: {supplier_address}"
                log_error(st.session_state, error_msg)
                st.error("Не удалось определить координаты поставщика. Проверьте адрес или введите координаты вручную.")
                st.stop()

        # Расчёт маршрута по дорогам
        log_info(st.session_state, "Начало расчёта маршрута")
        route_coords, road_distance = get_route_ors(st.session_state, ors_client, sup_coords, obj_coords)

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
            "Цвет": selected_color,
            "supplier_coords": sup_coords,
            "object_coords": obj_coords,
            "route_coords": route_coords
        })

        log_info(st.session_state, f"Поставщик добавлен успешно: {supplier_name}, расстояние: {road_distance} км")

        success_msg = f"✅ Поставщик «{supplier_name}» добавлен! Расстояние "
        if route_coords:
            success_msg += f"по дорогам: {road_distance} км"
        else:
            success_msg += f"по прямой: {road_distance} км (маршрут по дорогам недоступен)"

        st.success(success_msg)

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

    # --- Легенда материалов ---
    # Создаем уникальный список материалов и их цветов
    materials_used = []
    colors_used = []

    for record in st.session_state.delivery_data:
        material_name = record["Наименование материала"]
        color = record["Цвет"]

        # Проверяем, есть ли уже такая пара материал-цвет
        material_color_pair = (material_name, color)
        if material_color_pair not in zip(materials_used, colors_used):
            materials_used.append(material_name)
            colors_used.append(color)

    # Проверяем, есть ли данные для отображения
    if materials_used:
        # Отображаем заголовок условных обозначений
        st.subheader("📋 Условные обозначения")

        # Отображаем каждый материал в отдельной строке (в один столбец)
        for material, color in zip(materials_used, colors_used):
            # Создаем строку с цветным прямоугольником и названием материала
            st.markdown(
                f"<div style='display: flex; align-items: center; margin-bottom: 10px;'>"
                f"<div style='background-color: {color}; width: 30px; height: 10px; margin-right: 10px;'></div>"
                f"<div>{material}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
    else:
        # Если нет данных, показываем пустой контейнер
        st.info("Добавьте поставщиков для отображения условных обозначений")

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
            href = save_map_screenshot(map_html)
            if href:
                st.markdown(href, unsafe_allow_html=True)
                st.info("Сохраните карту и откройте файл в любом браузере для просмотра интерактивной карты.")
                st.success("✅ Ссылка для скачивания карты создана!")
            else:
                st.error("Не удалось создать ссылку для скачивания карты")
                log_error(st.session_state, "Ошибка при создании ссылки для скачивания карты")

    with col2:
        # Очистка
        if st.button("🗑️ Очистить все данные"):
            log_info(st.session_state, "Очистка всех данных")
            st.session_state.delivery_data = []
            st.session_state.geocode_cache = {}
            st.rerun()

else:
    st.info("Добавьте поставщиков, чтобы увидеть ведомость и транспортную схему.")

    # --- Статистика в подвале (только если включен режим отладки) ---
    display_error_stats(st.session_state)

# --- Статистика в подвале ---
display_error_stats(st.session_state)