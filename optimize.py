import os
import re
import threading
import time
import logging
import shutil
import json

import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import pdfplumber
import telebot
from telebot import types

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Конфигурация
CONFIG = {
    "SAVE_PATH": "downloads",
    "ICS_PATH": "ics",
    "TELEGRAM_TOKEN": "7900071646:AAHIi93du6_RfCzGIjE02FlZyE1XZ0VGBK8",
    "WAIT_TIMEOUT": 30,
    "MAX_PDF_WAIT": 30,
    "USER_AGENT": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36"
}

# Создаем необходимые директории
os.makedirs(CONFIG["SAVE_PATH"], exist_ok=True)
os.makedirs(CONFIG["ICS_PATH"], exist_ok=True)

# Инициализация бота
bot = telebot.TeleBot(CONFIG["TELEGRAM_TOKEN"])
is_parsing = False
lock = threading.Lock()


class WebDriverManager:
    @staticmethod
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
        options.add_argument(f"user-agent={CONFIG['USER_AGENT']}")

        prefs = {
            "download.default_directory": download_folder,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver


class FileUtils:
    @staticmethod
    def sanitize_filename(filename):
        return re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)

    @staticmethod
    def extract_date(text):
        match = re.search(r"\d{2}\.\d{2}\.\d{4}", text)
        return match.group(0) if match else "Нет даты"

    @staticmethod
    def normalize_keyword(keyword):
        spaced_keyword = " ".join(keyword)
        return rf"(?:{keyword}:|{spaced_keyword}:)"


class PDFProcessor:
    @staticmethod
    def process_pdf(pdf_path):
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "\n".join(
                    page.extract_text() for page in pdf.pages
                    if page.extract_text()
                )
            return full_text
        except Exception as e:
            logging.error(f"Error processing PDF: {e}")
            return None

    @staticmethod
    def extract_sections(text):
        if not text:
            return {"established": "", "determined": "", "full": ""}

        ustanovil_regex = FileUtils.normalize_keyword("УСТАНОВИЛ")
        opredelil_regex = FileUtils.normalize_keyword("ОПРЕДЕЛИЛ")

        result = {
            "established": "",
            "determined": "",
            "full": text
        }

        # Поиск "УСТАНОВИЛ:"
        match = re.search(
            rf"{ustanovil_regex}(.*?)(?:{opredelil_regex}|$)",
            text,
            re.DOTALL
        )
        if match:
            result["established"] = match.group(1).strip()

        # Поиск "ОПРЕДЕЛИЛ:"
        match = re.search(rf"{opredelil_regex}(.*)", text, re.DOTALL)
        if match:
            result["determined"] = match.group(1).strip()

        return result


