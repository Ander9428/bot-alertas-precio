import os
import asyncio
import sqlite3
import threading
import sys
from flask import Flask
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Forzar la salida de logs directa en Render
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 1. SERVIDOR FLASK (Para mantener Render activo)
# ==========================================
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot de Alertas de Precio Activo 24/7 en Render", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port, use_reloader=False)

# ==========================================
# 2. BASE DE DATOS (SQLite local)
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

# MAPA DE SÍMBOLOS (Forex, Oro, Índices y Cripto)
SYMBOL_MAP = {
    # Forex
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "USDCHF": "CHF=X",
    "NZDUSD": "NZDUSD=X",
    "GBPJPY": "GBPJPY=X",
    "EURJPY": "EURJPY=X",
    # Commodities / Oro / Plata
    "XAUUSD": "GC=F",
    "ORO": "GC=F",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    # Índices
    "NAS100": "NQ=F",
    "NASDAQ": "NQ=F",
    "US30": "YM=F",
    "DOW": "YM=F",
    "SP500": "ES=F",
    # Criptos
    "BTC": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD"
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
            price = float(data['Close'].iloc[-1])
            return price, ticker_symbol
    except Exception as e:
        print(f"Error consultando precio para {sym}: {e}", flush=True)
        
    return None, ticker_symbol

# ==========================================
# 3. COMANDOS DE TELEGRAM
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 **¡Bot de Alertas de Precio Activo!**\n\n"
        "📈 **Crear Alerta:**\n"
        "• `/alerta XAUUSD > 2500`\n"
        "• `/alerta NAS100 < 19500`\n"
        "• `/alerta EURUSD > 1.0880`\n"
        "• `/alerta BTC > 68000`\n\n"
        "📋 **Gestión de Alertas:**\n"
        "• `/misalertas` - Ver tus alertas activas\n"
        "• `/borrar <ID>` - Eliminar alerta\n"
        "• `/precio <ACTIVO>` - Consultar precio actual"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def crear_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("❌ Uso: `/alerta SIMBOLO > PRECIO` o `/alerta SIMBOLO < PRECIO`", parse_mode="Markdown")
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
            await update.message.reply_text(f"⚠️ No se obtuvo el precio de `{symbol}`. Verifica el símbolo.", parse_mode="Markdown")
            return

        conn = sqlite3.connect("alertas.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO alertas (user_id, symbol, condition, target_price) VALUES (?, ?, ?, ?)",
            (user_id, symbol, condition, target_price)
        )
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ **Alerta Creada Exitosamente**\n\n"
            f"📈 **Activo:** `{symbol}`\n"
            f"📊 **Precio Actual:** `{current_price:.4f}`\n"
            f"🎯 **Disparar cuando:** `{condition} {target_price}`",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ El precio debe ser un número válido.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al crear la alerta: {e}")

async def mis_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("alertas.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, condition, target_price FROM alertas WHERE user_id = ? AND triggered = 0", (user_id,))
    alertas = cursor.fetchall()
    conn.close()

    if not alertas:
        await update.message.reply_text("📌 No tienes alertas activas en este momento.")
        return

    msg = "📋 **Tus Alertas Activas:**\n\n"
    for a in alertas:
        msg += f"• **ID `{a[0]}`**: `{a[1]}` cuando sea `{a[2]} {a[3]}`\n"
    msg += "\n💡 *Para eliminar usa: `/borrar ID`*"
    await update.message.reply_text(msg, parse_mode="Markdown")

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

        if rows_affected > 0:
            await update.message.reply_text(f"🗑️ Alerta ID `{alert_id}` eliminada.", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ No se encontró la alerta.")
    except ValueError:
        await update.message.reply_text("❌ El ID debe ser un número entero.")

async def consultar_precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Ejemplo: `/precio XAUUSD`")
        return
        
    symbol = context.args[0].upper().strip()
    price, _ = get_live_price(symbol)
    
    if price:
        await update.message.reply_text(f"💵 **Precio Actual de {symbol}:** `{price:.4f}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No se encontró el precio de `{symbol}`.", parse_mode="Markdown")

# ==========================================
# 4. MOTOR EN SEGUNDO PLANO (Verifica precios cada 20s)
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
                    triggered = False
                    if condition == ">" and current_price >= target_price:
                        triggered = True
                    elif condition == "<" and current_price <= target_price:
                        triggered = True

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
            print(f"Error en bucle de verificación: {e}", flush=True)

        await asyncio.sleep(20)

async def post_init(application: Application):
    asyncio.create_task(price_checker_loop(application))

# ==========================================
# 5. INICIALIZACIÓN PRINCIPAL
# ==========================================
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    token = os.environ.get("TELEGRAM_TOKEN", "8255701499:AAHiwqeQMacNooE9X_xldFsv-6RrIkyNQ8Q")

    app = Application.builder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("alerta", crear_alerta))
    app.add_handler(CommandHandler("misalertas", mis_alertas))
    app.add_handler(CommandHandler("borrar", borrar_alerta))
    app.add_handler(CommandHandler("precio", consultar_precio))

    print("🚀 Bot iniciado y listo para recibir comandos en Telegram.", flush=True)
    
    # drop_pending_updates=True limpia conexiones previas colgadas en Telegram
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
