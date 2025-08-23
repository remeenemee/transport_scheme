import io
import base64
import pandas as pd

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

def save_map_screenshot(html_content, width=1200, height=800):
    """Сохраняет HTML-версию карты для скачивания"""
    try:
        # Кодируем HTML в base64 для скачивания
        b64 = base64.b64encode(html_content.encode()).decode()
        href = f'<a href="data:text/html;charset=utf-8;base64,{b64}" download="transport_map.html">📥 Скачать HTML карты</a>'
        return href
    except Exception as e:
        return None