class KadArbitrParser:
    def __init__(self):
        self.driver = None

    def __enter__(self):
        self.driver = WebDriverManager.init_driver(CONFIG["SAVE_PATH"])
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver.quit()

    def get_case_info(self, participant_number):
        try:
            self._navigate_to_site()
            self._search_participant(participant_number)
            case_links = self._get_case_links()

            if not case_links:
                return [{"error": "Дела не найдены"}]

            logging.info(f"Найдено дел: {len(case_links)}")
            return [self._parse_case(url) for url in case_links]

        except Exception as e:
            logging.error(f"Error in get_case_info: {e}")
            return [{"error": f"Ошибка: {str(e)}"}]

    def _navigate_to_site(self):
        self.driver.get("https://kad.arbitr.ru")
        try:
            WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "js-promo_notification-popup-close"))
            ).click()
            logging.info("Всплывающее окно закрыто")
        except Exception:
            logging.info("Всплывающее окно не появилось")

    def _search_participant(self, participant_number):
        WebDriverWait(self.driver, CONFIG["WAIT_TIMEOUT"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea.g-ph"))
        ).send_keys(participant_number)

        time.sleep(1)

        WebDriverWait(self.driver, CONFIG["WAIT_TIMEOUT"]).until(
            EC.element_to_be_clickable((By.ID, "b-form-submit"))
        ).click()

    def _get_case_links(self):
        try:
            WebDriverWait(self.driver, CONFIG["WAIT_TIMEOUT"]).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "#b-cases tbody")
            )
            return [
                case.get_attribute("href") for case in
                WebDriverWait(self.driver, 60).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, ".num_case")
                )
            ]
        except TimeoutException:
            logging.error("Не удалось загрузить список дел")
            return []

    def _parse_case(self, case_url):
        try:
            self.driver.get(case_url)
            time.sleep(5)  # Даем странице время на загрузку

            case = {
                "case_number": self._get_case_number(),
                "next_hearing": self._get_next_hearing(),
                "plaintiff": self._get_participant(".plaintiffs"),
                "defendant": self._get_participant(".defendants"),
                "case-date": self._get_case_date(),
                "chronology": self._get_chronology(),
                "case_url": case_url
            }

            # Добавляем данные из PDF, если есть
            pdf_data = self._get_pdf_data()
            if pdf_data:
                case.update(pdf_data)

            return case

        except Exception as e:
            logging.error(f"Error parsing case {case_url}: {e}")
            return {"error": f"Ошибка парсинга дела: {str(e)}"}

    def _get_case_number(self):
        try:
            return WebDriverWait(self.driver, CONFIG["WAIT_TIMEOUT"]).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.crumb .js-case-header-case_num"))
            ).text
        except:
            return "Не удалось найти номер дела"

    def _get_next_hearing(self):
        try:
            hearing_info = self.driver.find_element(By.CSS_SELECTOR, ".b-instanceAdditional").text
            return FileUtils.extract_date(hearing_info)
        except:
            return "Нет даты"

    def _get_participant(self, selector):
        try:
            return self.driver.find_element(By.CSS_SELECTOR, f"{selector} .container ul li a").text
        except:
            return "Не указан"

    def _get_case_date(self):
        try:
            return self.driver.find_element(By.CSS_SELECTOR, ".case-date").text
        except:
            return "Дата кейса не указана"

    def _get_chronology(self):
        try:
            WebDriverWait(self.driver, CONFIG["WAIT_TIMEOUT"]).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".b-collapse.js-collapse"))
            ).click()
            time.sleep(2)

            code = WebDriverWait(self.driver, CONFIG["WAIT_TIMEOUT"]).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#chrono_list_content"))
            ).get_attribute("outerHTML")

            return self._parse_additional_data(code)
        except Exception as e:
            logging.error(f"Error getting chronology: {e}")
            return "Ошибка загрузки хронологии"

    def _parse_additional_data(self, html):
        soup = BeautifulSoup(html, "html.parser")
        cases = []
        case_data = {}

        for item in soup.find_all("div", class_="b-chrono-item"):
            case_date = item.find("p", class_="case-date").get_text(strip=True) if item.find("p",
                                                                                             class_="case-date") else "Нет данных"
            case_type = item.find("p", class_="case-type").get_text(strip=True) if item.find("p",
                                                                                             class_="case-type") else "Нет данных"

            r_col = item.find("div", class_="r-col")
            if r_col:
                case_subject = r_col.find("p", class_="case-subject").get_text(strip=True) if r_col.find("p",
                                                                                                         class_="case-subject") else "Нет данных"
                case_result = r_col.find("span", class_="js-judges-rollover").get_text(strip=True) if r_col.find("span",
                                                                                                                 class_="js-judges-rollover") else "Нет данных"

                # Проверяем наличие PDF
                if case_type == "Определение":
                    h2 = r_col.find("h2", class_="b-case-result")
                    if h2:
                        pdf_link = h2.find("a", class_="js-case-result-text--doc_link", href=True)
                        if pdf_link:
                            pdf_data = self._process_pdf_link(pdf_link["href"])
                            if pdf_data:
                                case_data.update(pdf_data)

            cases.append(f"{case_date} / {case_type} / {case_subject} / {case_result}")

        case_data["chronology"] = "\n".join(cases)
        return case_data

    def _process_pdf_link(self, pdf_url):
        try:
            self.driver.get(pdf_url)
            time.sleep(5)  # Ждем загрузки PDF

            # Ожидаем загрузки файла
            pdf_file = None
            for _ in range(CONFIG["MAX_PDF_WAIT"]):
                files = [f for f in os.listdir(CONFIG["SAVE_PATH"]) if f.endswith(".pdf")]
                if files:
                    pdf_file = os.path.join(CONFIG["SAVE_PATH"], files[0])
                    break
                time.sleep(1)

            if not pdf_file:
                return None

            # Обрабатываем PDF
            full_text = PDFProcessor.process_pdf(pdf_file)
            if not full_text:
                return None

            # Удаляем временный файл
            os.remove(pdf_file)

            return PDFProcessor.extract_sections(full_text)

        except Exception as e:
            logging.error(f"Error processing PDF: {e}")
            return None


class ExcelGenerator:
    @staticmethod
    def generate_excel(data, filename):
        filename = FileUtils.sanitize_filename(filename)
        filepath = os.path.join(CONFIG["SAVE_PATH"], filename)

        formatted_data = []
        for case in data:
            formatted_data.append({
                "Дело": f"{case.get('case-date', 'Нет данных')} {case.get('case_number', 'Нет данных')}",
                "Юрист": "",
                "Следующее заседание": case.get('next_hearing', 'Нет даты'),
                "Истцы": case.get('plaintiff', 'Не указаны'),
                "Ответчики": case.get('defendant', 'Не указаны'),
                "ИСКОВЫЕ ТРЕБОВАНИЯ": case.get('iskov', ''),
                "Итоговый судебный акт": case.get('itog', ''),
                "Хронология": case.get('chronology', ''),
                "Установил": case.get('established', ''),
                "Определил": case.get('determined', ''),
                "PDF": case.get('full', '')
            })

        df = pd.DataFrame(formatted_data)
        df.to_excel(filepath, index=False)
        return filepath


# Telegram Bot Handlers
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, "Введите номер участника дела или название компании:")


@bot.message_handler(func=lambda message: True)
def handle_participant_query(message):
    thread = threading.Thread(target=parse_and_send_file, args=(message,))
    thread.start()


def parse_and_send_file(message):
    global is_parsing

    with lock:
        if is_parsing:
            bot.send_message(message.chat.id, "⏳ Уже выполняется запрос. Подождите.")
            return
        is_parsing = True

    try:
        participant_query = message.text
        bot.send_message(message.chat.id, f"🔍 Ищу дела для: {participant_query}...")

        with KadArbitrParser() as parser:
            case_info = parser.get_case_info(participant_query)

        if "error" in case_info[0]:
            bot.send_message(message.chat.id, case_info[0]["error"])
        else:
            filename = f"cases_{FileUtils.sanitize_filename(participant_query)}.xlsx"
            file_path = ExcelGenerator.generate_excel(case_info, filename)

            with open(file_path, "rb") as file:
                bot.send_document(message.chat.id, file, caption="📂 Ваш файл с делами готов!")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
        logging.error(f"Error in parse_and_send_file: {e}")

    finally:
        with lock:
            is_parsing = False


if __name__ == "__main__":
    while True:
        try:
            logging.info("Starting bot...")
            bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"Bot error: {e}")
            time.sleep(5)