import os
import asyncio
import sqlite3
import threading
import sys
import logging
from flask import Flask
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Configuración de logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ==========================================
# 1. SERVIDOR FLASK
# ==========================================
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot de Alertas con Menú Activo 24/7", 200

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

SYMBOL_MAP = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X",
    "AUDUSD": "AUDUSD=X", "USDCAD": "CAD=X", "USDCHF": "CHF=X",
    "NZDUSD": "NZDUSD=X", "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X",
    "XAUUSD": "GC=F", "ORO": "GC=F", "GOLD": "GC=F", "SILVER": "SI=F",
    "NAS100": "NQ=F", "NASDAQ": "NQ=F", "US30": "YM=F", "DOW": "YM=F", "SP500": "ES=F",
    "BTC": "BTC-USD", "BTCUSD": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"
}

def get_live_price(symbol_raw):
    sym = symbol_raw.upper().replace("/", "").strip()
    ticker_symbol = SYMBOL_MAP.get(sym, sym)
    if ticker_symbol == sym and len(sym) == 6 and sym.isalpha():
        ticker_symbol = f"{sym}=X"
    try:
        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return float(data['Close'].iloc[-1]), ticker_symbol
    except Exception as e:
        logger.error(f"Error consultando precio para {sym}: {e}")
    return None, ticker_symbol

# ==========================================
# 3. MENÚ INTERACTIVO Y NAVEGACIÓN
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
        ],
        [
            InlineKeyboardButton("❓ Ayuda y Ejemplos", callback_data="menu_ayuda")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    texto = (
        f"👋 **¡Hola {user_name}! Bienvenido al Bot de Alertas.**\n\n"
        "Selecciona una opción del menú interactivo para comenzar:"
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
            "💵 **Consultar Precio Actual**\n\n"
            "Escribe directamente el activo que deseas consultar:\n"
            "Ejemplo: `/precio XAUUSD` o `/precio GBPUSD`",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

    elif query.data == "menu_crear":
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])
        await query.message.edit_text(
            "🔔 **Crear Nueva Alerta**\n\n"
            "Envía un mensaje con la estructura:\n"
            "`/alerta SIMBOLO CONDICION PRECIO`\n\n"
            "**Ejemplos:**\n"
            "• `/alerta GBPUSD > 1.3150`\n"
            "• `/alerta EURUSD < 1.0820`\n"
            "• `/alerta XAUUSD > 2510.50`",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

    elif query.data == "menu_misalertas":
        await mis_alertas_callback(query)

    elif query.data == "menu_borrar":
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])
        await query.message.edit_text(
            "🗑️ **Borrar Alerta**\n\n"
            "1. Revisa el ID de tus alertas en **📋 Mis Alertas**.\n"
            "2. Envía el comando `/borrar ID` (ejemplo: `/borrar 3`).",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

    elif query.data == "menu_ayuda":
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]])
        await query.message.edit_text(
            "❓ **Guía Rápida**\n\n"
            "• **Símbolos soportados:** Forex (`GBPUSD`, `EURUSD`), Oro (`XAUUSD`), Índices (`NAS100`, `US30`) y Cripto (`BTC`, `ETH`).\n"
            "• **Condiciones:** Usar `>` para precios al alza o `<` para precios a la baja.\n"
            "• **Frecuencia:** Revisión automática de mercado cada 20 segundos.",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )

# ==========================================
# 4. FUNCIONALIDADES
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
        msg += f"• **ID `{a[0]}`**: `{a[1]}` cuando sea `{a[2]} {a[3]}`\n"
    
    await query.message.edit_text(msg, reply_markup=back_btn, parse_mode="Markdown")

async def crear_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("❌ Uso: `/alerta SIMBOLO > PRECIO`", parse_mode="Markdown")
            return
        symbol = args[0].upper().replace("/", "").strip()
        condition = args[1]
        target_price = float(args[2].replace(",", "."))
        user_id = update.effective_user.id

        if condition not in [">", "<"]:
            await update.message.reply_text("❌ La condición debe ser `>` o `<`.")
            return

        current_price, _ = get_live_price(symbol)
        if current_price is None:
            await update.message.reply_text(f"⚠️ No se obtuvo el precio de `{symbol}`.", parse_mode="Markdown")
            return

        conn = sqlite3.connect("alertas.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO alertas (user_id, symbol, condition, target_price) VALUES (?, ?, ?, ?)",
            (user_id, symbol, condition, target_price)
        )
        conn.commit()
        conn.close()

        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Menú Principal", callback_data="menu_start")]])
        await update.message.reply_text(
            f"✅ **Alerta Creada Exitosamente**\n\n"
            f"📈 **Activo:** `{symbol}`\n"
            f"📊 **Precio Actual:** `{current_price:.4f}`\n"
            f"🎯 **Disparar cuando:** `{condition} {target_price}`",
            reply_markup=back_btn,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error en crear_alerta: {e}")
        await update.message.reply_text(f"❌ Error al crear la alerta: {e}")

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

async def consultar_precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Ejemplo: `/precio XAUUSD`")
        return
    symbol = context.args[0].upper().strip()
    price, _ = get_live_price(symbol)
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Menú Principal", callback_data="menu_start")]])
    if price:
        await update.message.reply_text(f"💵 **Precio Actual de {symbol}:** `{price:.4f}`", reply_markup=back_btn, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No se encontró el precio de `{symbol}`.", reply_markup=back_btn)

# ==========================================
# 5. MOTOR EN SEGUNDO PLANO
# ==========================================
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
                        mensaje = (
                            f"🚨 **¡ALERTA DE PRECIO ALCANZADA!** 🚨\n\n"
                            f"📈 **Símbolo:** `{symbol}`\n"
                            f"🎯 **Objetivo:** `{condition} {target_price}`\n"
                            f"💵 **Precio Actual:** `{current_price:.4f}`"
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
# 6. INICIALIZACIÓN
# ==========================================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    token = os.environ.get("TELEGRAM_TOKEN", "8255701499:AAHiwqeQMacNooE9X_xldFsv-6RrIkyNQ8Q")

    app = Application.builder().token(token).post_init(post_init).build()

    # Handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("alerta", crear_alerta))
    app.add_handler(CommandHandler("borrar", borrar_alerta))
    app.add_handler(CommandHandler("precio", consultar_precio))

    # Handler para interactuar con botones del menú
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🚀 Bot con Menú Interactivo iniciado correctamente.")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
