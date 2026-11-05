"""Telegram-бот: отчёты по продажам из Google Таблицы.

Запуск: python bot.py
— отвечает на кнопки /report, /stock, /plan
— каждый день в REPORT_TIME сам присылает отчёт в ADMIN_CHAT_ID
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

import report

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")
logging.getLogger("matplotlib").setLevel(logging.WARNING)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SHEET_ID = os.environ["SHEET_ID"]
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")          # кому присылать ежедневный отчёт
REPORT_TIME = os.getenv("REPORT_TIME", "09:00")     # во сколько
TZ = ZoneInfo(os.getenv("TZ_NAME", "Europe/Moscow"))
MONTH_PLAN = float(os.getenv("MONTH_PLAN", "1800000"))
LOW_STOCK = int(os.getenv("LOW_STOCK", "10"))
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"      # сдвигать даты, чтобы данные были «свежими»

API = f"https://api.telegram.org/bot{TOKEN}/"

BTN_REPORT, BTN_STOCK, BTN_PLAN = "📊 Отчёт за вчера", "📦 Остатки", "🎯 План месяца"
KEYBOARD = {"keyboard": [[{"text": BTN_REPORT}], [{"text": BTN_STOCK}, {"text": BTN_PLAN}]],
            "resize_keyboard": True}

WELCOME = (
    "Привет! Я демо-бот отчётов 📊\n\n"
    "Беру данные о продажах вымышленного магазина из Google Таблицы и присылаю сводку: "
    "выручку, заказы, план месяца, топ товаров и что заканчивается на складе.\n\n"
    "Нажмите кнопку внизу, чтобы получить отчёт прямо сейчас. "
    "Такого бота можно настроить под ваши данные."
)


# ---------- Telegram ----------

def tg(method: str, http_timeout: int = 40, files=None, **params):
    if files:
        resp = requests.post(API + method, data=params, files=files, timeout=http_timeout)
    else:
        resp = requests.post(API + method, json=params, timeout=http_timeout)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description')}")
    return data["result"]


def send_text(chat_id, text):
    tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=KEYBOARD)


def send_photo(chat_id, png: bytes, caption: str):
    # подпись к фото ограничена 1024 символами — длинный отчёт отправляем отдельным сообщением
    if len(caption) <= 1024:
        tg("sendPhoto", files={"photo": ("chart.png", png)}, chat_id=chat_id, caption=caption, parse_mode="HTML")
    else:
        tg("sendPhoto", files={"photo": ("chart.png", png)}, chat_id=chat_id)
        send_text(chat_id, caption)


# ---------- данные ----------

def today() -> date:
    return datetime.now(TZ).date()


def get_data():
    sales, stock = report.load_data(SHEET_ID)
    if DEMO_MODE:
        sales = report.shift_to_yesterday(sales, today())
    return sales, stock


def send_daily_report(chat_id):
    sales, stock = get_data()
    day = today() - timedelta(days=1)
    r = report.build_report(sales, stock, day, MONTH_PLAN, LOW_STOCK)
    send_photo(chat_id, report.revenue_chart(sales, day), report.format_report(r))


def handle(chat_id, text: str):
    cmd = text.strip().split("@")[0]
    if cmd in ("/start", "/help"):
        send_text(chat_id, WELCOME)
    elif cmd in ("/report", BTN_REPORT):
        send_daily_report(chat_id)
    elif cmd in ("/stock", BTN_STOCK):
        _, stock = get_data()
        send_text(chat_id, report.format_stock(stock, LOW_STOCK))
    elif cmd in ("/plan", BTN_PLAN):
        sales, stock = get_data()
        r = report.build_report(sales, stock, today() - timedelta(days=1), MONTH_PLAN, LOW_STOCK)
        pct = r.mtd_revenue / r.plan * 100
        send_text(chat_id, (f"<b>🎯 План месяца</b>\n\nФакт: {report.rub(r.mtd_revenue)} ({pct:.0f}%)\n"
                            f"План: {report.rub(r.plan)}\nПрогноз: {report.rub(r.forecast)}"))
    else:
        send_text(chat_id, "Выберите действие кнопкой внизу 👇")


# ---------- расписание ----------

def next_run(now: datetime) -> datetime:
    h, m = map(int, REPORT_TIME.split(":"))
    run = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def main():
    offset = None
    scheduled = next_run(datetime.now(TZ))
    log.info("Бот запущен. Ежедневный отчёт: %s (%s)", scheduled, "в чат " + str(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else "выключен")
    while True:
        if ADMIN_CHAT_ID and datetime.now(TZ) >= scheduled:
            try:
                send_daily_report(ADMIN_CHAT_ID)
                log.info("Ежедневный отчёт отправлен")
            except Exception:  # noqa: BLE001
                log.exception("Не удалось отправить ежедневный отчёт")
            scheduled = next_run(datetime.now(TZ))

        try:
            updates = tg("getUpdates", http_timeout=40, offset=offset, timeout=25, allowed_updates=["message"])
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates: %s", exc)
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if "text" not in msg:
                continue
            chat_id = msg["chat"]["id"]
            try:
                handle(chat_id, msg["text"])
            except Exception:  # noqa: BLE001
                log.exception("Ошибка обработки %r", msg["text"])
                try:
                    send_text(chat_id, "Не получилось загрузить данные, попробуйте через минуту 🙏")
                except Exception:  # noqa: BLE001
                    pass


if __name__ == "__main__":
    main()
