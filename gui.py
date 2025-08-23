import streamlit as st
import subprocess

def main():
    st.set_page_config(page_title="Выбор метода добавления данных", page_icon="🚚", layout="centered")
    st.title("🚚 Выбор метода добавления поставщиков")
    st.markdown("""
        Добро пожаловать в модуль управления транспортной схемой! 
        Выберите один из методов добавления поставщиков:
    """)

    # Разделение на две колонки для кнопок
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("➕ Добавить вручную")
        st.markdown("""
            Используйте этот метод, если хотите добавить поставщиков, вводя данные вручную.
        """)
        if st.button("Перейти к добавлению вручную"):
            # Запуск streamlit_app.py
            subprocess.Popen(["streamlit", "run", "streamlit_app.py"])

    with col2:
        st.subheader("📂 Добавить из базы")
        st.markdown("""
            Используйте этот метод, если хотите загрузить поставщиков из базы данных.
        """)
        if st.button("Перейти к добавлению из базы"):
            # Запуск supplier.py
            subprocess.Popen(["streamlit", "run", "supplier.py"])

    # Информация о текущем выборе
    st.markdown("---")
    st.info("Выберите метод добавления, чтобы продолжить.")

if __name__ == "__main__":
    main()
