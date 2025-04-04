import telebot
from telebot import types

# Initialize bot with your token
bot = telebot.TeleBot('7900071646:AAHIi93du6_RfCzGIjE02FlZyE1XZ0VGBK8')

# Handler for /start command
@bot.message_handler(commands=['start'])
def start(message):
    # Create keyboard markup
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Button 1')
    btn2 = types.KeyboardButton('Button 2') 
    btn3 = types.KeyboardButton('Button 3')
    markup.add(btn1, btn2, btn3)
    # Send welcome message with keyboard
    bot.send_message(message.chat.id, 
                     "Welcome! Choose an option:",
                     reply_markup=markup)

# Handler for button clicks
@bot.message_handler(content_types=['text'])
def handle_text(message):
    if message.text == 'Button 1':
        bot.send_message(message.chat.id, 'You pressed Button 1!')
    elif message.text == 'Button 2':
        bot.send_message(message.chat.id, 'You pressed Button 2!')
    elif message.text == 'Button 3':
        bot.send_message(message.chat.id, 'You pressed Button 3!')

# Start the bot
if __name__ == '__main__':
    bot.polling(none_stop=True)
