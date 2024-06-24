#!.venv/bin/python
import time
import json
import random
import requests
from typing import Dict, List
import asyncio
import traceback
import sys
from datetime import datetime
import os

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.common.by import By

from telegram_client import TelegramClient
from config_parser import VisaConfig, EmbassyConfig

# Time between steps (interactions with forms)
STEP_TIME = 0.5

MAX_BAN_COUNT = 3
MAX_LOGIN_RETRIES = 3

SECS_PER_MINUTE = 60
SECS_PER_HOUR = 60 * SECS_PER_MINUTE
DATE_FORMAT = '%Y-%m-%d'
MAX_DATE_STR = '2038-12-12'
MAX_DATE: datetime = datetime.strptime(MAX_DATE_STR, DATE_FORMAT)

# Lockfile to prevent unintentional reschedules
LOCKFILE = '/tmp/visa_appointment_lock'
LOG_FILE_NAME = "logs/log_" + str(datetime.now().date()) + ".txt"

JS_SCRIPT = ("var req = new XMLHttpRequest();"
             "req.open('GET', '%s', false);"
             "req.setRequestHeader('Accept', 'application/json, text/javascript, */*; q=0.01');"
             "req.setRequestHeader('X-Requested-With', 'XMLHttpRequest');"
             "req.setRequestHeader('Cookie', '_yatri_session=%s');"
             "req.send(null);"
             "return req.responseText;")

class ExecutionResult:
    earliest_date: str = MAX_DATE_STR
    result_type: str = ''
    result_message: str = ''
    possible_ban_count: int = 1

def send_notification(telegram_client, telegram_chat_id, title, message):
    print("Sending notification!")
    try:
        asyncio.run(telegram_client.send_message(chat_id=telegram_chat_id, message=f"*{title}*\n{message}"))
    except Exception as ex:
        print(f"Caught exception : {ex}")

def auto_action(driver: webdriver.Chrome, label, find_by, el_type, action, value, sleep_time=0):
    print("\t" + label + ":", end="")
    # Find Element By
    match find_by.lower():
        case 'id':
            item = driver.find_element(By.ID, el_type)
        case 'name':
            item = driver.find_element(By.NAME, el_type)
        case 'class':
            item = driver.find_element(By.CLASS_NAME, el_type)
        case 'xpath':
            item = driver.find_element(By.XPATH, el_type)
        case _:
            return 0
    # Do Action:
    match action.lower():
        case 'send':
            item.send_keys(value)
        case 'click':
            item.click()
        case _:
            return 0
    print("\t\tCheck!")
    if sleep_time:
        time.sleep(sleep_time)

def login(driver: webdriver.Chrome, visa_config: VisaConfig):
    count = 1
    last_exception_message = ''
    while count < MAX_LOGIN_RETRIES:
        try:
            start_process(driver, visa_config)
            return
        except Exception as ex:
            info_logger(LOG_FILE_NAME, f"Failed to login! {ex}, {traceback.format_exc()}. Retries - {count}/{MAX_LOGIN_RETRIES}.")
            count += 1
            time.sleep(random.randint(visa_config.retry_time_l_bound, visa_config.retry_time_u_bound))
            last_exception_message = str(ex)
    raise RuntimeError(f"Failed to login after {count} / {MAX_LOGIN_RETRIES} attempts: {last_exception_message}. Exiting.")

def start_process(driver: webdriver.Chrome, visa_config: VisaConfig):
    # Bypass reCAPTCHA
    driver.get(visa_config.embassies[0].get_sign_in_link())
    time.sleep(STEP_TIME)
    title = driver.title
    if title.count("construction") > 0:
        raise RuntimeError(f"Site not available: {title}")
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))
    auto_action(driver, "Click bounce", "xpath", '//a[@class="down-arrow bounce"]', "click", "", STEP_TIME)
    auto_action(driver, "Email", "id", "user_email", "send", visa_config.username, STEP_TIME)
    auto_action(driver, "Password", "id", "user_password", "send", visa_config.password, STEP_TIME)
    auto_action(driver, "Privacy", "class", "icheckbox", "click", "", STEP_TIME)
    auto_action(driver, "Enter Panel", "name", "commit", "click", "", STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), '" + visa_config.embassies[0].get_continue_regex() + "')]")))
    print("\n\tlogin successful!\n")

