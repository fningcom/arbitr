from flask import Flask, jsonify, request
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, NoSuchElementException
import time
from bs4 import BeautifulSoup
import logging
from extract_pdf import extract_text_from_pdf, init_driver, download_file_ics_by_url

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


def case_pdf_url(url):
    result = extract_text_from_pdf(url)
    if not result:
        print("Повторная попытка загрузки файла...")
        result = extract_text_from_pdf(url)
    return result

def pars_additional_data(code):
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

            # Поиск ссылки на PDF
            case_pdf = None
            if h2:
                pdf_link = h2.find("a", href=True)
                if pdf_link and "О принятии искового заявления" in pdf_link.get_text(strip=True):
                    case_pdf = case_pdf_url(pdf_link["href"])


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
            case_data["pdf"] = case_pdf  # Добавляем ссылку на PDF, если она есть

        cases.append(case_data)

    return cases


def parse_case_info(case_url):
    # global driver
    driver = None
    try:
        driver = init_driver("downloads")

        logging.info(f"Парсим дело: {case_url}")
        driver.get(case_url)
        time.sleep(5)
        case = {}

        try:
            case['case_number'] = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.crumb .js-case-header-case_num"))
            ).text
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
            case['chronology'] = pars_additional_data(code.get_attribute("outerHTML")) if code else "Нет данных"
        except:
            case['chronology'] = "Ошибка загрузки хронологии"

        try:
            calendar_link = driver.find_element(By.CSS_SELECTOR, "li.case-date a").get_attribute("href")
            base_url = "https://kad.arbitr.ru"
            calendar_url = base_url + calendar_link if calendar_link.startswith('/') else calendar_link
            case['calendar_url'] = calendar_url
            logging.info("Скачиваем календарь...")
            download_file_ics_by_url(calendar_url)
        except:
            case['calendar_url'] = "Ссылка на календарь не найдена"
        case['case_url'] = case_url
        return case
    except Exception as e:
        return {"error": f"Ошибка: {str(e)}"}

    finally:
        if driver:
            print("Закрываем WebDriver...")
            driver.quit()  # Безопасное закрытие WebDriver

def get_case_info(participant_number):
    driver = None
    try:
        driver = init_driver("downloads")

        logging.info(f"Запрос информации о делах для участника: {participant_number}")
        driver.get("https://kad.arbitr.ru")
        try:
            close_popup = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "js-promo_notification-popup-close"))
            )
            close_popup.click()
            logging.info("Всплывающее окно закрыто...")
        except:
            logging.info("Всплывающее окно не появилось...")
            pass

        participant_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea.g-ph"))
        )
        participant_input.send_keys(participant_number)
        time.sleep(1)
        logging.info("Выполняем поиск...")
        logging.info("Ждем 30 секунд загрузки дел...")
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
        case_info = [parse_case_info(url) for url in case_links]

        return case_info
    except Exception as e:
        return {"error": f"Ошибка: {str(e)}"}

    finally:
        if driver:
            print("Закрываем WebDriver...")
            driver.quit()  # Безопасное закрытие WebDriver

@app.route('/get_cases', methods=['GET'])
def get_cases():
    participant_number = request.args.get('participant_number')
    if not participant_number:
        return jsonify({"error": "Номер участника не передан"}), 400
    case_info = get_case_info(participant_number)
    return jsonify(case_info)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=9012)