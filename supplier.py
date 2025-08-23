import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
import os
from geopy.distance import geodesic
from utils import (
    log_error, log_info, log_warning, log_api_error,
    geocode_address_cached, init_ors_client, get_route_ors,
    MATERIAL_COLORS, AVAILABLE_COLORS, MATERIALS
)
from export_utils import export_to_excel, save_map_screenshot
import tkinter as tk
from tkinter import filedialog

# --- Настройка страницы ---
st.set_page_config(layout="wide", page_title="Модуль программы для работы с базой поставщиков", page_icon="🏭")

# --- Инициализация сессии ---
if 'delivery_data' not in st.session_state:
    st.session_state.delivery_data = []

if 'geocode_cache' not in st.session_state:
    st.session_state.geocode_cache = {}

if 'error_log' not in st.session_state:
    st.session_state.error_log = []

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

# Инициализация выбранного поставщика для карты
if 'selected_suppliers' not in st.session_state:
    st.session_state.selected_suppliers = []

if 'object_coords' not in st.session_state:
    st.session_state.object_coords = None

if 'object_address' not in st.session_state:
    st.session_state.object_address = ""

if 'suppliers_df' not in st.session_state:
    st.session_state.suppliers_df = None

if 'filtered_suppliers' not in st.session_state:
    st.session_state.filtered_suppliers = None

if 'selected_okved' not in st.session_state:
    st.session_state.selected_okved = None

# --- Заголовок страницы ---
st.title("Модуль программы для работы с базой поставщиков")

