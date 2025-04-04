import os
import shutil
import time
import re
import json
import pdfplumber
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

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

# Пример вызова
# url = "https://kad.arbitr.ru/Kad/PdfDocument/ea85af4e-a445-4d5b-a41e-9e8eeeaeaa7c/170aa1cd-54b4-45bb-bae2-e84ceb9a18ca/A58-9052-2024_20241015_Opredelenie.pdf"
# print(extract_text_from_pdf(url))
