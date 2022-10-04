import json
import logging.config
import ssl
import sys

import psycopg2
from aiogram import Bot, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import Dispatcher
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.webhook import configure_app
from aiogram.utils.callback_data import CallbackData
from aiohttp import web

import config

# --- Логирование ---
with open(config.LOGGER_CONFIG, 'r', encoding='utf-8') as stream:
    logger_config = json.load(stream)
    logger_config['handlers']['file']['filename'] = config.log_filename
    logger_config['handlers']['error_file']['filename'] = config.error_log_filename

logging.config.dictConfig(logger_config)
log = logging.getLogger(__name__)

# --- Подключение к бд ---
try:
    conn = psycopg2.connect(dbname=config.postgres_dbname,
                            user=config.postgres_user, password=config.postgres_password,
                            host=config.postgres_host, port=config.postgres_port)
    cursor = conn.cursor()
except Exception as e:
    log.exception("No connect to db - {}".format(e))
    sys.exit("No connect Database")

bot = Bot(token=config.API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

product_cb = CallbackData('buy', 'name', 'action')
deposit_cb = CallbackData('deposit', 'action')


class FormProducts(StatesGroup):
    city = State()


def create_user(user):
    user_id = user.id
    first_name = user.first_name
    last_name = user.last_name
    user_name = user.username

    if user_name is None:
        user_name = ""

    cursor.execute("""INSERT INTO users (user_id, first_name, last_name, username)
                      VALUES (%s, %s, %s, %s);
                   """,
                   (user_id, first_name, last_name, user_name))
    conn.commit()


def user_exist(user_id):
    cursor.execute("""SELECT * FROM users WHERE user_id = %s""", (user_id,))
    row_user = cursor.fetchall()
    if len(row_user) == 0:
        return 0
    return row_user


def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton('Калькулятор'))
    markup.row(types.KeyboardButton('Поддержка'))
    return markup


async def send_start(message: types.Message):
    user = message.from_user
    user_id = user.id
    current_user = user_exist(user_id)
    if current_user == 0:
        create_user(user)
        current_user = user_exist(user_id)

    await bot.send_message(message.chat.id, "Добро пожаловать, {}! 👋🏻".format(current_user[0][1]),
                           reply_markup=main_menu_keyboard())


@dp.message_handler(text=["Калькулятор", "Поддержка"])
async def send_message(message: types.Message):
    user_id = message.from_user.id

    if message.text == "Калькулятор":
        await bot.send_message(user_id, f"Калькулятор",
                               parse_mode="Markdown")

    elif message.text == "Поддержка":
        await bot.send_message(user_id, "По всем вопросам обращайтесь - {}".format(config.SUPPORT))


def setup_handlers(dispatcher: Dispatcher):
    dispatcher.register_message_handler(send_start, commands=['start'])
    dispatcher.register_message_handler(send_message, text=["Калькулятор", "Поддержка"])


async def on_startup(_app):
    setup_handlers(dp)

    # Get current webhook status
    webhook = await bot.get_webhook_info()

    webhook_url = f"https://{config.host_name}{config.webhook_path}"
    log.info("Webhook URL - {}".format(webhook_url))

    if webhook.url != webhook_url:
        # If URL doesn't match with by current remove webhook
        if not webhook.url:
            await bot.delete_webhook()
            log.info("Delete webhook")

        # Set new URL for webhook
        if config.cert:
            with open(config.cert, 'rb') as cert_file:
                await bot.set_webhook(webhook_url, certificate=cert_file)
                log.info("Set webhook with cert - {}".format(webhook_url))
        else:
            await bot.set_webhook(webhook_url)
            log.info("Set webhook - {}".format(webhook_url))


async def on_shutdown(_app):
    # Remove webhook.
    await bot.delete_webhook()

    # Close Redis connection.
    await dp.storage.close()
    await dp.storage.wait_closed()


if __name__ == '__main__':
    app = web.Application()
    configure_app(dp, app, path=config.webhook_path)

    # Setup event handlers
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    if config.cert and config.pkey:
        # Generate SSL context
        # ss = ssl.SSLContext(ssl.PRP)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        ssl_context.load_cert_chain(config.cert, config.pkey)
    else:
        ssl_context = None

    # Start web-application
    web.run_app(app, host=config.host, port=config.port, ssl_context=ssl_context)
