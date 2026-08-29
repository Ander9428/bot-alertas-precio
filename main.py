import os
import asyncio
import sqlite3
import threading
import sys
import logging
import requests
from flask import Flask
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configuración de logs para Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ==========================================
# 1. SERVIDOR FLASK (Render 24/7)
# ==========================================
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot de Alertas de Precio Activo 24/7", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port, use_reloader=False)

# ==========================================
# 2. BASE DE DATOS
# ==========================================
def init_db():
    conn = sqlite3.connect("alertas.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            condition TEXT,
            target_price REAL,
            triggered INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 3. OBTENCIÓN Y FORMATEO DE PRECIOS
# ==========================================
def format_price(price, symbol):
    """Formatea decimales según la clase de activo (5 para Forex, 2 para Cripto/Índices/Oro)."""
    sym = symbol.upper()
    if any(c in sym for c in ["BTC", "ETH", "SOL", "NAS100", "US30", "SP500", "XAU", "ORO", "GOLD"]):
        return f"{price:.2f}"
    return f"{price:.5f}"

def get_live_price(symbol_raw):
    sym = symbol_raw.upper().replace("/", "").replace("-", "").strip()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    # 1. FOREX DIRECTO DESDE TRADINGVIEW (OANDA - SIN CUENTAS NI TOKENS)
    if len(sym) == 6 and sym.isalpha():
        tv_ticker = f"OANDA:{sym}"
        url_tv = "https://scanner.tradingview.com/forex/scan"
        payload = {
            "symbols": {"tickers": [tv_ticker]},
            "columns": ["close"]
        }
        try:
            res = requests.post(url_tv, json=payload, headers=headers, timeout=4).json()
            if "data" in res and len(res["data"]) > 0:
                price = res["data"][0]["d"][0]
                if price is not None:
                    return float(price), sym
        except Exception as e:
            logger.error(f"Error TradingView OANDA para {tv_ticker}: {e}")

    # 2. CRIPTOMONEDAS (Coinbase / CryptoCompare)
    crypto_base = {
        "BTC": "BTC", "BTCUSD": "BTC", "BTCUSDT": "BTC",
        "ETH": "ETH", "ETHUSD": "ETH", "ETHUSDT": "ETH",
        "SOL": "SOL", "SOLUSD": "SOL", "SOLUSDT": "SOL"
    }

    if sym in crypto_base:
        base_coin = crypto_base[sym]
        try:
            url = f"https://api.coinbase.com/v2/prices/{base_coin}-USD/spot"
            res = requests.get(url, headers=headers, timeout=4).json()
            if "data" in res and "amount" in res["data"]:
                return float(res["data"]["amount"]), sym
        except Exception as e:
            logger.error(f"Error Coinbase para {sym}: {e}")

    # 3. RESPALDO (Yahoo Finance para Índices, Oro o Commodities)
    yahoo_map = {
        "XAUUSD": "GC=F", "ORO": "GC=F", "GOLD": "GC=F", "SILVER": "SI=F",
        "NAS100": "NQ=F", "NASDAQ": "NQ=F", "US30": "YM=F", "DOW": "YM=F", "SP500": "ES=F"
    }
    ticker_symbol = yahoo_map.get(sym, sym)
    if ticker_symbol == sym and len(sym) == 6 and sym.isalpha():
        ticker_symbol = f"{sym}=X"

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_symbol}?range=1d&interval=1m"
        res = requests.get(url, headers=headers, timeout=4).json()
        result = res.get("chart", {}).get("result")
        if result and len(result) > 0:
            price = result[0].get("meta", {}).get("regularMarketPrice")
            if price is not None:
                return float(price), ticker_symbol
    except Exception as e:
        logger.error(f"Error Yahoo Direct para {ticker_symbol}: {e}")

    try:
        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period="5d")
        if not data.empty:
            return float(data['Close'].dropna().iloc[-1]), ticker_symbol
    except Exception as e:
        logger.error(f"Error yfinance para {ticker_symbol}: {e}")

    return None, ticker_symbol