# Функция для загрузки поставщиков из CSV файла
def load_suppliers():
    try:
        # Открываем окно выбора файла
        root = tk.Tk()
        root.withdraw()  # Скрываем главное окно Tkinter
        file_path = filedialog.askopenfilename(
            title="Выберите файл базы данных (CSV)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not file_path:
            st.warning("⚠️ Файл не выбран. Пожалуйста, выберите файл базы данных.")
            return None, []

        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            # Обработка данных
            df = df.fillna('')
            # Извлечение координат
            df['lat'] = 0.0
            df['lon'] = 0.0

            # Парсинг координат из столбца G ("Координаты")
            for idx, row in df.iterrows():
                if row['Координаты'] and isinstance(row['Координаты'], str):
                    try:
                        lat, lon = map(float, row['Координаты'].split(','))
                        df.at[idx, 'lat'] = lat
                        df.at[idx, 'lon'] = lon
                    except:
                        pass

            # Создаем информационное поле
            df['info'] = df.apply(lambda row: f"{row['Название компании']}\nИНН: {row['ИНН']}\nАдрес: {row['Адрес компании']}", axis=1)

            # Извлечение уникальных ОКВЭД для фильтрации
            okved_list = df['Главный ОКВЭД (название)'].unique().tolist()
            okved_list = [x for x in okved_list if x]
            okved_list.sort()

            log_info(st.session_state, f"Загружено {len(df)} поставщиков из CSV файла")

            return df, okved_list
        else:
            log_error(st.session_state, f"Файл {file_path} не найден")
            st.error("❌ Указанный файл не найден. Проверьте путь и попробуйте снова.")
            return None, []
    except Exception as e:
        log_error(st.session_state, f"Ошибка при загрузке CSV файла: {str(e)}")
        st.error(f"❌ Ошибка при загрузке файла: {str(e)}")
        return None, []

# Обработчик выбора поставщика на карте
def handle_supplier_click(clicked_point):
    if clicked_point and st.session_state.object_coords and st.session_state.filtered_suppliers is not None:
        # Получаем координаты клика
        lat, lon = clicked_point['lat'], clicked_point['lng']

        # Находим ближайшего поставщика из фильтрованного списка
        closest_supplier = None
        min_distance = float('inf')

        for idx, row in st.session_state.filtered_suppliers.iterrows():
            supplier_coords = (row['lat'], row['lon'])
            click_coords = (lat, lon)

            # Расчет расстояния от клика до поставщика
            distance = geodesic(click_coords, supplier_coords).kilometers

            # Если это ближайший поставщик к клику
            if distance < min_distance and distance < 10:  # Порог в 10 км
                min_distance = distance
                closest_supplier = row

        # Если нашли поставщика в радиусе клика
        if closest_supplier is not None:
            # Проверяем, что этот поставщик еще не выбран
            supplier_name = closest_supplier['Название компании']
            already_selected = any(s['Название компании'] == supplier_name for s in st.session_state.selected_suppliers)

            if not already_selected:
                # Расчет маршрута по дорогам
                supplier_coords = (closest_supplier['lat'], closest_supplier['lon'])
                route_coords, road_distance = get_route_ors(
                    st.session_state,
                    ors_client,
                    supplier_coords,
                    st.session_state.object_coords
                )

                # Создаем запись для выбранного поставщика
                # Используем цвет, выбранный пользователем в интерфейсе
                color_name = st.session_state.get('color_select', "Синий")
                selected_color = AVAILABLE_COLORS[color_name]

                # Формирование полного адреса
                obj_full_addr = f"Координаты: {st.session_state.object_coords[0]:.5f}, {st.session_state.object_coords[1]:.5f}"
                if st.session_state.object_address:
                    obj_full_addr = st.session_state.object_address

                # Сохраняем информацию о выбранном поставщике
                idx = len(st.session_state.delivery_data) + 1

                # Запись для добавления в ведомость поставщиков
                supplier_data = {
                    "№ п/п": idx,
                    "Наименование материала": closest_supplier['Главный ОКВЭД (название)'],
                    "% от общей потребности": 100,
                    "Вид работ": "Поставка материалов",
                    "Наименование поставщика": f"{closest_supplier['Название компании']} (ИНН: {closest_supplier['ИНН']})",
                    "Адрес": closest_supplier['Адрес компании'],
                    "Вид \"франко\" для данного материала": "-",
                    "Железнодорожные перевозки %": "-",
                    "Станции назначения, на которую прибывает материал": obj_full_addr,
                    "Расстояние перевозки, км": road_distance,
                    "Автомобильные перевозки %": 100,
                    "Средняя дальность возки, км": road_distance,
                    "Цвет": selected_color,
                    "supplier_coords": supplier_coords,
                    "object_coords": st.session_state.object_coords,
                    "route_coords": route_coords,
                    "ИНН": closest_supplier['ИНН']
                }

                # Добавляем данные о поставщике в сессию
                st.session_state.delivery_data.append(supplier_data)
                st.session_state.selected_suppliers.append({
                    "Название компании": closest_supplier['Название компании'],
                    "Координаты": supplier_coords,
                    "Маршрут": route_coords,
                    "Расстояние": road_distance,
                    "ОКВЭД": closest_supplier['Главный ОКВЭД (название)'],
                    "Цвет": selected_color
                })

                log_info(st.session_state, f"Добавлен поставщик: {supplier_name}, расстояние: {road_distance} км")
                return True

    return False

# --- Основной интерфейс ---
col1, col2 = st.columns([1, 2])

with col1:
    st.header("1.Укажите объект")

    # Ввод информации об объекте
    use_object_coords = st.checkbox("Ввести координаты объекта вручную")

    if use_object_coords:
        obj_coord_input = st.text_input("Координаты объекта (широта, долгота)", "")
        if obj_coord_input:
            try:
                lat, lon = map(float, [x.strip() for x in obj_coord_input.split(",")])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    st.session_state.object_coords = (lat, lon)
                    st.session_state.object_address = f"Координаты: {lat:.5f}, {lon:.5f}"
                    st.success("✅ Координаты объекта установлены!")
                else:
                    st.error("Координаты объекта вне допустимого диапазона.")
            except Exception as e:
                st.error("Введите корректные координаты объекта: например, 54.7100, 20.4800")
    else:
        object_address = st.text_input(
            "Адрес объекта",
            value="Калининградская обл., Гурьевский район, пос. Невское, ул. Гагарина, д. ЗД. 229"
        )

        if st.button("📍 Определить координаты объекта"):
            obj_coords, obj_full_addr = geocode_address_cached(st.session_state, object_address)
            if obj_coords is None:
                st.error("Не удалось определить координаты объекта. Проверьте адрес или введите координаты вручную.")
            else:
                st.session_state.object_coords = obj_coords
                st.session_state.object_address = obj_full_addr
                st.success(f"✅ Координаты объекта определены: {obj_coords[0]:.5f}, {obj_coords[1]:.5f}")

    # Загрузка данных поставщиков
    st.header("2.Загрузите данные поставщиков")

    if st.button("📂 Загрузить CSV файл поставщиков"):
        df, okved_list = load_suppliers()
        if df is not None:
            st.session_state.suppliers_df = df
            st.success(f"✅ Загружено {len(df)} поставщиков")
        else:
            st.error("❌ Ошибка при загрузке файла поставщиков")

    # Фильтрация поставщиков по ОКВЭД
    if st.session_state.suppliers_df is not None:
        st.header("3.Выберите категорию поставщиков")

        # Получение списка уникальных ОКВЭД
        okved_list = st.session_state.suppliers_df['Главный ОКВЭД (название)'].unique().tolist()
        okved_list = [x for x in okved_list if x]
        okved_list.sort()

        # Выбор ОКВЭД
        okved_list.insert(0, "Ничего")  # Добавляем опцию "Ничего" в начало списка
        selected_okved = st.selectbox(
            "Выберите ОКВЭД поставщиков",
            okved_list,
            index=0,  # Устанавливаем "Ничего" как значение по умолчанию
            placeholder="Выберите категорию..."
        )

        if selected_okved:
            # Фильтрация поставщиков по выбранному ОКВЭД
            filtered_df = st.session_state.suppliers_df[
                st.session_state.suppliers_df['Главный ОКВЭД (название)'] == selected_okved
            ]

            st.session_state.filtered_suppliers = filtered_df
            st.session_state.selected_okved = selected_okved

            st.success(f"✅ Найдено {len(filtered_df)} поставщиков по ОКВЭД: {selected_okved}")

            # Подсказка о взаимодействии с картой
            st.info("ℹ️ Нажмите на точку поставщика на карте, чтобы добавить его в ведомость")
        else:
            st.session_state.filtered_suppliers = None
            st.session_state.selected_okved = None
            st.warning("⚠️ Выберите категорию поставщиков")

    # Выбор цвета маршрута
    if st.session_state.filtered_suppliers is not None:
        st.header("4.Выберите цвет маршрута")

        color_name = st.selectbox("Цвет линии маршрута", list(AVAILABLE_COLORS.keys()), key="color_select")
        selected_color = AVAILABLE_COLORS[color_name]

        # Предпросмотр выбранного цвета
        st.markdown(f"<div style='background-color: {selected_color}; width: 100%; height: 20px; border-radius: 5px;'></div>", unsafe_allow_html=True)

with col2:
    # Отображение карты
    st.header("Карта поставщиков")

    # Проверка наличия API-ключа для построения маршрутов
    if not st.session_state.ors_api_key:
        st.warning("⚠️ API-ключ OpenRouteService не установлен. Маршруты будут рассчитаны по прямой линии. Используйте панель 'Ввести временный API-ключ для тестирования'.")

    # Если объект не задан, показываем сообщение
    if st.session_state.object_coords is None:
        st.warning("⚠️ Сначала укажите координаты объекта")
    elif st.session_state.filtered_suppliers is None:
        st.warning("⚠️ Загрузите данные поставщиков и выберите ОКВЭД")
    else:
        # Создаем карту
        m = folium.Map(location=st.session_state.object_coords, zoom_start=10)

        # Добавляем объект - маленькая красная точка
        folium.CircleMarker(
            st.session_state.object_coords,
            radius=10,  # Маленький радиус
            color="red",
            fill=True,
            fill_opacity=1.0,
            popup=folium.Popup("Объект", max_width=200),
            tooltip="Объект"

        ).add_to(m)

        # Добавляем поставщиков из отфильтрованного списка
        for idx, row in st.session_state.filtered_suppliers.iterrows():
            # Проверяем, что координаты корректные
            if row['lat'] != 0 and row['lon'] != 0:
                # Создаем всплывающую подсказку с информацией о поставщике
                popup_text = f"""<b>{row['Название компании']}</b><br>
                                ИНН: {row['ИНН']}<br>
                                ОКВЭД: {row['Главный ОКВЭД (название)']}<br>
                                Адрес: {row['Адрес компании']}"""

                # Добавляем маркер поставщика
                folium.CircleMarker(
                    [row['lat'], row['lon']],
                    popup=folium.Popup(popup_text, max_width=300),
                    tooltip=row['Название компании'],
                    radius=5,  # Маленький радиус
                    color="blue",
                    fill=True,
                    fill_opacity=1.0,
                ).add_to(m)

        # Добавляем выбранных поставщиков и маршруты
        for i, supplier in enumerate(st.session_state.selected_suppliers):
            # Получаем данные поставщика
            sup_coords = supplier['Координаты']
            idx = i + 1  # Номер поставщика

            # Выбираем цвет из доступных (для разнообразия)
            color = list(AVAILABLE_COLORS.values())[i % len(AVAILABLE_COLORS)]

            # Добавляем маркер с номером
            folium.Marker(
                sup_coords,
                popup=f"№{idx}: {supplier['Название компании']}",
                tooltip=f"Поставщик №{idx}",
                icon=folium.DivIcon(html=f"""
                <div style="
                    background: {supplier.get('Цвет', color)};
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

            # Добавляем маршрут
            route_coords = supplier['Маршрут']
            if route_coords:
                folium.PolyLine(
                    locations=route_coords,
                    weight=5,
                    color=supplier.get('Цвет', color),
                    opacity=0.8,
                    tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по дорогам)"
                ).add_to(m)
            else:
                # Резерв — прямая линия, если маршрут не определен
                folium.PolyLine(
                    locations=[sup_coords, st.session_state.object_coords],
                    weight=3,
                    color=color,
                    dash_array="10",
                    opacity=0.6,
                    tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по прямой)"
                ).add_to(m)

        # Отображаем карту с обработкой кликов
        folium_map = st_folium(
            m,
            width="100%",
            height=600,
            returned_objects=["last_object_clicked"],
            key="supplier_map"
        )

        # Обрабатываем клик по карте
        if folium_map["last_object_clicked"] is not None:
            # Пытаемся добавить поставщика при клике
            if handle_supplier_click(folium_map["last_object_clicked"]):
                st.rerun()  # Перезагружаем страницу для обновления карты

# --- Отображение результатов ---
st.header("📋 Ведомость поставщиков")

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

    # Кнопки экспорта и скриншота
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("💾 Сохранить карту"):
            # Создаем карту для экспорта
            m_export = folium.Map(location=st.session_state.object_coords, zoom_start=10)

            # Добавляем объект
            folium.CircleMarker(
                st.session_state.object_coords,
                radius=5,
                color="red",
                fill=True,
                fill_opacity=1.0,
                popup="Место размещения объекта",
                tooltip="Объект"
            ).add_to(m_export)

            # Добавляем выбранных поставщиков и маршруты
            for i, supplier in enumerate(st.session_state.selected_suppliers):
                sup_coords = supplier['Координаты']
                idx = i + 1
                color = list(AVAILABLE_COLORS.values())[i % len(AVAILABLE_COLORS)]

                # Маркер с номером
                folium.Marker(
                    sup_coords,
                    popup=f"№{idx}: {supplier['Название компании']}",
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
                ).add_to(m_export)

                # Добавляем маршрут (по дорогам или по прямой)
                route_coords = supplier.get('Маршрут')
                if route_coords:
                    folium.PolyLine(
                        locations=route_coords,
                        weight=5,
                        color=color,
                        opacity=0.8,
                        tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по дорогам)"
                    ).add_to(m_export)
                else:
                    folium.PolyLine(
                        locations=[sup_coords, st.session_state.object_coords],
                        weight=3,
                        color=color,
                        dash_array="10",
                        opacity=0.6,
                        tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по прямой)"
                    ).add_to(m_export)

            # Получаем HTML карты
            map_html = m_export._repr_html_()
            href = save_map_screenshot(map_html)
            if href:
                st.markdown(href, unsafe_allow_html=True)
                st.info("Сохраните карту и откройте файл в любом браузере для просмотра интерактивной карты.")
                st.success("✅ Ссылка для скачивания карты создана!")
            else:
                st.error("Не удалось создать ссылку для скачивания карты")

    with col2:
        # Очистка выбранных поставщиков
        if st.button("🗑️ Очистить выбранных поставщиков"):
            log_info(st.session_state, "Очистка выбранных поставщиков")
            st.session_state.delivery_data = []
            st.session_state.selected_suppliers = []
            st.rerun()

    with col3:
        # Кнопка для отключения геоточек неиспользуемых поставщиков
        if st.button("🔍 Скрыть неиспользуемые поставщики"):
            # Добавляем в selected_suppliers строку с пустыми данными
            st.session_state.selected_suppliers = [{
                "Название компании": "Ничего",
                "Координаты": None,
                "Маршрут": None,
                "Расстояние": 0,
                "ОКВЭД": "",
                "Цвет": "gray"
            }]
            st.info("✅ Показаны только выбранные поставщики. Для возврата к полной карте обновите страницу.")
            log_info(st.session_state, "Отображение карты только с выбранными поставщиками")
else:
    st.info("Выберите поставщиков на карте, чтобы сформировать ведомость.")

# --- Функция для отображения интерфейса добавления поставщиков из базы ---
def display_supplier_gui():
    st.header("📂 Добавление поставщиков из базы")

    # --- Инициализация сессии ---
    if 'delivery_data' not in st.session_state:
        st.session_state.delivery_data = []

    if 'geocode_cache' not in st.session_state:
        st.session_state.geocode_cache = {}

    if 'error_log' not in st.session_state:
        st.session_state.error_log = []

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

    # Инициализация выбранного поставщика для карты
    if 'selected_suppliers' not in st.session_state:
        st.session_state.selected_suppliers = []

    if 'object_coords' not in st.session_state:
        st.session_state.object_coords = None

    if 'object_address' not in st.session_state:
        st.session_state.object_address = ""

    if 'suppliers_df' not in st.session_state:
        st.session_state.suppliers_df = None

    if 'filtered_suppliers' not in st.session_state:
        st.session_state.filtered_suppliers = None

    if 'selected_okved' not in st.session_state:
        st.session_state.selected_okved = None

    # --- Заголовок страницы ---
    st.title("Модуль программы для работы с базой поставщиков")

    # Функция для загрузки поставщиков из CSV файла
    def load_suppliers():
        try:
            # Открываем окно выбора файла
            root = tk.Tk()
            root.withdraw()  # Скрываем главное окно Tkinter
            file_path = filedialog.askopenfilename(
                title="Выберите файл базы данных (CSV)",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )

            if not file_path:
                st.warning("⚠️ Файл не выбран. Пожалуйста, выберите файл базы данных.")
                return None, []

            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                # Обработка данных
                df = df.fillna('')
                # Извлечение координат
                df['lat'] = 0.0
                df['lon'] = 0.0

                # Парсинг координат из столбца G ("Координаты")
                for idx, row in df.iterrows():
                    if row['Координаты'] and isinstance(row['Координаты'], str):
                        try:
                            lat, lon = map(float, row['Координаты'].split(','))
                            df.at[idx, 'lat'] = lat
                            df.at[idx, 'lon'] = lon
                        except:
                            pass

                # Создаем информационное поле
                df['info'] = df.apply(lambda row: f"{row['Название компании']}\nИНН: {row['ИНН']}\nАдрес: {row['Адрес компании']}", axis=1)

                # Извлечение уникальных ОКВЭД для фильтрации
                okved_list = df['Главный ОКВЭД (название)'].unique().tolist()
                okved_list = [x for x in okved_list if x]
                okved_list.sort()

                log_info(st.session_state, f"Загружено {len(df)} поставщиков из CSV файла")

                return df, okved_list
            else:
                log_error(st.session_state, f"Файл {file_path} не найден")
                st.error("❌ Указанный файл не найден. Проверьте путь и попробуйте снова.")
                return None, []
        except Exception as e:
            log_error(st.session_state, f"Ошибка при загрузке CSV файла: {str(e)}")
            st.error(f"❌ Ошибка при загрузке файла: {str(e)}")
            return None, []

    # Обработчик выбора поставщика на карте
    def handle_supplier_click(clicked_point):
        if clicked_point and st.session_state.object_coords and st.session_state.filtered_suppliers is not None:
            # Получаем координаты клика
            lat, lon = clicked_point['lat'], clicked_point['lng']

            # Находим ближайшего поставщика из фильтрованного списка
            closest_supplier = None
            min_distance = float('inf')

            for idx, row in st.session_state.filtered_suppliers.iterrows():
                supplier_coords = (row['lat'], row['lon'])
                click_coords = (lat, lon)

                # Расчет расстояния от клика до поставщика
                distance = geodesic(click_coords, supplier_coords).kilometers

                # Если это ближайший поставщик к клику
                if distance < min_distance and distance < 10:  # Порог в 10 км
                    min_distance = distance
                    closest_supplier = row

            # Если нашли поставщика в радиусе клика
            if closest_supplier is not None:
                # Проверяем, что этот поставщик еще не выбран
                supplier_name = closest_supplier['Название компании']
                already_selected = any(s['Название компании'] == supplier_name for s in st.session_state.selected_suppliers)

                if not already_selected:
                    # Расчет маршрута по дорогам
                    supplier_coords = (closest_supplier['lat'], closest_supplier['lon'])
                    route_coords, road_distance = get_route_ors(
                        st.session_state,
                        ors_client,
                        supplier_coords,
                        st.session_state.object_coords
                    )

                    # Создаем запись для выбранного поставщика
                    # Используем цвет, выбранный пользователем в интерфейсе
                    color_name = st.session_state.get('color_select', "Синий")
                    selected_color = AVAILABLE_COLORS[color_name]

                    # Формирование полного адреса
                    obj_full_addr = f"Координаты: {st.session_state.object_coords[0]:.5f}, {st.session_state.object_coords[1]:.5f}"
                    if st.session_state.object_address:
                        obj_full_addr = st.session_state.object_address

                    # Сохраняем информацию о выбранном поставщике
                    idx = len(st.session_state.delivery_data) + 1

                    # Запись для добавления в ведомость поставщиков
                    supplier_data = {
                        "№ п/п": idx,
                        "Наименование материала": closest_supplier['Главный ОКВЭД (название)'],
                        "% от общей потребности": 100,
                        "Вид работ": "Поставка материалов",
                        "Наименование поставщика": f"{closest_supplier['Название компании']} (ИНН: {closest_supplier['ИНН']})",
                        "Адрес": closest_supplier['Адрес компании'],
                        "Вид \"франко\" для данного материала": "-",
                        "Железнодорожные перевозки %": "-",
                        "Станции назначения, на которую прибывает материал": obj_full_addr,
                        "Расстояние перевозки, км": road_distance,
                        "Автомобильные перевозки %": 100,
                        "Средняя дальность возки, км": road_distance,
                        "Цвет": selected_color,
                        "supplier_coords": supplier_coords,
                        "object_coords": st.session_state.object_coords,
                        "route_coords": route_coords,
                        "ИНН": closest_supplier['ИНН']
                    }

                    # Добавляем данные о поставщике в сессию
                    st.session_state.delivery_data.append(supplier_data)
                    st.session_state.selected_suppliers.append({
                        "Название компании": closest_supplier['Название компании'],
                        "Координаты": supplier_coords,
                        "Маршрут": route_coords,
                        "Расстояние": road_distance,
                        "ОКВЭД": closest_supplier['Главный ОКВЭД (название)'],
                        "Цвет": selected_color
                    })

                    log_info(st.session_state, f"Добавлен поставщик: {supplier_name}, расстояние: {road_distance} км")
                    return True

        return False

    # --- Основной интерфейс ---
    col1, col2 = st.columns([1, 2])

    with col1:
        st.header("1.Укажите объект")

        # Ввод информации об объекте
        use_object_coords = st.checkbox("Ввести координаты объекта вручную")

        if use_object_coords:
            obj_coord_input = st.text_input("Координаты объекта (широта, долгота)", "")
            if obj_coord_input:
                try:
                    lat, lon = map(float, [x.strip() for x in obj_coord_input.split(",")])
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        st.session_state.object_coords = (lat, lon)
                        st.session_state.object_address = f"Координаты: {lat:.5f}, {lon:.5f}"
                        st.success("✅ Координаты объекта установлены!")
                    else:
                        st.error("Координаты объекта вне допустимого диапазона.")
                except Exception as e:
                    st.error("Введите корректные координаты объекта: например, 54.7100, 20.4800")
        else:
            object_address = st.text_input(
                "Адрес объекта",
                value="Калининградская обл., Гурьевский район, пос. Невское, ул. Гагарина, д. ЗД. 229"
            )

            if st.button("📍 Определить координаты объекта"):
                obj_coords, obj_full_addr = geocode_address_cached(st.session_state, object_address)
                if obj_coords is None:
                    st.error("Не удалось определить координаты объекта. Проверьте адрес или введите координаты вручную.")
                else:
                    st.session_state.object_coords = obj_coords
                    st.session_state.object_address = obj_full_addr
                    st.success(f"✅ Координаты объекта определены: {obj_coords[0]:.5f}, {obj_coords[1]:.5f}")

        # Загрузка данных поставщиков
        st.header("2.Загрузите данные поставщиков")

        if st.button("📂 Загрузить CSV файл поставщиков"):
            df, okved_list = load_suppliers()
            if df is not None:
                st.session_state.suppliers_df = df
                st.success(f"✅ Загружено {len(df)} поставщиков")
            else:
                st.error("❌ Ошибка при загрузке файла поставщиков")

        # Фильтрация поставщиков по ОКВЭД
        if st.session_state.suppliers_df is not None:
            st.header("3.Выберите категорию поставщиков")

            # Получение списка уникальных ОКВЭД
            okved_list = st.session_state.suppliers_df['Главный ОКВЭД (название)'].unique().tolist()
            okved_list = [x for x in okved_list if x]
            okved_list.sort()

            # Выбор ОКВЭД
            okved_list.insert(0, "Ничего")  # Добавляем опцию "Ничего" в начало списка
            selected_okved = st.selectbox(
                "Выберите ОКВЭД поставщиков",
                okved_list,
                index=0,  # Устанавливаем "Ничего" как значение по умолчанию
                placeholder="Выберите категорию..."
            )

            if selected_okved:
                # Фильтрация поставщиков по выбранному ОКВЭД
                filtered_df = st.session_state.suppliers_df[
                    st.session_state.suppliers_df['Главный ОКВЭД (название)'] == selected_okved
                ]

                st.session_state.filtered_suppliers = filtered_df
                st.session_state.selected_okved = selected_okved

                st.success(f"✅ Найдено {len(filtered_df)} поставщиков по ОКВЭД: {selected_okved}")

                # Подсказка о взаимодействии с картой
                st.info("ℹ️ Нажмите на точку поставщика на карте, чтобы добавить его в ведомость")
            else:
                st.session_state.filtered_suppliers = None
                st.session_state.selected_okved = None
                st.warning("⚠️ Выберите категорию поставщиков")

        # Выбор цвета маршрута
        if st.session_state.filtered_suppliers is not None:
            st.header("4.Выберите цвет маршрута")

            color_name = st.selectbox("Цвет линии маршрута", list(AVAILABLE_COLORS.keys()), key="color_select")
            selected_color = AVAILABLE_COLORS[color_name]

            # Предпросмотр выбранного цвета
            st.markdown(f"<div style='background-color: {selected_color}; width: 100%; height: 20px; border-radius: 5px;'></div>", unsafe_allow_html=True)

    with col2:
        # Отображение карты
        st.header("Карта поставщиков")

        # Проверка наличия API-ключа для построения маршрутов
        if not st.session_state.ors_api_key:
            st.warning("⚠️ API-ключ OpenRouteService не установлен. Маршруты будут рассчитаны по прямой линии. Используйте панель 'Ввести временный API-ключ для тестирования'.")

        # Если объект не задан, показываем сообщение
        if st.session_state.object_coords is None:
            st.warning("⚠️ Сначала укажите координаты объекта")
        elif st.session_state.filtered_suppliers is None:
            st.warning("⚠️ Загрузите данные поставщиков и выберите ОКВЭД")
        else:
            # Создаем карту
            m = folium.Map(location=st.session_state.object_coords, zoom_start=10)

            # Добавляем объект - маленькая красная точка
            folium.CircleMarker(
                st.session_state.object_coords,
                radius=10,  # Маленький радиус
                color="red",
                fill=True,
                fill_opacity=1.0,
                popup=folium.Popup("Объект", max_width=200),
                tooltip="Объект"

            ).add_to(m)

            # Добавляем поставщиков из отфильтрованного списка
            for idx, row in st.session_state.filtered_suppliers.iterrows():
                # Проверяем, что координаты корректные
                if row['lat'] != 0 and row['lon'] != 0:
                    # Создаем всплывающую подсказку с информацией о поставщике
                    popup_text = f"""<b>{row['Название компании']}</b><br>
                                    ИНН: {row['ИНН']}<br>
                                    ОКВЭД: {row['Главный ОКВЭД (название)']}<br>
                                    Адрес: {row['Адрес компании']}"""

                    # Добавляем маркер поставщика
                    folium.CircleMarker(
                        [row['lat'], row['lon']],
                        popup=folium.Popup(popup_text, max_width=300),
                        tooltip=row['Название компании'],
                        radius=5,  # Маленький радиус
                        color="blue",
                        fill=True,
                        fill_opacity=1.0,
                    ).add_to(m)

            # Добавляем выбранных поставщиков и маршруты
            for i, supplier in enumerate(st.session_state.selected_suppliers):
                # Получаем данные поставщика
                sup_coords = supplier['Координаты']
                idx = i + 1  # Номер поставщика

                # Выбираем цвет из доступных (для разнообразия)
                color = list(AVAILABLE_COLORS.values())[i % len(AVAILABLE_COLORS)]

                # Добавляем маркер с номером
                folium.Marker(
                    sup_coords,
                    popup=f"№{idx}: {supplier['Название компании']}",
                    tooltip=f"Поставщик №{idx}",
                    icon=folium.DivIcon(html=f"""
                    <div style="
                        background: {supplier.get('Цвет', color)};
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

                # Добавляем маршрут
                route_coords = supplier['Маршрут']
                if route_coords:
                    folium.PolyLine(
                        locations=route_coords,
                        weight=5,
                        color=supplier.get('Цвет', color),
                        opacity=0.8,
                        tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по дорогам)"
                    ).add_to(m)
                else:
                    # Резерв — прямая линия, если маршрут не определен
                    folium.PolyLine(
                        locations=[sup_coords, st.session_state.object_coords],
                        weight=3,
                        color=color,
                        dash_array="10",
                        opacity=0.6,
                        tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по прямой)"
                    ).add_to(m)

            # Отображаем карту с обработкой кликов
            folium_map = st_folium(
                m,
                width="100%",
                height=600,
                returned_objects=["last_object_clicked"],
                key="supplier_map"
            )

            # Обрабатываем клик по карте
            if folium_map["last_object_clicked"] is not None:
                # Пытаемся добавить поставщика при клике
                if handle_supplier_click(folium_map["last_object_clicked"]):
                    st.rerun()  # Перезагружаем страницу для обновления карты

    # --- Отображение результатов ---
    st.header("📋 Ведомость поставщиков")

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

        # Кнопки экспорта и скриншота
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("💾 Сохранить карту"):
                # Создаем карту для экспорта
                m_export = folium.Map(location=st.session_state.object_coords, zoom_start=10)

                # Добавляем объект
                folium.CircleMarker(
                    st.session_state.object_coords,
                    radius=5,
                    color="red",
                    fill=True,
                    fill_opacity=1.0,
                    popup="Место размещения объекта",
                    tooltip="Объект"
                ).add_to(m_export)

                # Добавляем выбранных поставщиков и маршруты
                for i, supplier in enumerate(st.session_state.selected_suppliers):
                    sup_coords = supplier['Координаты']
                    idx = i + 1
                    color = list(AVAILABLE_COLORS.values())[i % len(AVAILABLE_COLORS)]

                    # Маркер с номером
                    folium.Marker(
                        sup_coords,
                        popup=f"№{idx}: {supplier['Название компании']}",
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
                    ).add_to(m_export)

                    # Добавляем маршрут (по дорогам или по прямой)
                    route_coords = supplier.get('Маршрут')
                    if route_coords:
                        folium.PolyLine(
                            locations=route_coords,
                            weight=5,
                            color=color,
                            opacity=0.8,
                            tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по дорогам)"
                        ).add_to(m_export)
                    else:
                        folium.PolyLine(
                            locations=[sup_coords, st.session_state.object_coords],
                            weight=3,
                            color=color,
                            dash_array="10",
                            opacity=0.6,
                            tooltip=f"{supplier['ОКВЭД']} → {supplier['Расстояние']} км (по прямой)"
                        ).add_to(m_export)

                # Получаем HTML карты
                map_html = m_export._repr_html_()
                href = save_map_screenshot(map_html)
                if href:
                    st.markdown(href, unsafe_allow_html=True)
                    st.info("Сохраните карту и откройте файл в любом браузере для просмотра интерактивной карты.")
                    st.success("✅ Ссылка для скачивания карты создана!")
                else:
                    st.error("Не удалось создать ссылку для скачивания карты")

        with col2:
            # Очистка выбранных поставщиков
            if st.button("🗑️ Очистить выбранных поставщиков"):
                log_info(st.session_state, "Очистка выбранных поставщиков")
                st.session_state.delivery_data = []
                st.session_state.selected_suppliers = []
                st.rerun()

        with col3:
            # Кнопка для отключения геоточек неиспользуемых поставщиков
            if st.button("🔍 Скрыть неиспользуемые поставщики"):
                # Добавляем в selected_suppliers строку с пустыми данными
                st.session_state.selected_suppliers = [{
                    "Название компании": "Ничего",
                    "Координаты": None,
                    "Маршрут": None,
                    "Расстояние": 0,
                    "ОКВЭД": "",
                    "Цвет": "gray"
                }]
                st.info("✅ Показаны только выбранные поставщики. Для возврата к полной карте обновите страницу.")
                log_info(st.session_state, "Отображение карты только с выбранными поставщиками")
    else:
        st.info("Выберите поставщиков на карте, чтобы сформировать ведомость.")
