import os
import re
import threading

import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, send_file
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging
import telebot
import shutil
import re
import json
import pdfplumber
from telebot import types

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
SAVE_PATH = "downloads"
os.makedirs(SAVE_PATH, exist_ok=True)
# Telegram API токен
TOKEN = "7900071646:AAHIi93du6_RfCzGIjE02FlZyE1XZ0VGBK8"
bot = telebot.TeleBot(TOKEN)
# Флаг блокировки выполнения задачи
is_parsing = False
lock = threading.Lock()

def init_driver(download_folder):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36")
    prefs = {
        "download.default_directory": download_folder,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,  # Открывать PDF в браузере
    }
    options.add_experimental_option("prefs", prefs)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def normalize_keyword(keyword):
    """ Создает регулярное выражение для поиска ключевых слов с пробелами между буквами. """
    spaced_keyword = " ".join(keyword)  # "УСТАНОВИЛ" → "У С Т А Н О В И Л"
    return rf"(?:{keyword}:|{spaced_keyword}:)"  # Учитываем двоеточие сразу после слова

# Функция для очистки имени файла от недопустимых символов
def sanitize_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)  # Заменяем запрещённые символы

# Извлечение даты из строки
def extract_date(text):
    # Ищем дату в формате "ДД.ММ.ГГГГ"
    match = re.search(r"\d{2}\.\d{2}\.\d{4}", text)
    if match:
        return match.group(0)
    return "Нет даты"

def download_file_ics_by_url(url):
    driver = None
    download_folder = os.path.abspath("downloads")
    os.makedirs(download_folder, exist_ok=True)
    try:
        driver = init_driver(download_folder)
        driver.get(url)
        print(f"Загружаем календарь по ссылке: {url}")
        time.sleep(5)  # Ждем загрузки файла
        download_folder = os.path.abspath("downloads")
        ics_folder = os.path.abspath("ics")
        if not os.path.exists(ics_folder):
            os.makedirs(ics_folder)
        files = os.listdir(download_folder)
        if not files:
            return json.dumps({"error": "Файл не был загружен."}, ensure_ascii=False)
        file_path = os.path.join(download_folder, files[0])
        shutil.move(file_path, ics_folder)
        print(f"Файл перемещен в папку 'ics': {os.path.join(ics_folder, files[0])}")
        return os.path.join(ics_folder, files[0])
    except Exception as e:
        return {"error": f"Ошибка: {str(e)}"}
    finally:
        if driver:
            print("Закрываем WebDriver...")
            driver.quit()  # Безопасное закрытие WebDriver

def extract_text_from_pdf(url):
    """ Загружает PDF через Selenium и парсит текст с помощью pdfplumber. """
    download_folder = os.path.abspath("downloads")
    os.makedirs(download_folder, exist_ok=True)

    driver = None
    try:
        driver = init_driver(download_folder)
        print(f"Открываем ссылку: {url}")
        driver.get(url)
        time.sleep(10)  # Ждем загрузки

        # Ожидаем появления файла
        pdf_file = None
        for _ in range(30):  # Ожидание до 30 секунд
            files = [f for f in os.listdir(download_folder) if f.endswith(".pdf")]
            if files:
                pdf_file = os.path.join(download_folder, files[0])
                break
            time.sleep(1)

        if not pdf_file:
            return {"error": "PDF не загрузился"}

        print(f"Файл загружен: {pdf_file}")

        # Читаем PDF через pdfplumber
        with pdfplumber.open(pdf_file) as pdf:
            full_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])

        # Удаляем файл после обработки
        os.remove(pdf_file)

        # Регулярные выражения с учетом пробелов между буквами
        ustanovil_regex = normalize_keyword("УСТАНОВИЛ")
        opredelil_regex = normalize_keyword("ОПРЕДЕЛИЛ")

        # Извлекаем нужные части текста
        result = {"pdf_link": url, "established": "", "determined": "", "full": full_text}

        # Ищем "УСТАНОВИЛ:"
        match_established = re.search(rf"{ustanovil_regex}(.*?)(?:{opredelil_regex}|$)", full_text, re.S)
        if match_established:
            result["established"] = match_established.group(1).strip() if match_established.group(1) else ""

        # Ищем "ОПРЕДЕЛИЛ:"
        match_determined = re.search(rf"{opredelil_regex}(.*)", full_text, re.S)
        if match_determined:
            result["determined"] = match_determined.group(1).strip() if match_determined.group(1) else ""

        return result

    except Exception as e:
        return {"error": f"Ошибка: {str(e)}"}

    finally:
        if driver:
            print("Закрываем WebDriver...")
            driver.quit()  # Безопасное закрытие WebDriver