# ==========================================
# 4. TECLADOS Y MENÚS DE TELEGRAM
# ==========================================
def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("💵 Consultar Precio", callback_data="menu_precio"),
            InlineKeyboardButton("🔔 Crear Alerta", callback_data="menu_crear")
        ],
        [
            InlineKeyboardButton("📋 Mis Alertas", callback_data="menu_misalertas"),
            InlineKeyboardButton("🗑️ Borrar Alerta", callback_data="menu_borrar")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "🤖 **Bot de Alertas Inteligente (TradingView / OANDA Feed)**\n\n"
        "💡 **Uso ultrarrápido:**\n"
        "• **Ver Precio:** Escribe solo el activo (ej: `GBPUSD` o `BTCUSD`).\n"
        "• **Crear Alerta:** Escribe activo y precio objetivo (ej: `GBPUSD 1.35340` o `BTCUSD 65000`). El bot detectará automáticamente si es al alza o a la baja."
    )
    if update.message:
        await update.message.reply_text(texto, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(texto, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu_start":
        await start(update, context)

    elif query.data == "menu_precio":
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])
        await query.message.edit_text(
            "💵 **Consultar Precio**\n\nEscribe directamente el activo en el chat:\n`GBPUSD`, `BTCUSD` o `XAUUSD`",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

    elif query.data == "menu_crear":
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])
        await query.message.edit_text(
            "🔔 **Crear Alerta**\n\nEscribe el activo seguido del precio objetivo:\n• `GBPUSD 1.35340`\n• `BTCUSD 68000`\n• `XAUUSD 2500`",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

    elif query.data == "menu_misalertas":
        await mis_alertas_callback(query)

    elif query.data == "menu_borrar":
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])
        await query.message.edit_text(
            "🗑️ **Borrar Alerta**\n\nEscribe `/borrar ID` (ejemplo: `/borrar 1`).",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

# ==========================================
# 5. MANEJO DE MENSAJES DIRECTOS
# ==========================================
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split()
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Menú Principal", callback_data="menu_start")]])

    # 1. Consulta simple de precio
    if len(parts) == 1:
        symbol = parts[0].upper().replace("/", "").strip()
        price, _ = get_live_price(symbol)
        
        if price:
            p_formatted = format_price(price, symbol)
            await update.message.reply_text(f"💵 **Precio Actual de {symbol}:** `{p_formatted}`", reply_markup=back_btn, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ No se encontró el precio de `{symbol}`.", reply_markup=back_btn, parse_mode="Markdown")

    # 2. Creación automática de alerta (ej: GBPUSD 1.35340)
    elif len(parts) == 2:
        symbol = parts[0].upper().replace("/", "").strip()
        try:
            target_price = float(parts[1].replace(",", "."))
            user_id = update.effective_user.id
            current_price, _ = get_live_price(symbol)

            if current_price is None:
                await update.message.reply_text(f"⚠️ No se pudo obtener el precio actual de `{symbol}`.", reply_markup=back_btn, parse_mode="Markdown")
                return

            if target_price > current_price:
                condition = ">"
                tipo = "Al Alza 📈"
            elif target_price < current_price:
                condition = "<"
                tipo = "A la Baja 📉"
            else:
                await update.message.reply_text("⚠️ El precio objetivo ingresado es igual al precio actual.", reply_markup=back_btn)
                return

            conn = sqlite3.connect("alertas.db")
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO alertas (user_id, symbol, condition, target_price) VALUES (?, ?, ?, ?)",
                (user_id, symbol, condition, target_price)
            )
            conn.commit()
            conn.close()

            curr_fmt = format_price(current_price, symbol)
            target_fmt = format_price(target_price, symbol)

            await update.message.reply_text(
                f"✅ **Alerta Creada Exitosamente**\n\n"
                f"📈 **Activo:** `{symbol}`\n"
                f"📊 **Precio Actual:** `{curr_fmt}`\n"
                f"🎯 **Tipo:** `{tipo}` cuando alcance `{target_fmt}`",
                reply_markup=back_btn,
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ El precio debe ser un número válido. Ejemplo: `GBPUSD 1.35340`", reply_markup=back_btn)

    # 3. Creación con operador explícito (ej: GBPUSD > 1.35340)
    elif len(parts) == 3 and parts[1] in [">", "<"]:
        symbol = parts[0].upper().replace("/", "").strip()
        condition = parts[1]
        try:
            target_price = float(parts[2].replace(",", "."))
            user_id = update.effective_user.id
            current_price, _ = get_live_price(symbol)

            if current_price is None:
                await update.message.reply_text(f"⚠️ No se pudo obtener el precio actual de `{symbol}`.", reply_markup=back_btn, parse_mode="Markdown")
                return

            conn = sqlite3.connect("alertas.db")
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO alertas (user_id, symbol, condition, target_price) VALUES (?, ?, ?, ?)",
                (user_id, symbol, condition, target_price)
            )
            conn.commit()
            conn.close()

            curr_fmt = format_price(current_price, symbol)
            target_fmt = format_price(target_price, symbol)

            await update.message.reply_text(
                f"✅ **Alerta Creada Exitosamente**\n\n"
                f"📈 **Activo:** `{symbol}`\n"
                f"📊 **Precio Actual:** `{curr_fmt}`\n"
                f"🎯 **Disparar cuando:** `{condition} {target_fmt}`",
                reply_markup=back_btn,
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ El precio debe ser un número válido.", reply_markup=back_btn)

# ==========================================
# 6. VERIFICADOR DE ALERTAS SEGUNDO PLANO
# ==========================================
async def mis_alertas_callback(query):
    user_id = query.from_user.id
    conn = sqlite3.connect("alertas.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, condition, target_price FROM alertas WHERE user_id = ? AND triggered = 0", (user_id,))
    alertas = cursor.fetchall()
    conn.close()

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])

    if not alertas:
        await query.message.edit_text("📌 No tienes alertas activas en este momento.", reply_markup=back_btn)
        return

    msg = "📋 **Tus Alertas Activas:**\n\n"
    for a in alertas:
        cond_text = "al alza 📈" if a[2] == ">" else "a la baja 📉"
        target_fmt = format_price(a[3], a[1])
        msg += f"• **ID `{a[0]}`**: `{a[1]}` ({cond_text}) a `{target_fmt}`\n"
    
    await query.message.edit_text(msg, reply_markup=back_btn, parse_mode="Markdown")

