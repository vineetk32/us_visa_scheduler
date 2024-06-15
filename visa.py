#!.venv/bin/python
import time
import json
import random
import requests
import configparser
import asyncio
import traceback
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from webdriver_manager.core.utils import ChromeType
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException

from embassy import *
from telegram_client import TelegramClient

config = configparser.ConfigParser()
config.read('config.ini')

# Personal Info:
# Account and current appointment info from https://ais.usvisa-info.com
USERNAME = config['PERSONAL_INFO']['USERNAME']
PASSWORD = config['PERSONAL_INFO']['PASSWORD']
# Find SCHEDULE_ID in re-schedule page link:
# https://ais.usvisa-info.com/en-am/niv/schedule/{SCHEDULE_ID}/appointment
SCHEDULE_ID = config['PERSONAL_INFO']['SCHEDULE_ID']
# Target Period:
TELEGRAM_BOT_TOKEN = config['NOTIFICATION']['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = config['NOTIFICATION']['TELEGRAM_CHAT_ID']

# Embassy Section:
YOUR_EMBASSY = config['PERSONAL_INFO']['YOUR_EMBASSY'] 
EMBASSY = Embassies[YOUR_EMBASSY][0]
FACILITY_ID = Embassies[YOUR_EMBASSY][1]
REGEX_CONTINUE = Embassies[YOUR_EMBASSY][2]

# Time Section:
SECS_PER_MINUTE = 60
SECS_PER_HOUR = 60 * SECS_PER_MINUTE
DATE_FORMAT = "%Y-%m-%d"

# Time between steps (interactions with forms)
STEP_TIME = 0.5
# Time between retries/checks for available dates (seconds)
RETRY_TIME_L_BOUND = config['TIME'].getfloat('RETRY_TIME_L_BOUND')
RETRY_TIME_U_BOUND = config['TIME'].getfloat('RETRY_TIME_U_BOUND')
# Cooling down after WORK_LIMIT_TIME hours of work (Avoiding Ban)
WORK_LIMIT_TIME = config['TIME'].getfloat('WORK_LIMIT_TIME')
WORK_COOLDOWN_TIME = config['TIME'].getfloat('WORK_COOLDOWN_TIME')
# Temporary Banned (empty list): wait COOLDOWN_TIME hours
BAN_COOLDOWN_TIME = config['TIME'].getfloat('BAN_COOLDOWN_TIME')

SIGN_IN_LINK = f"https://ais.usvisa-info.com/{EMBASSY}/niv/users/sign_in"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment"
DATE_URL = f"https://ais.usvisa-info.com/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
SIGN_OUT_LINK = f"https://ais.usvisa-info.com/{EMBASSY}/niv/users/sign_out"

JS_SCRIPT = ("var req = new XMLHttpRequest();"
             f"req.open('GET', '%s', false);"
             "req.setRequestHeader('Accept', 'application/json, text/javascript, */*; q=0.01');"
             "req.setRequestHeader('X-Requested-With', 'XMLHttpRequest');"
             f"req.setRequestHeader('Cookie', '_yatri_session=%s');"
             "req.send(null);"
             "return req.responseText;")

TELEGRAM_BOT = TelegramClient(TELEGRAM_BOT_TOKEN)

#print(f"Date URL - {DATE_URL}")
#print(f"Time URL - {TIME_URL}")

def parse_config_date(config_date: str) -> str:
    calculated_period = config_date
    if config_date.count("$DATE$") > 0:
        days_to_add = config_date.split('+')[1].strip()
        calculated_period = (datetime.today() + timedelta(int(days_to_add))).strftime(DATE_FORMAT)
    #print(f'Period - {calculated_period}')
    return calculated_period

def send_notification(title, msg):
    print(f"Sending notification!")
    try:
        asyncio.run(TELEGRAM_BOT.send_message(chat_id=TELEGRAM_CHAT_ID, message=f"*{title}*\n{msg}"))
    except Exception as e:
        print(f"Caught exception : {e}")

def auto_action(label, find_by, el_type, action, value, sleep_time=0):
    print("\t"+ label +":", end="")
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

def login():
    count = 1
    MAX_RETRIES = 3
    last_exception_message = ''
    while count < MAX_RETRIES:
        try:
            start_process()
            return
        except Exception as e:
            info_logger(LOG_FILE_NAME, f"Failed to login! {e}, {traceback.format_exc()}. Retries - {count}/{MAX_RETRIES}.")
            count += 1
            time.sleep(random.randint(RETRY_TIME_L_BOUND, RETRY_TIME_U_BOUND))
            last_exception_message = str(e)
    raise RuntimeError(f"Failed to login after {count} / {MAX_RETRIES} attempts: {last_exception_message}. Exiting.")

def start_process():
    # Bypass reCAPTCHA
    driver.get(SIGN_IN_LINK)
    time.sleep(STEP_TIME)
    title = driver.title
    if title.count("construction") > 0:
        raise RuntimeError(f"Site not available: {title}")
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))
    auto_action("Click bounce", "xpath", '//a[@class="down-arrow bounce"]', "click", "", STEP_TIME)
    auto_action("Email", "id", "user_email", "send", USERNAME, STEP_TIME)
    auto_action("Password", "id", "user_password", "send", PASSWORD, STEP_TIME)
    auto_action("Privacy", "class", "icheckbox", "click", "", STEP_TIME)
    auto_action("Enter Panel", "name", "commit", "click", "", STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), '" + REGEX_CONTINUE + "')]")))
    print("\n\tlogin successful!\n")