def reschedule(driver: webdriver.Chrome, date, schedule_id: str, embassy_config: EmbassyConfig, should_reschedule: bool):
    reschedule_time = get_time(driver, date, embassy_config.get_time_url(schedule_id))
    appointment_url = embassy_config.get_appointment_url(schedule_id)
    driver.get(appointment_url)
    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": appointment_url,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }
    data = {
        # "utf8": driver.find_element(by=By.NAME, value='utf8').get_attribute('value'),
        "authenticity_token": driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value'),
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": embassy_config.get_facility_id(),
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": reschedule_time,
    }
    is_lock_present = os.path.isfile(LOCKFILE)
    info_logger(LOG_FILE_NAME, f'Should reschedule: {should_reschedule}, Lock present: {is_lock_present}')
    if should_reschedule and not is_lock_present:
        r = requests.post(appointment_url, headers=headers, data=data)
        info_logger(LOG_FILE_NAME, f'Reschedule response: {r.text}')
    if should_reschedule and not is_lock_present and r.text.find('Successfully Scheduled') != -1:
        title = "RESCHEDULE_SUCCESS"
        msg = f"{embassy_config.embassy_short_name}: Rescheduled Successfully! {date} {reschedule_time}"
        open(LOCKFILE, 'w').close()
    else:
        title = "RESCHEDULE_FAIL"
        msg = f"{embassy_config.embassy_short_name}: Reschedule Failed! {date} {reschedule_time}"
    return [title, msg]


def get_date(driver: webdriver.Chrome, date_url: str):
    # Requesting to get the whole available dates
    session = driver.get_cookie("_yatri_session")["value"]
    script = JS_SCRIPT % (date_url, session)
    content = driver.execute_script(script)
    dates = []
    if (content.count('html') > 0):
        print("Found non-json response, skipping.")
        return dates
    try:
        dates = json.loads(content)
    except Exception as ex:
        info_logger(LOG_FILE_NAME, f"Failed to decode {content}: {ex}, {traceback.format_exc()}")
    return dates

def get_time(driver: webdriver.Chrome, date, time_url: str):
    time_url = time_url % date
    session = driver.get_cookie("_yatri_session")["value"]
    script = JS_SCRIPT % (str(time_url), session)
    content = driver.execute_script(script)
    data = json.loads(content)
    available_time = data.get("available_times")[-1]
    info_logger(LOG_FILE_NAME, f"Got time successfully! {date} {available_time}")
    return available_time


def is_logged_in(driver: webdriver.Chrome):
    content = driver.page_source
    if content.find("error") != -1:
        return False
    return True

def is_in_period(date: str, period_start: datetime, period_end: datetime) -> bool:
    new_date = datetime.strptime(date, DATE_FORMAT)
    return period_end > new_date and new_date > period_start

def get_available_date(blocked_days: List[str], period_start: str, period_end: str, dates):
    period_end_date = datetime.strptime(period_end, DATE_FORMAT)
    period_start_date = datetime.strptime(period_start, DATE_FORMAT)
    for d in dates:
        date = d.get('date')
        if date in blocked_days:
            info_logger(LOG_FILE_NAME, f"Skipping blocked date: {date}")
            continue
        if is_in_period(date, period_start_date, period_end_date):
            return date
    print(f"\n\nNo available dates between ({period_start_date.date()}) and ({period_end_date.date()})!")
    return None

def info_logger(file_path, log):
    print(log)
    with open(file_path, "a") as file:
        file.write(str(datetime.now().time()) + ":\n" + log + "\n")

def check_embassy(driver: webdriver.Chrome, schedule_id: str, embassy_config: EmbassyConfig):
    dates = get_date(driver, embassy_config.get_date_url(schedule_id))
    result = ExecutionResult()
    if not dates:
        info_logger(LOG_FILE_NAME, "No dates found!")
        result.result_type = 'NO_DATES'
        result.result_message = "No dates found!"
    else:
        # Print Available dates:
        msg = "Available dates:\n "
        for d in dates:
            msg = msg + "%s" % (d.get('date')) + ", "
        info_logger(LOG_FILE_NAME, msg)
        date = get_available_date(embassy_config.blocked_days, embassy_config.appointment_period_start, embassy_config.appointment_period_end, dates)
        result.earliest_date = dates[0].get('date')
        if date:
            result.result_type, result.result_message = reschedule(driver, date, schedule_id, embassy_config, embassy_config.should_reschedule)
    return result

