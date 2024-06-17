import configparser
from typing import List
import configparser
from datetime import datetime, timedelta

STATIC_EMBASSY_INFO = {
    # [EMBASSY (COUNTRY CODE), FACILITY_ID (EMBASSY ID), "Continue in different languages"],
    "en-am-yer": ["en-am", 122, "Continue"], # English - Armenia - YEREVAN
    "es-co-bog": ["es-co", 25, "Continuar"], # Spanish - Colombia - Bogotá
    "en-ca-cal": ["en-ca", 89, "Continue"], # English - Canada - Calgary
    "en-ca-hal": ["en-ca", 90, "Continue"], # English - Canada - Halifax
    "en-ca-mon": ["en-ca", 91, "Continue"], # English - Canada - Montreal
    "en-ca-ott": ["en-ca", 92, "Continue"], # English - Canada - Ottawa
    "en-ca-que": ["en-ca", 93, "Continue"], # English - Canada - Quebec City
    "en-ca-tor": ["en-ca", 94, "Continue"], # English - Canada - Toronto
    "en-ca-van": ["en-ca", 95, "Continue"], # English - Canada - Vancouver
}

DATE_FORMAT = "%Y-%m-%d"

class EmbassyConfig:
    embassy_short_name: str
    appointment_period_start: str
    appointment_period_end: str
    should_reschedule: bool
    embassy_info: List

    def __init__(self, embassy_short_name:str, appointment_period_start: str, appointment_period_end: str, should_reschedule: bool):
        self.embassy_short_name = embassy_short_name
        self.appointment_period_start = appointment_period_start
        self.appointment_period_end = appointment_period_end
        self.should_reschedule = should_reschedule
        self.embassy_info = STATIC_EMBASSY_INFO[embassy_short_name]

    def get_continue_regex(self) -> str:
        return self.embassy_info[2]
        
    def get_sign_in_link(self) -> str:
        return f"https://ais.usvisa-info.com/{self.embassy_info[0]}/niv/users/sign_in"

    def get_sign_out_link(self) -> str:
        return f"https://ais.usvisa-info.com/{self.embassy_info[0]}/niv/users/sign_out"

    def get_appointment_url(self, schedule_id) -> str:
        return f"https://ais.usvisa-info.com/{self.embassy_info[0]}/niv/schedule/{schedule_id}/appointment"

    def get_date_url(self, schedule_id) -> str:
        return f"https://ais.usvisa-info.com/{self.embassy_info[0]}/niv/schedule/{schedule_id}/appointment/days/{self.embassy_info[1]}.json?appointments[expedite]=false"

    def get_time_url(self, schedule_id) -> str:
        return f"https://ais.usvisa-info.com/{self.embassy_info[0]}/niv/schedule/{schedule_id}/appointment/times/{self.embassy_info[1]}.json?date=%s&appointments[expedite]=false"

class VisaConfig:

    username: str
    password: str

    schedule_id: str
    telegram_bot_token: str
    telegram_chat_id: str

    retry_time_l_bound: float
    retry_time_u_bound: float
    work_limit_time: float
    work_cooldown_time: float
    ban_cooldown_time: float
    
    embassies: List[EmbassyConfig]

    def __init__(self, config_file: str):
        config = configparser.ConfigParser()
        config.read(config_file)

        self.username = config['PERSONAL_INFO']['USERNAME']
        self.password = config['PERSONAL_INFO']['PASSWORD']
        self.schedule_id = config['PERSONAL_INFO']['SCHEDULE_ID']
        self.telegram_bot_token = config['NOTIFICATION']['TELEGRAM_BOT_TOKEN']
        self.telegram_chat_id = config['NOTIFICATION']['TELEGRAM_CHAT_ID']
        
        self.retry_time_l_bound = config['TIME'].getfloat('RETRY_TIME_L_BOUND')
        self.retry_time_u_bound = config['TIME'].getfloat('RETRY_TIME_U_BOUND')
        self.work_limit_time = config['TIME'].getfloat('WORK_LIMIT_TIME')
        self.work_cooldown_time = config['TIME'].getfloat('WORK_COOLDOWN_TIME')
        self.ban_cooldown_time = config['TIME'].getfloat('BAN_COOLDOWN_TIME')

        
        self.embassies = []

        for embassy_section in [section for section in config.sections() if section.count('EMBASSY') > 0]:
            embassy_code = config[embassy_section]['EMBASSY_CODE'] 

            period_start = self._parse_config_date(config[embassy_section]['PERIOD_START'])
            period_end = self._parse_config_date(config[embassy_section]['PERIOD_END'])
            should_reschedule = config[embassy_section].getboolean('SHOULD_RESCHEDULE', False)

            self.embassies.append(EmbassyConfig(embassy_code, period_start, period_end, should_reschedule))
        
    def _parse_config_date(self, config_date: str) -> str:
        calculated_period = config_date
        if config_date.count("$DATE$") > 0:
            days_to_add = config_date.split('+')[1].strip()
            calculated_period = (datetime.today() + timedelta(int(days_to_add))).strftime(DATE_FORMAT)
        #print(f'Period - {calculated_period}')
        return calculated_period