def reschedule(date):
    time = get_time(date)
    driver.get(APPOINTMENT_URL)
    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": APPOINTMENT_URL,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }
    data = {
        "utf8": driver.find_element(by=By.NAME, value='utf8').get_attribute('value'),
        "authenticity_token": driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value'),
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": time,
    }
    r = requests.post(APPOINTMENT_URL, headers=headers, data=data)
    if(r.text.find('Successfully Scheduled') != -1):
        title = "SUCCESS"
        msg = f"Rescheduled Successfully! {date} {time}"
    else:
        title = "FAIL"
        msg = f"Reschedule Failed!!! {date} {time}"
    return [title, msg]


def get_date():
    # Requesting to get the whole available dates
    session = driver.get_cookie("_yatri_session")["value"]
    script = JS_SCRIPT % (str(DATE_URL), session)
    content = driver.execute_script(script)
    dates = []
    if (content.count('html') > 0):
        print("Found non-json response, skipping.")
        return dates
    try:
        dates = json.loads(content)
    except Exception as e:
        info_logger(LOG_FILE_NAME, f"Failed to decode {content}: {e}, {traceback.format_exc()}")
    return dates

def get_time(date):
    time_url = TIME_URL % date
    session = driver.get_cookie("_yatri_session")["value"]
    script = JS_SCRIPT % (str(time_url), session)
    content = driver.execute_script(script)
    data = json.loads(content)
    time = data.get("available_times")[-1]
    print(f"Got time successfully! {date} {time}")
    return time


def is_logged_in():
    content = driver.page_source
    if(content.find("error") != -1):
        return False
    return True


def get_available_date(dates):
    # Evaluation of different available dates
    def is_in_period(date, PSD, PED):
        new_date = datetime.strptime(date, DATE_FORMAT)
        result = ( PED > new_date and new_date > PSD )
        # print(f'{new_date.date()} : {result}', end=", ")
        return result
    
    PED = datetime.strptime(PERIOD_END, DATE_FORMAT)
    PSD = datetime.strptime(PERIOD_START, DATE_FORMAT)
    for d in dates:
        date = d.get('date')
        if is_in_period(date, PSD, PED):
            return date
    print(f"\n\nNo available dates between ({PSD.date()}) and ({PED.date()})!")        

