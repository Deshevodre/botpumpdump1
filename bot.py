# ┌─────────────────────────────────────────────┐
# │ БЛОК 1: Импорты и константы для bot.py      │
# └─────────────────────────────────────────────┘
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackContext,
)
from mexc_api import (
    detect_pumps,
    is_ready_to_dump,
    get_klines,
    plot_price_hourly,
    get_rsi,
)
from stats_manager import stats_command, weekly_report

import os
BOT_TOKEN = os.environ['BOT_TOKEN']

# ──────────────────────────────────────────────
# БЛОК 1.1: Глобальный кеш сигналов и настройки interval
# ──────────────────────────────────────────────
last_signal_time: dict[str, datetime] = {}
MIN_SIGNAL_INTERVAL = 300  # минимум 5 минут между сигналами по одной монете
CHAT_ID = None  # заполнится в start_bot

# ┌─────────────────────────────────────────────┐
# │ БЛОК 2: Форматирование текста сигнала       │
# └─────────────────────────────────────────────┘
def format_signal(symbol, change, prev_price, curr_price, reasons):
    pp = f"{prev_price:.8f}".rstrip('0').rstrip('.')
    cp = f"{curr_price:.8f}".rstrip('0').rstrip('.')
    link = f"https://futures.mexc.com/ru-RU/exchange/{symbol}"
    lines = [
        f"#МОНЕТА: {symbol}",
        f"🟢 Pump: {change:.2f}% ({pp} → {cp})",
        f"💲 Trade: Mexc ({link})",
        f"x100 / ~{(10000*1/100):.1f}$ / {1_000_000:.1f}$ / {0.02:.3f}%",
        "",
        f"📊 RSI: {get_rsi(symbol):.1f}%",
        "",
        "📉 Признаки дампа:"
    ]
    for r in reasons:
        lines.append(f"- {r}")
    return "\n".join(lines)

# ┌─────────────────────────────────────────────┐
# │ БЛОК 9.1: Функция start_bot                 │
# └─────────────────────────────────────────────┘
def start_bot(update: Update, context: CallbackContext):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    print(f"[DEBUG] /start received, CHAT_ID = {CHAT_ID}")
    update.message.reply_text(
        "Бот запущен!\n"
        "- Авто-проверка каждые 60 сек\n"
        "- Введите /check для мгновенной проверки"
    )

    jobq = context.job_queue
    job = jobq.run_repeating(
        auto_check,
        interval=60,
        first=1,
        context=CHAT_ID,
        job_kwargs={'max_instances': 3}
    )
    print(f"[DEBUG] Next auto_check at {job.next_run_time} (UTC)")

    # Еженедельный отчёт по воскресеньям в полночь UTC
    jobq.run_daily(
        weekly_report,
        time=datetime.strptime("00:00", "%H:%M").time(),
        context=CHAT_ID
    )

# ┌─────────────────────────────────────────────┐
# │ БЛОК 9.2: Функция auto_check                │
# └─────────────────────────────────────────────┘
def auto_check(context: CallbackContext):
    pumps = detect_pumps()
    top_pumps = pumps[:5]
    print(f"[DEBUG][auto] Всего пампов: {len(pumps)}, обрабатываем топ-{len(top_pumps)}")

    for symbol, change in top_pumps:
        now = datetime.utcnow()
        last = last_signal_time.get(symbol)
        if last and (now - last).total_seconds() < MIN_SIGNAL_INTERVAL:
            print(f"[DEBUG][auto] Пропускаем {symbol}, был сигнал {int((now-last).total_seconds())} сек назад")
            continue

        reasons = is_ready_to_dump(symbol)
        print(f"[DEBUG][auto] {symbol}: признаки {reasons}")
        if not reasons:
            continue

        dfm = get_klines(symbol, '1m', 120)
        if dfm.shape[0] < 61:
            print(f"[DEBUG][auto] Недостаточно 1m-данных для {symbol}, пропускаем")
            continue

        prev_price = dfm['close'].iloc[-61]
        curr_price = dfm['close'].iloc[-1]
        print(f"[DEBUG][auto] {symbol}: prev={prev_price}, curr={curr_price}")

        # 1) Текст
        msg = format_signal(symbol, change, prev_price, curr_price, reasons)
        context.bot.send_message(chat_id=CHAT_ID, text=msg)
        last_signal_time[symbol] = now
        print(f"[DEBUG][auto] Текст отправлен по {symbol}")

        # 2) График
        img_path = plot_price_hourly(symbol)
        if img_path:
            try:
                with open(img_path, 'rb') as img_file:
                    context.bot.send_photo(chat_id=CHAT_ID, photo=img_file)
                print(f"[DEBUG][auto] График отправлен по {symbol}")
            except Exception as e:
                print(f"[DEBUG][auto] Ошибка при отправке графика {symbol}: {e}")
        else:
            print(f"[DEBUG][auto] График для {symbol} пропущен")

# ┌─────────────────────────────────────────────┐
# │ БЛОК 9.3: main и регистрация команд         │
# └─────────────────────────────────────────────┘
def main():
    print("[DEBUG] Bot is starting...")
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler('start', start_bot))
    app.add_handler(CommandHandler('check', lambda u, c: (
        auto_check(c),
        u.message.reply_text("✅ Ручная проверка выполнена")
    )))
    app.add_handler(CommandHandler('stats', stats_command))

    print("[DEBUG] Starting polling...")
    app.run_polling()
    print("[DEBUG] Bot has stopped.")

# ┌─────────────────────────────────────────────┐
# │ БЛОК 9.4: Запуск приложения                │
# └─────────────────────────────────────────────┘
if __name__ == '__main__':
    main()
