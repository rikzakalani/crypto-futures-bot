from telegram.ext import ApplicationBuilder, CommandHandler
from telegram import Update
from telegram.ext import ContextTypes
from config import *
import scanner, signals

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 COMBINED CRYPTO BOT\n\n"
        "/scan 15m|1h|1d\n"
        "/autostart 15m\n"
        "/autostop\n"
        "/signalmonitor on|off|btc\n"
        "/listcoin"
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tf = context.args[0] if context.args else "15m"
    coins = scanner.get_top_movers()
    for _, r in coins.iterrows():
        await scanner.send_chart(context.application, r.symbol, r.change, tf)

async def autostart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scanner.AUTO_SCAN = True
    scanner.AUTO_TF = context.args[0]
    scanner.AUTO_INTERVAL = TF_MAP[scanner.AUTO_TF]
    await update.message.reply_text("🟢 AUTO SCAN AKTIF")

async def autostop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scanner.AUTO_SCAN = False
    await update.message.reply_text("🔴 AUTO SCAN OFF")

async def post_init(app):
    app.create_task(scanner.scanner_loop(app))
    app.create_task(signals.monitor_loop(app))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("autostart", autostart))
    app.add_handler(CommandHandler("autostop", autostop))

    # signal handlers
    app.add_handler(CommandHandler("signalmonitor", signals.signalmonitor))
    app.add_handler(CommandHandler("listcoin", signals.listcoin))
    app.add_handler(CommandHandler("addcoin", signals.addcoin))
    app.add_handler(CommandHandler("delcoin", signals.delcoin))

    print("🚀 COMBINED BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
