from datetime import date

import pandas as pd
import pytest

import report

XLSX = "demo_data/demo_shop.xlsx"


@pytest.fixture
def data():
    sales = pd.read_excel(XLSX, sheet_name="Продажи")
    stock = pd.read_excel(XLSX, sheet_name="Остатки")
    return report.prepare(sales, stock)


@pytest.mark.parametrize("raw, expected", [
    ("04.11.2026", date(2026, 11, 4)),
    ("11/4/2026", date(2026, 11, 4)),
    ("2026-11-04", date(2026, 11, 4)),
    ("04.11.2026 0:00:00", date(2026, 11, 4)),
])
def test_parse_date(raw, expected):
    assert report.parse_date(raw) == expected


def test_prepare_handles_russian_numbers():
    sales = pd.DataFrame({"Дата": ["01.11.2026"], "Товар": ["A"], "Количество": ["2"], "Сумма": ["1 290,50"]})
    stock = pd.DataFrame({"Товар": ["A"], "Остаток": ["5"]})
    s, st = report.prepare(sales, stock)
    assert s["Сумма"].iloc[0] == 1290.5 and st["Остаток"].iloc[0] == 5


def test_shift_to_yesterday(data):
    sales, _ = data
    shifted = report.shift_to_yesterday(sales, date(2027, 3, 10))
    assert max(shifted["Дата"]) == date(2027, 3, 9)
    assert len(shifted) == len(sales)


def test_build_and_format(data):
    sales, stock = data
    day = max(sales["Дата"])
    r = report.build_report(sales, stock, day, 1_800_000, 10)
    assert r.revenue > 0 and r.orders > 0
    assert len(r.top_products) == 3
    assert [n for n, _ in r.low_stock] == ["Солнцезащитный крем SPF 50", "Крем для лица 50 мл", "Маска тканевая (5 шт.)"]
    text = report.format_report(r)
    assert "Отчёт за" in text and "План месяца" in text and "Заканчиваются" in text
    assert len(text) < 1024  # влезает в подпись к фото


def test_chart_is_png(data):
    sales, _ = data
    png = report.revenue_chart(sales, max(sales["Дата"]))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_stock_message(data):
    _, stock = data
    assert "3 шт." in report.format_stock(stock, 10)
    assert "Все товары в наличии" in report.format_stock(stock, 1)
