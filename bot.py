import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import threading
import time

TOKEN = "7900071646:AAHIi93du6_RfCzGIjE02FlZyE1XZ0VGBK8"  # Укажите токен вашего бота
bot = telebot.TeleBot(TOKEN)

# Главное меню
def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("⚙️ Настройки"), KeyboardButton("📊 Запустить парсинг"))
    return markup

# Меню настроек
def settings_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("👥 Все участники"), KeyboardButton("➕ Добавить нового"))
    markup.add(KeyboardButton("❌ Удалить"), KeyboardButton("⬅️ Назад"))
    return markup

# Подключение к БД
def connect_db():
    return sqlite3.connect("parser.db")

# Функция добавления участника
def add_participant(participant_number):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO participants (participant_number) VALUES (?)", (participant_number,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# Функция удаления участника
def delete_participant(participant_number):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM participants WHERE participant_number = ?", (participant_number,))
    conn.commit()
    conn.close()

# Функция получения списка участников
def get_all_participants():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT participant_number FROM participants")
    participants = [row[0] for row in cursor.fetchall()]
    conn.close()
    return participants

# Обработчик команды /start
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "👋 Привет! Выберите действие:", reply_markup=main_menu())

# Обработчик кнопки "Настройки"
@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
def settings(message):
    bot.send_message(message.chat.id, "🔧 Меню настроек:", reply_markup=settings_menu())

# Обработчик кнопки "Все участники"
@bot.message_handler(func=lambda message: message.text == "👥 Все участники")
def show_participants(message):
    participants = get_all_participants()
    if participants:
        bot.send_message(message.chat.id, "📌 Участники:\n" + "\n".join(participants))
    else:
        bot.send_message(message.chat.id, "🚫 Список участников пуст.")

# Обработчик кнопки "Добавить нового"
@bot.message_handler(func=lambda message: message.text == "➕ Добавить нового")
def request_new_participant(message):
    bot.send_message(message.chat.id, "📝 Введите номер участника для добавления:")
    # Сохраняем состояние, что пользователь в процессе добавления
    bot.register_next_step_handler(message, add_new_participant)

# Добавление нового участника
def add_new_participant(message):
    if add_participant(message.text):
        bot.send_message(message.chat.id, f"✅ Участник {message.text} добавлен.")
    else:
        bot.send_message(message.chat.id, f"⚠️ Участник {message.text} уже существует.")

# Обработчик кнопки "Удалить"
@bot.message_handler(func=lambda message: message.text == "❌ Удалить")
def request_delete_participant(message):
    bot.send_message(message.chat.id, "🗑 Введите номер участника для удаления:")
    # Сохраняем состояние, что пользователь в процессе удаления
    bot.register_next_step_handler(message, remove_participant)

# Удаление участника
def remove_participant(message):
    delete_participant(message.text)
    bot.send_message(message.chat.id, f"❌ Участник {message.text} удален.")

# Обработчик кнопки "Назад"
@bot.message_handler(func=lambda message: message.text == "⬅️ Назад")
def back_to_main(message):
    bot.send_message(message.chat.id, "🔙 Возвращаемся в главное меню:", reply_markup=main_menu())

# Запуск парсинга
@bot.message_handler(func=lambda message: message.text == "📊 Запустить парсинг")
def start_parsing_handler(message):
    participants = get_all_participants()
    if not participants:
        bot.send_message(message.chat.id, "🚫 Нет участников для парсинга.")
        bot.send_message(message.chat.id, "❗️ Добавьте участников для запуска парсинга.")
        return

    bot.send_message(message.chat.id, "⏳ Парсинг запущен...")

    # Запуск в отдельном потоке
    thread = threading.Thread(target=run_parsing, args=(message.chat.id, participants))
    thread.start()

def start_parsing():
    pass

# Функция для запуска парсинга
def run_parsing(chat_id, participants):
    for participant in participants:
        data = start_parsing(participant)  # Вызываем парсер
        save_parsing_result(participant, data)  # Сохраняем данные в БД
        time.sleep(2)  # Имитация задержки для API

    bot.send_message(chat_id, "✅ Парсинг завершен!")

# Функция сохранения результатов парсинга в БД
def save_parsing_result(participant_number, case_data):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO cases (participant_number, case_data) VALUES (?, ?)", (participant_number, case_data))
    conn.commit()
    conn.close()

# Запуск бота
bot.polling(none_stop=True)
