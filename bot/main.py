from telegram.ext import ApplicationBuilder, CommandHandler
from config import BOT_TOKEN
from scanner import scanner_loop
from signals import monitor_loop

async def start(update, context):
    await update.message.reply_text(
        "🤖 COMBINED CRYPTO BOT\n\n"
        "/autostart 15m\n"
        "/autostop\n"
        "/signalmonitor on|off"
    )

async def post_init(app):
    app.create_task(scanner_loop(app))
    app.create_task(monitor_loop(app))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    print("🔥 BOT BERJALAN")
    app.run_polling()

if __name__ == "__main__":
    main()
