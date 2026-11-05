"""Загрузка данных из Google Таблицы, расчёт показателей и график."""
from __future__ import annotations

import calendar
import html
import io
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote

import matplotlib

matplotlib.use("Agg")  # рисуем без экрана, на сервере
import matplotlib.pyplot as plt
import pandas as pd
import requests

SALES_SHEET = "Продажи"
STOCK_SHEET = "Остатки"


# ---------- загрузка ----------

def sheet_csv_url(sheet_id: str, sheet_name: str) -> str:
    """CSV-выгрузка листа по имени. Таблица должна быть открыта «для всех, у кого есть ссылка»."""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(sheet_name)}"


def _read_csv(url: str) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    if resp.text.lstrip().startswith("<"):
        raise RuntimeError("Google вернул страницу вместо данных: проверьте доступ к таблице по ссылке")
    return pd.read_csv(io.StringIO(resp.text))


def load_data(sheet_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sales = _read_csv(sheet_csv_url(sheet_id, SALES_SHEET))
    stock = _read_csv(sheet_csv_url(sheet_id, STOCK_SHEET))
    return prepare(sales, stock)


def parse_date(value) -> date:
    """Google отдаёт даты в формате локали таблицы: 04.11.2026, 11/4/2026 или 2026-11-04."""
    s = str(value).strip().split(" ")[0]
    if "." in s:
        return pd.to_datetime(s, format="%d.%m.%Y").date()
    if "/" in s:
        return pd.to_datetime(s, format="%m/%d/%Y").date()
    return pd.to_datetime(s).date()


def prepare(sales: pd.DataFrame, stock: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Приводим типы: даты — датами, суммы — числами (Google иногда отдаёт «1 290,00»)."""
    sales = sales.rename(columns=str.strip).copy()
    sales["Дата"] = sales["Дата"].map(parse_date)
    for col in ("Количество", "Сумма"):
        sales[col] = pd.to_numeric(
            sales[col].astype(str).str.replace(" ", "").str.replace(" ", "").str.replace(",", "."),
            errors="coerce",
        ).fillna(0)
    stock = stock.rename(columns=str.strip).copy()
    stock["Остаток"] = pd.to_numeric(stock["Остаток"], errors="coerce").fillna(0).astype(int)
    return sales, stock


def shift_to_yesterday(sales: pd.DataFrame, today: date) -> pd.DataFrame:
    """Демо-режим: сдвигаем даты так, чтобы последний день в таблице был «вчера».
    Тогда демо-отчёт всегда выглядит свежим, сколько бы времени ни прошло."""
    offset = (today - timedelta(days=1)) - max(sales["Дата"])
    sales = sales.copy()
    sales["Дата"] = sales["Дата"].apply(lambda d: d + offset)
    return sales


# ---------- расчёты ----------

@dataclass
class DayReport:
    day: date
    revenue: float
    orders: int
    avg_check: float
    revenue_delta_pct: float | None
    mtd_revenue: float
    plan: float
    forecast: float
    top_products: list[tuple[str, float]]
    low_stock: list[tuple[str, int]]


def build_report(sales: pd.DataFrame, stock: pd.DataFrame, day: date, month_plan: float, low_stock: int) -> DayReport:
    by_day = sales.groupby("Дата")["Сумма"].sum()
    revenue = float(by_day.get(day, 0.0))
    prev = by_day.get(day - timedelta(days=1))
    delta = (revenue / prev - 1) * 100 if prev else None

    day_rows = sales[sales["Дата"] == day]
    orders = len(day_rows)

    month_rows = sales[(sales["Дата"] >= day.replace(day=1)) & (sales["Дата"] <= day)]
    mtd = float(month_rows["Сумма"].sum())
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    forecast = mtd / day.day * days_in_month

    top = (day_rows.groupby("Товар")["Сумма"].sum().sort_values(ascending=False).head(3))
    low = stock[stock["Остаток"] < low_stock].sort_values("Остаток")

    return DayReport(
        day=day,
        revenue=revenue,
        orders=orders,
        avg_check=revenue / orders if orders else 0.0,
        revenue_delta_pct=delta,
        mtd_revenue=mtd,
        plan=month_plan,
        forecast=forecast,
        top_products=[(str(k), float(v)) for k, v in top.items()],
        low_stock=[(str(r["Товар"]), int(r["Остаток"])) for _, r in low.iterrows()],
    )


# ---------- оформление ----------

def rub(x: float) -> str:
    return f"{x:,.0f} ₽".replace(",", " ")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def format_report(r: DayReport) -> str:
    if r.revenue_delta_pct is None:
        delta = ""
    else:
        arrow = "🔺" if r.revenue_delta_pct >= 0 else "🔻"
        delta = f" {arrow} {r.revenue_delta_pct:+.0f}% к предыдущему дню"
    plan_pct = r.mtd_revenue / r.plan * 100 if r.plan else 0
    forecast_pct = r.forecast / r.plan * 100 if r.plan else 0
    verdict = "✅ идём к плану" if forecast_pct >= 100 else "⚠️ есть риск не выполнить план"

    lines = [
        f"<b>📊 Отчёт за {r.day:%d.%m.%Y}</b>",
        "",
        f"Выручка: <b>{rub(r.revenue)}</b>{delta}",
        f"Заказы: <b>{r.orders}</b> · средний чек: <b>{rub(r.avg_check)}</b>",
        "",
        f"<b>🎯 План месяца:</b> {rub(r.mtd_revenue)} из {rub(r.plan)} ({plan_pct:.0f}%)",
        f"Прогноз на конец месяца: {rub(r.forecast)} ({forecast_pct:.0f}%) — {verdict}",
    ]
    if r.top_products:
        lines += ["", "<b>🏆 Топ товаров дня:</b>"]
        lines += [f"{i}. {esc(name)} — {rub(v)}" for i, (name, v) in enumerate(r.top_products, 1)]
    if r.low_stock:
        lines += ["", "<b>📦 Заканчиваются:</b>"]
        lines += [f"• {esc(name)} — {qty} шт." for name, qty in r.low_stock]
    return "\n".join(lines)


def format_stock(stock: pd.DataFrame, low_stock: int) -> str:
    low = stock[stock["Остаток"] < low_stock].sort_values("Остаток")
    if low.empty:
        return f"📦 Все товары в наличии: остаток каждого не меньше {low_stock} шт."
    lines = [f"<b>📦 Остаток меньше {low_stock} шт.:</b>", ""]
    lines += [f"• {esc(str(r['Товар']))} — <b>{int(r['Остаток'])} шт.</b>" for _, r in low.iterrows()]
    return "\n".join(lines)


def revenue_chart(sales: pd.DataFrame, day: date, days: int = 14) -> bytes:
    """Столбики выручки за последние N дней, отчётный день выделен."""
    start = day - timedelta(days=days - 1)
    by_day = sales.groupby("Дата")["Сумма"].sum()
    dates = [start + timedelta(days=i) for i in range(days)]
    values = [by_day.get(d, 0.0) / 1000 for d in dates]
    colors = ["#E85A9E" if d == day else "#F4B6D2" for d in dates]

    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    ax.bar([d.strftime("%d.%m") for d in dates], values, color=colors, width=0.7)
    ax.set_title(f"Выручка за {days} дней, тыс. руб.", fontsize=13, loc="left", pad=12, color="#2B1D27")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#DDD")
    ax.tick_params(axis="x", labelsize=8, colors="#666", rotation=45)
    ax.tick_params(axis="y", labelsize=8, colors="#666", length=0)
    ax.grid(axis="y", color="#EEE")
    ax.set_axisbelow(True)
    ax.annotate(f"{values[-1]:.0f}", (len(dates) - 1, values[-1]), ha="center", va="bottom",
                fontsize=9, color="#B0306F", fontweight="bold", xytext=(0, 3), textcoords="offset points")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
