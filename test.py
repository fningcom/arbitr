import os
import time
import logging
import tempfile
from flask import Flask, jsonify, request
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from contextlib import contextmanager
from extract_pdf import extract_text_from_pdf

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def load_driver(download_path):
    logging.info("Запуск браузера...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36")

    prefs = {
        "download.default_directory": download_path,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

@contextmanager
def create_driver():
    download_path = os.path.abspath("downloads")
    os.makedirs(download_path, exist_ok=True)
    driver = load_driver(download_path)
    try:
        yield driver, download_path
    finally:
        logging.info("Закрытие браузера (локально)...")
        driver.quit()

def pars_additional_data(driver, code, download_path):
    soup = BeautifulSoup(code, "html.parser")
    cases = []

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

            case_pdf = None
            if h2:
                pdf_link = h2.find("a", href=True)
                if pdf_link and "О принятии искового заявления" in pdf_link.get_text(strip=True):
                    case_pdf = extract_text_from_pdf(pdf_link["href"])
        else:
            case_subject = case_result_text = "Нет данных"
            case_pdf = None

        case_data = {
            "date": case_date,
            "type": case_type,
            "subject": case_subject,
            "result": case_result_text
        }

        if case_pdf:
            case_data["pdf"] = case_pdf

        cases.append(case_data)

    return cases

def parse_case_info(driver, case_url, download_path):
    logging.info(f"Парсим дело: {case_url}")
    driver.get(case_url)
    time.sleep(2)
    case = {}

    try:
        case['case_number'] = driver.find_element(By.CSS_SELECTOR, "ul.crumb .js-case-header-case_num").text
    except:
        case['case_number'] = "Не удалось найти номер дела"


    try:
        case['next_hearing'] = driver.find_element(By.CSS_SELECTOR, ".b-instanceAdditional").text
    except:
        case['next_hearing'] = "Следующее заседание: Нет даты"

    try:
        plus_button = WebDriverWait(driver, 45).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".b-collapse.js-collapse"))
        )
        plus_button.click()
        time.sleep(2)
        code = WebDriverWait(driver, 45).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#chrono_list_content"))
        )
        case['chronology'] = pars_additional_data(driver, code.get_attribute("outerHTML"), download_path)
    except:
        case['chronology'] = "Ошибка загрузки хронологии"

    try:
        calendar_link = driver.find_element(By.CSS_SELECTOR, "li.case-date a").get_attribute("href")
        base_url = "https://kad.arbitr.ru"
        case['calendar_url'] = base_url + calendar_link if calendar_link.startswith('/') else calendar_link
    except:
        case['calendar_url'] = "Ссылка на календарь не найдена"

    case['case_url'] = case_url
    return case

def get_case_info(participant_number):
    logging.info(f"Запрос информации о делах для участника: {participant_number}")
    with create_driver() as (driver, download_path):
        driver.get("https://kad.arbitr.ru")
        try:
            close_popup = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "js-promo_notification-popup-close"))
            )
            close_popup.click()
            logging.info("Всплывающее окно закрыто...")
        except:
            logging.info("Всплывающее окно не появилось...")

        participant_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea.g-ph"))
        )
        participant_input.send_keys(participant_number)
        time.sleep(1)
        logging.info("Выполняем поиск...")

        search_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "b-form-submit"))
        )
        search_button.click()

        try:
            WebDriverWait(driver, 30).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "#b-cases tbody")
            )
        except TimeoutException:
            return [{"error": "Таблица с делами не загрузилась"}]

        try:
            case_links = [case.get_attribute("href") for case in WebDriverWait(driver, 60).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, ".num_case")
            )]
        except TimeoutException:
            return [{"error": "Ссылки на дела не найдены"}]

        if not case_links:
            return [{"error": "Дела не найдены"}]

        logging.info(f"Найдено дел: {len(case_links)}")
        return [parse_case_info(driver, url, download_path) for url in case_links]

@app.route('/get_cases', methods=['GET'])
def get_cases():
    participant_number = request.args.get('participant_number')
    if not participant_number:
        return jsonify({"error": "Номер участника не передан"}), 400
    case_info = get_case_info(participant_number)
    return jsonify(case_info)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=9012)
