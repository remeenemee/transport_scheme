import time
import random
import traceback
from datetime import datetime
from geopy.geocoders import Nominatim
from tenacity import retry, stop_after_attempt, wait_fixed
import openrouteservice
from openrouteservice import convert
from geopy.distance import geodesic

# --- Функции для логирования ---
def log_error(session_state, message, error_type="ERROR", details=None):
    """Добавляет ошибку в лог с временной меткой"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    error_entry = {
        "time": timestamp,
        "type": error_type,
        "message": message,
        "details": details if details else ""
    }
    session_state.error_log.append(error_entry)
    # Ограничиваем размер лога (последние 50 записей)
    if len(session_state.error_log) > 50:
        session_state.error_log = session_state.error_log[-50:]

def log_info(session_state, message):
    """Добавляет информационное сообщение в лог"""
    log_error(session_state, message, "INFO")

def log_warning(session_state, message, details=None):
    """Добавляет предупреждение в лог"""
    log_error(session_state, message, "WARNING", details)

def log_api_error(session_state, api_name, error, details=None):
    """Специальная функция для логирования ошибок API"""
    error_message = f"Ошибка API {api_name}: {str(error)}"
    full_details = f"Подробности: {details}\nТрассировка: {traceback.format_exc()}" if details else traceback.format_exc()
    log_error(session_state, error_message, "API_ERROR", full_details)

# --- Словари ---
MATERIAL_COLORS = {
    "Асфальтобетон": "black",
    "Песок, щебень, грунт": "brown",
    "Трубопроводы": "blue",
    "Металлопрокатные изделия": "red",
    "Бетон": "gray"
}

# Доступные цвета для выбора пользователем
AVAILABLE_COLORS = {
    "Чёрный": "black", 
    "Коричневый": "brown", 
    "Синий": "blue", 
    "Красный": "red", 
    "Серый": "gray", 
    "Зелёный": "green", 
    "Оранжевый": "orange", 
    "Фиолетовый": "purple", 
    "Жёлтый": "yellow", 
    "Голубой": "lightblue"
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
def geocode_address(session_state, address):
    user_agent = f"transport_app_{random.randint(1000, 9999)}"
    geolocator = Nominatim(user_agent=user_agent)
    try:
        log_info(session_state, f"Запрос геокодирования для адреса: {address}")
        time.sleep(1.5 + random.uniform(0.5, 1.0))
        location = geolocator.geocode(address, timeout=10)
        if location:
            log_info(session_state, f"Геокодирование успешно: {location.address}")
            return (location.latitude, location.longitude), location.address
        else:
            log_warning(session_state, f"Геокодирование не дало результатов для адреса: {address}")
            return None, None
    except Exception as e:
        log_api_error(session_state, "Nominatim", e, f"Адрес: {address}")
        return None, None

def geocode_address_cached(session_state, address):
    normalized = normalize_address(address)
    if normalized in session_state.geocode_cache:
        log_info(session_state, f"Использование кэшированных координат для: {normalized}")
        return session_state.geocode_cache[normalized]
    coords, full_addr = geocode_address(session_state, normalized)
    session_state.geocode_cache[normalized] = (coords, full_addr)
    return coords, full_addr

# --- Инициализация клиента OpenRouteService ---
def init_ors_client(session_state, api_key=None):
    try:
        # Используем переданный ключ или берем из session_state
        if api_key:
            ors_key = api_key
        elif session_state.ors_api_key:
            ors_key = session_state.ors_api_key
        else:
            return None

        ors_client = openrouteservice.Client(key=ors_key)
        log_info(session_state, "Подключение к OpenRouteService успешно")
        return ors_client
    except Exception as e:
        log_api_error(session_state, "OpenRouteService", e, "Ошибка инициализации клиента")
        return None

def get_route_ors(session_state, ors_client, origin_coords, destination_coords):
    """
    origin_coords: (lat, lon)
    destination_coords: (lat, lon)
    Возвращает: маршрут (список координат), расстояние в км
    """
    try:
        log_info(session_state, f"Запрос маршрута ORS от {origin_coords} до {destination_coords}")
        coords = [(origin_coords[1], origin_coords[0]), (destination_coords[1], destination_coords[0])]

        # Подробное логирование запроса
        log_info(session_state, f"Параметры запроса ORS: coordinates={coords}, profile='driving-car'")

        # Убираем некорректный параметр extra_info
        result = ors_client.directions(
            coordinates=coords,
            profile='driving-car',
            format='geojson'
            # Убрали: extra_info=['total_distance'] - этот параметр вызывает ошибку 2003
        )

        log_info(session_state, "Получен успешный ответ от ORS API")

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

        log_info(session_state, f"Маршрут построен успешно, расстояние: {distance_km} км, точек: {len(route_coords)}")
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

        log_api_error(session_state, "OpenRouteService", e, error_details)

        # Резерв: расстояние по прямой
        try:
            dist = round(geodesic(origin_coords, destination_coords).kilometers, 2)
            log_warning(session_state, f"Используется расчёт по прямой: {dist} км", "Ошибка ORS API")
            return None, dist
        except Exception as fallback_error:
            log_api_error(session_state, "Geopy", fallback_error, "Ошибка при расчёте расстояния по прямой")
            return None, 0