# Сохранение данных в Excel
def save_to_excel(data, filename):
    filename = sanitize_filename(filename)  # Очищаем имя файла
    filepath = os.path.join(SAVE_PATH, filename)

    # Преобразуем данные в pandas DataFrame
    formatted_data = []
    for case in data:
        formatted_data.append({
            "Дело": f"{case.get('case-date', 'Нет данных')} {case.get('case_number', 'Нет данных')}",
            "Юрист": "",  # Оставляем поле пустым
            "Следующее заседание": case.get('next_hearing', 'Нет даты'),
            "Истцы": case.get('plaintiff', 'Не указаны'),
            "Ответчики": case.get('defendant', 'Не указаны'),
            "ИСКОВЫЕ ТРЕБОВАНИЯ": case.get('iskov', ''),
            "Итоговый судебный акт": case.get('itog', ''),
            "Хронология": case.get('chronology', ''),
            "PDF_link": case.get('pdf_link', ''),
            "Установил": case.get('established', ''),
            "Определил": case.get('determined', ''),
            "PDF": case.get('full', '')
        })

    df = pd.DataFrame(formatted_data)
    df.to_excel(filepath, index=False)  # Сохраняем файл Excel
    return filepath

def get_chronology_data(code):
    soup = BeautifulSoup(code, "html.parser")
    cases = []
    case_data = {}
    case_pdf = None
    try:
        for item in soup.find_all("div", class_="b-chrono-item"):
            case_date = item.find("p", class_="case-date")
            case_type = item.find("p", class_="case-type")

            case_date = case_date.get_text(strip=True) if case_date else "Нет данных"
            case_type = case_type.get_text(strip=True) if case_type else "Нет данных"

            r_col = item.find("div", class_="r-col")

            if r_col:
                case_subject = r_col.find("p", class_="case-subject")
                case_result = r_col.find("span", class_="js-judges-rollover")
                h2 = r_col.find("h2", class_="b-case-result")
                case_subject = case_subject.get_text(strip=True) if case_subject else "Нет данных"
                case_result_text = case_result.get_text(strip=True) if case_result else "Нет данных"

                # Поиск ссылки на PDF
                if h2:
                    pdf_link = h2.find("a", class_="js-case-result-text--doc_link", href=True)
                    # if pdf_link and "О принятии" in pdf_link.get_text(strip=True):
                    if pdf_link and case_pdf is None:
                        if "определение" in case_type.lower():
                            case_pdf = extract_text_from_pdf(pdf_link["href"])
            else:
                case_subject = case_result_text = "Нет данных"

            cases.append(f"{case_date} / {case_type} / {case_subject} / {case_result_text}")
        case_data = {
            "chronology": "\n".join(cases),
            "pdf": case_pdf
        }
        print("Данные хронологии получены")
    except Exception as e:
        print(f"Ошибка get_chronology_data(): {str(e)}")

    return case_data

# Парсинг информации по делу
def get_case_data(case_url):
    driver = None
    try:
        driver = init_driver("downloads")
        logging.info(f"Парсим дело: {case_url}")
        driver.get(case_url)
        time.sleep(10)
        case = {}
        # Номер дела
        try:
            case['case_number'] = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.crumb .js-case-header-case_num"))
            ).text
        except:
            case['case_number'] = "Не удалось найти номер дела"

        try:
            hearing_info = driver.find_element(By.CSS_SELECTOR, ".b-instanceAdditional").text
            case['next_hearing'] = extract_date(hearing_info)
        except:
            case['next_hearing'] = "Нет даты"
        # Истец
        try:
            plaintiff_element = driver.find_element(By.CSS_SELECTOR, ".plaintiffs .container ul li a")
            case['plaintiff'] = plaintiff_element.text  # Извлекаем только текст внутри тега <a>
        except:
            case['plaintiff'] = "Истец не указан"
        # Ответчик
        try:
            defendant_element = driver.find_element(By.CSS_SELECTOR, ".defendants .container ul li a")
            case['defendant'] = defendant_element.text
        except:
            case['defendant'] = "Ответчик не указан"

        # Дата кейса
        try:
            case['case-date'] = driver.find_element(By.CSS_SELECTOR, ".case-date").text
        except:
            case['case-date'] = "Дата кейса не указана"

        # Загрузка Хронологии
        try:
            plus_button = WebDriverWait(driver, 45).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".b-collapse.js-collapse"))
            )
            plus_button.click()
            time.sleep(3)
            chrono_list_content = WebDriverWait(driver, 45).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#chrono_list_content"))
            )
            # Ожидаем появления блока chrono_list_content
            if chrono_list_content:
                b_chrono_item = WebDriverWait(driver, 45).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".b-chrono-item"))
                )
                # Ожидаем появления первого элемента .b-chrono-item
                if b_chrono_item:
                    # Парсим информацию из хронологии
                    chronology_data = get_chronology_data(chrono_list_content.get_attribute("outerHTML"))
                    if chronology_data:
                        if 'chronology' in chronology_data:
                            case['chronology'] = chronology_data['chronology']
                        if 'pdf' in chronology_data and 'established' in chronology_data['pdf']:
                            case['established'] = chronology_data['pdf']['established']
                        if 'pdf' in chronology_data and 'determined' in chronology_data['pdf']:
                            case['determined'] = chronology_data['pdf']['determined']
                        if 'pdf' in chronology_data and 'pdf_link' in chronology_data['pdf']:
                            case['pdf_link'] = chronology_data['pdf']['pdf_link']
                        if 'pdf' in chronology_data and 'full' in chronology_data['pdf']:
                            case['full'] = chronology_data['pdf']['full']

        except Exception as e:
            print(f"Ошибка загрузки хронологии: {str(e)}")
            case['chronology'] = "Ошибка загрузки хронологии"

        case['case_url'] = case_url
        return case
    except Exception as e:
        return {"error": f"Ошибка: {str(e)}"}
    finally:
        if driver:
            driver.quit()