async def borrar_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("❌ Ejemplo: `/borrar 1`")
            return
        alert_id = int(context.args[0])
        user_id = update.effective_user.id

        conn = sqlite3.connect("alertas.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alertas WHERE id = ? AND user_id = ?", (alert_id, user_id))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()

        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Menú Principal", callback_data="menu_start")]])
        if rows_affected > 0:
            await update.message.reply_text(f"🗑️ Alerta ID `{alert_id}` eliminada.", reply_markup=back_btn, parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ No se encontró la alerta.", reply_markup=back_btn)
    except Exception as e:
        logger.error(f"Error en borrar_alerta: {e}")

async def price_checker_loop(telegram_app):
    while True:
        try:
            conn = sqlite3.connect("alertas.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, symbol, condition, target_price FROM alertas WHERE triggered = 0")
            alertas = cursor.fetchall()

            for alerta in alertas:
                alert_id, user_id, symbol, condition, target_price = alerta
                current_price, _ = get_live_price(symbol)

                if current_price is not None:
                    triggered = (condition == ">" and current_price >= target_price) or \
                                (condition == "<" and current_price <= target_price)

                    if triggered:
                        curr_fmt = format_price(current_price, symbol)
                        target_fmt = format_price(target_price, symbol)
                        mensaje = (
                            f"🚨 **¡ALERTA DE PRECIO ALCANZADA!** 🚨\n\n"
                            f"📈 **Símbolo:** `{symbol}`\n"
                            f"🎯 **Objetivo:** `{condition} {target_fmt}`\n"
                            f"💵 **Precio Actual:** `{curr_fmt}`"
                        )
                        await telegram_app.bot.send_message(chat_id=user_id, text=mensaje, parse_mode="Markdown")
                        cursor.execute("UPDATE alertas SET triggered = 1 WHERE id = ?", (alert_id,))
                        conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error en price_checker_loop: {e}")

        await asyncio.sleep(20)

async def post_init(application: Application):
    asyncio.create_task(price_checker_loop(application))

# ==========================================
# 7. INICIALIZACIÓN
# ==========================================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    token = os.environ.get("TELEGRAM_TOKEN", "8255701499:AAHiwqeQMacNooE9X_xldFsv-6RrIkyNQ8Q")

    app = Application.builder().token(token).post_init(post_init).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("borrar", borrar_alerta))

    # Botones interactivos
    app.add_handler(CallbackQueryHandler(button_handler))

    # Mensajes directos simples
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("🚀 Bot Optimizado iniciado correctamente.")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
