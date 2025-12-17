from telegram.ext import ApplicationBuilder, CommandHandler
from config import BOT_TOKEN
from scanner import scan_now, autostart, autostop, scanner_loop
from signals import (
    signalmonitor, addcoin, delcoin, listcoin, monitor_loop
)

async def start(update, context):
    await update.message.reply_text(
        "🤖 COMBINED CRYPTO BOT\n\n"
        "📊 SCANNER\n"
        "/scan 15m\n"
        "/autostart 15m\n"
        "/autostop\n\n"
        "🚨 SIGNAL\n"
        "/signalmonitor on|off|btc\n"
        "/addcoin BTC\n"
        "/delcoin BTC\n"
        "/listcoin"
    )

async def post_init(app):
    app.create_task(scanner_loop(app))
    app.create_task(monitor_loop(app))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_now))
    app.add_handler(CommandHandler("autostart", autostart))
    app.add_handler(CommandHandler("autostop", autostop))

    app.add_handler(CommandHandler("signalmonitor", signalmonitor))
    app.add_handler(CommandHandler("addcoin", addcoin))
    app.add_handler(CommandHandler("delcoin", delcoin))
    app.add_handler(CommandHandler("listcoin", listcoin))

    print("🔥 BOT BERJALAN")
    app.run_polling()

if __name__ == "__main__":
    main()