def get_earliest_date(dates, earliest_date: str) -> str:
    earliest_date_value = datetime.strptime(earliest_date, DATE_FORMAT)
    for date in dates:
        date_value = datetime.strptime(date.get('date'), DATE_FORMAT)
        if (earliest_date_value > date_value):
            earliest_date = date.get('date')
            earliest_date_value = date_value
    return earliest_date

def info_logger(file_path, log):
    # file_path: e.g. "log.txt"
    print(log)
    with open(file_path, "a") as file:
        file.write(str(datetime.now().time()) + ":\n" + log + "\n")

options = Options()
options.add_argument("--headless=new")
options.binary_location = "/usr/bin/chromium-browser"
driver = webdriver.Chrome(service=ChromeService(executable_path="/usr/lib/chromium-browser/chromedriver"), options=options)

PERIOD_START = parse_config_date(config['PERSONAL_INFO']['PERIOD_START'])
PERIOD_END = parse_config_date(config['PERSONAL_INFO']['PERIOD_END'])

if __name__ == "__main__":
    first_loop = True
    MAX_BAN_COUNT = 3
    while 1:
        LOG_FILE_NAME = "logs/log_" + str(datetime.now().date()) + ".txt"
        try:
            if first_loop:
                t0 = time.time()
                total_time = 0
                tries = 1
                possible_ban_count = 1
                login()
                first_loop = False
                earliest_date = '2038-11-26'
            else:
                # Sleep from the previous attempt
                RETRY_WAIT_TIME = random.randint(RETRY_TIME_L_BOUND, RETRY_TIME_U_BOUND)
                msg = "Retry Wait Time: "+ str(RETRY_WAIT_TIME)+ " seconds"
                info_logger(LOG_FILE_NAME, msg)
                time.sleep(RETRY_WAIT_TIME)

            tries += 1
            info_logger(LOG_FILE_NAME, "-" * 60 + f"\nRequest count: {tries}, Log time: {datetime.today()}\n")
            dates = get_date()
            earliest_date = get_earliest_date(dates, earliest_date)
            if not dates:
                # Ban Situation
                possible_ban_count += 1
                info_logger(LOG_FILE_NAME, "No dates found!")
                if (possible_ban_count >= MAX_BAN_COUNT):
                    msg = f"List is empty after {possible_ban_count} / {MAX_BAN_COUNT} tries, exiting.\n\tEarliest date found - {earliest_date}, tries - {tries}"
                    info_logger(LOG_FILE_NAME, msg)
                    send_notification("INFO", msg)
                    break
            else:
                # Print Available dates:
                msg = "Available dates:\n "
                possible_ban_count = 1
                for d in dates:
                    msg = msg + "%s" % (d.get('date')) + ", "
                info_logger(LOG_FILE_NAME, msg)
                date = get_available_date(dates)
                if date:
                    # A good date to schedule for
                    END_MSG_TITLE, msg = reschedule(date)
                    send_notification(END_MSG_TITLE, msg)
                    break
                t1 = time.time()
                total_time = t1 - t0
                info_logger(LOG_FILE_NAME, "\nWorking Time:  ~ {:.2f} minutes".format(total_time/SECS_PER_MINUTE))
                if total_time > WORK_LIMIT_TIME * SECS_PER_HOUR:
                    send_notification("STATUS", f"After {total_time/SECS_PER_MINUTE:.2f} minutes - \nEarliest date found - {earliest_date}, tries - {tries}")
                    break
        except Exception as e:
            # Exception Occured
            msg = f"Exiting after exception: {e}"
            send_notification("EXCEPTION", msg)
            info_logger(LOG_FILE_NAME, msg)
            info_logger(LOG_FILE_NAME,traceback.format_exc())
            break
info_logger(LOG_FILE_NAME, msg)
driver.get(SIGN_OUT_LINK)
driver.stop_client()
driver.quit()