# Функция для получения информации о делах для участника
def get_case_info(participant_number):
    driver = None
    try:
        driver = init_driver("downloads")
        logging.info(f"Запрос информации о делах для участника: {participant_number}")
        driver.get("https://kad.arbitr.ru")

        # Закрытие всплывающего окна, если оно есть
        try:
            close_popup = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "js-promo_notification-popup-close"))
            )
            close_popup.click()
            logging.info("Всплывающее окно закрыто...")
        except Exception as e:
            logging.info("Всплывающее окно не появилось или уже закрыто.")

        # Ввод номера участника и выполнение поиска
        participant_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea.g-ph"))
        )
        participant_input.send_keys(participant_number)
        time.sleep(1)

        # Нажатие кнопки поиска
        search_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "b-form-submit"))
        )
        search_button.click()

        # Ожидание загрузки таблицы с делами
        try:
            WebDriverWait(driver, 30).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "#b-cases tbody")
            )
        except TimeoutException:
            return [{"error": "Таблица с делами не загрузилась"}]

        # Сбор ссылок на дела
        try:
            case_links = [case.get_attribute("href") for case in WebDriverWait(driver, 60).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, ".num_case")
            )]
        except TimeoutException:
            return [{"error": "Ссылки на дела не найдены"}]

        if not case_links:
            return [{"error": "Дела не найдены"}]

        logging.info(f"Найдено дел: {len(case_links)}")
        case_info = [get_case_data(url) for url in case_links]
        return case_info
    except Exception as e:
        return [{"error": f"Ошибка: {str(e)}"}]
    finally:
        if driver:
            driver.quit()


@bot.message_handler(commands=['start'])
def start_message(message):
    """Обработчик команды /start"""
    bot.send_message(message.chat.id, "Введите номер участника дела или название компании:")

@bot.message_handler(func=lambda message: True)
def handle_participant_query(message):
    """Запускаем парсинг в отдельном потоке"""
    thread = threading.Thread(target=parse_and_send_file, args=(message,))
    thread.start()

def parse_and_send_file(message):
    """Функция выполняет парсинг и отправляет файл"""
    global is_parsing
    with lock:
        if is_parsing:
            bot.send_message(message.chat.id, "⏳ Уже выполняется запрос. Подождите.")
            return
        is_parsing = True

    participant_query = message.text
    bot.send_message(message.chat.id, f"🔍 Ищу дела для: {participant_query}...")

    try:
        case_info = get_case_info(participant_query)

        if "error" in case_info[0]:
            bot.send_message(message.chat.id, case_info[0]["error"])
        else:
            filename = f"cases_{sanitize_filename(participant_query)}.xlsx"
            file_path = save_to_excel(case_info, filename)

            with open(file_path, "rb") as file:
                bot.send_document(message.chat.id, file, caption="📂 Ваш файл с делами готов!")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")

    with lock:
        is_parsing = False


if __name__ == "__main__":
    # url = "https://kad.arbitr.ru/Card/878c21b7-c8f1-4f99-a047-6893407866d9"
    # parse_case_info(url)
    # participant_number = '1659128597'
    # get_case_info(participant_number)
    while True:
        print("Bot is starting...")
        try:
            bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"Ошибка в работе бота: {e}")
            time.sleep(5)  # Даем паузу перед повторным запуском