def update_earliest_date_for_embassy(results: Dict[str, ExecutionResult], result: ExecutionResult, embassy_short_name: str):
    previous_earliest_date = datetime.strptime(results[embassy_short_name].earliest_date, DATE_FORMAT)
    curr_earliest_date = datetime.strptime(result.earliest_date, DATE_FORMAT)
    if curr_earliest_date < MAX_DATE:
        # Reset ban count if any dates were found
        results[embassy_short_name].possible_ban_count = 1
    if curr_earliest_date < previous_earliest_date:
        results[embassy_short_name].earliest_date = result.earliest_date

def get_embassy_summary(results: Dict[str, ExecutionResult]) -> str:
    summary_dict = {}
    for embassy, result in results.items():
        summary_dict[embassy] = result.earliest_date
    return str(summary_dict)

def no_dates_all_embassies(results: Dict[str, ExecutionResult]) -> bool:
    for result in results.values():
        if result.possible_ban_count < MAX_BAN_COUNT:
            return False
    return True

def main() -> int:
    options = Options()
    options.add_argument("--headless=new")
    options.binary_location = "/usr/bin/chromium-browser"
    driver = webdriver.Chrome(service=ChromeService(executable_path="/usr/lib/chromium-browser/chromedriver"), options=options)

    config = VisaConfig('config.ini')

    t0 = time.time()
    total_time = 0
    tries = 0

    results = {}
    telegram_client = TelegramClient(config.telegram_bot_token)

    try:
        login(driver, config)
    except Exception as e:
        # Exception Occured
        msg = f"Exiting after exception: {e}"
        send_notification(telegram_client, config.telegram_chat_id, "EXCEPTION", msg)
        info_logger(LOG_FILE_NAME, msg)
        info_logger(LOG_FILE_NAME, traceback.format_exc())
        return -1

    while 1:
        embassy_index = tries % len(config.embassies)
        embassy = config.embassies[embassy_index]
        info_logger(LOG_FILE_NAME, f'Processing {embassy_index}/{len(config.embassies)} - {embassy.embassy_short_name}..')
        result = check_embassy(driver, config.schedule_id, embassy)
        tries += 1

        if embassy.embassy_short_name not in results:
            results[embassy.embassy_short_name] = result

        previous_result = results.get(embassy.embassy_short_name)
        if result.result_type == 'NO_DATES':
            previous_result.possible_ban_count += 1
            if no_dates_all_embassies(results):
                msg = f"List is empty after {previous_result.possible_ban_count} / {MAX_BAN_COUNT} tries, exiting.\n"
                info_logger(LOG_FILE_NAME, msg)
                send_notification(telegram_client, config.telegram_chat_id, "INFO", msg)
                break
        elif result.result_type == 'RESCHEDULE_SUCCESS':
            send_notification(telegram_client, config.telegram_chat_id, result.result_type, result.result_message)
            break
        elif result.result_type == 'RESCHEDULE_FAIL':
            send_notification(telegram_client, config.telegram_chat_id, result.result_type, result.result_message)

        update_earliest_date_for_embassy(results, result, embassy.embassy_short_name)
        t1 = time.time()
        total_time = t1 - t0
        info_logger(LOG_FILE_NAME, f"\nWorking Time:  ~ {(total_time/SECS_PER_MINUTE):.2f} minutes")
        if total_time > config.work_limit_time * SECS_PER_HOUR:
            send_notification(telegram_client, config.telegram_chat_id, "STATUS",
                              f"After {total_time/SECS_PER_MINUTE:.2f} minutes - \nTries - {tries}\n{get_embassy_summary(results)}")
            break

        info_logger(LOG_FILE_NAME, "-" * 60 + f"\nRequest count: {tries}, Log time: {datetime.today()}\n")

        if embassy_index == len(config.embassies) - 1:
            retry_wait_time = random.randint(config.retry_time_l_bound, config.retry_time_u_bound)
            msg = f"Retry Wait Time: {retry_wait_time} seconds"
            info_logger(LOG_FILE_NAME, msg)
            time.sleep(retry_wait_time)

    info_logger(LOG_FILE_NAME, msg)
    driver.get(config.embassies[0].get_sign_out_link())
    driver.stop_client()
    driver.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
