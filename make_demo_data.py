"""Генерирует демо-таблицу вымышленного магазина косметики: demo_data/demo_shop.xlsx.

Её нужно загрузить в Google Диск и открыть как Google Таблицу.
"""
import random
from datetime import date, timedelta

import pandas as pd

random.seed(42)

PRODUCTS = {
    "Крем для лица 50 мл": 1290,
    "Сыворотка с витамином C": 1890,
    "Гель для умывания": 690,
    "Тоник увлажняющий": 790,
    "Маска тканевая (5 шт.)": 590,
    "Бальзам для губ": 390,
    "Солнцезащитный крем SPF 50": 1490,
    "Патчи для глаз": 990,
    "Мицеллярная вода 400 мл": 650,
    "Пенка для снятия макияжа": 850,
}
WEIGHTS = [14, 9, 12, 8, 10, 15, 6, 9, 11, 6]

end = date(2026, 11, 4)
rows = []
for i in range(90):
    d = end - timedelta(days=89 - i)
    weekday_boost = 1.25 if d.weekday() >= 5 else 1.0
    trend = 1 + i * 0.003
    n_orders = max(5, int(random.gauss(38, 6) * weekday_boost * trend))
    for _ in range(n_orders):
        product = random.choices(list(PRODUCTS), weights=WEIGHTS)[0]
        qty = random.choices([1, 2, 3], weights=[70, 22, 8])[0]
        rows.append({"Дата": d.strftime("%d.%m.%Y"), "Товар": product, "Количество": qty,
                     "Сумма": PRODUCTS[product] * qty})

sales = pd.DataFrame(rows)
stock = pd.DataFrame({
    "Товар": list(PRODUCTS),
    "Остаток": [4, 23, 41, 17, 8, 56, 3, 29, 35, 12],
})

with pd.ExcelWriter("demo_data/demo_shop.xlsx") as xw:
    sales.to_excel(xw, sheet_name="Продажи", index=False)
    stock.to_excel(xw, sheet_name="Остатки", index=False)
print(f"Продаж: {len(sales)}, дней: 90, средняя выручка в день: {sales['Сумма'].sum() / 90:,.0f} ₽")
