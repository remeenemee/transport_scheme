import streamlit as st
from utils import log_info

def display_debug_button():
    """Отображает кнопку для вызова панели отладки"""
    if st.button("🐛 Панель отладки"):
        st.session_state.show_debug = True

def display_debug_sidebar(session_state):
    """Отображает панель отладки в боковой панели"""
    with st.sidebar:
        st.header("🐛 Панель отладки")

        # Кнопка закрытия панели отладки
        if st.button("❌ Закрыть панель отладки"):
            st.session_state.show_debug = False
            st.rerun()

        # Переключатель режима отладки
        debug_mode = st.checkbox("Показать детальные логи", value=session_state.debug_mode)
        session_state.debug_mode = debug_mode

        # Кнопки управления логом
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Очистить лог"):
                session_state.error_log = []
                st.rerun()

        with col2:
            if st.button("📋 Экспорт лога"):
                if session_state.error_log:
                    log_text = "\n".join([
                        f"[{entry['time']}] {entry['type']}: {entry['message']}"
                        + (f"\n{entry['details']}" if entry['details'] else "")
                        for entry in session_state.error_log
                    ])
                    st.text_area("Экспорт лога ошибок", log_text, height=200)

        # Отображение лога ошибок
        st.subheader("📋 Лог событий")

        if session_state.error_log:
            # Фильтрация по типам сообщений
            filter_types = st.multiselect(
                "Фильтр по типам:",
                ["ERROR", "API_ERROR", "WARNING", "INFO"],
                default=["ERROR", "API_ERROR", "WARNING"] if not debug_mode else ["ERROR", "API_ERROR", "WARNING", "INFO"]
            )

            filtered_log = [entry for entry in session_state.error_log if entry['type'] in filter_types]

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

def display_error_stats(session_state):
    """Отображает статистику ошибок в нижней части страницы"""
    # Показываем статистику только если включена панель отладки
    if session_state.show_debug and session_state.error_log:
        error_count = len([e for e in session_state.error_log if e['type'] in ['ERROR', 'API_ERROR']])
        warning_count = len([e for e in session_state.error_log if e['type'] == 'WARNING'])

        if error_count > 0 or warning_count > 0:
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Ошибки", error_count)
            with col2:
                st.metric("Предупреждения", warning_count)
            with col3:
                st.metric("Всего событий", len(session_state.error_log))
