# visa_rescheduler
The visa_rescheduler is a bot for US VISA (usvisa-info.com) appointment rescheduling. This bot can help you reschedule your appointment to your desired time period.

## Prerequisites
- Having a US VISA appointment scheduled already.
- API token for Telegram. If you wish to use the simpler Pushover API instead, You can use this method to send notifications - 

```python
def send_pushover_notification(message):
    payload = {
        'token': PUSHOVER_API_TOKEN,
        'user': PUSHOVER_USER_KEY,
        'message': message
    }
    response = requests.post('https://api.pushover.net/1/messages.json', data=payload)
    if response.status_code != 200:
        print(f"Failed to send notification: {response.text}")
```

## Attention
- Right now, there are lots of unsupported embassies in our repository. A list of supported embassies is presented in the 'embassy.py' file.
- To add a new embassy (using English), you should find the embassy's "facility id." To do this, using google chrome, on the booking page of your account, right-click on the location section, then click "inspect." Then the right-hand window will be opened, highlighting the "select" item. You can find the "facility id" here and add this facility id in the 'embassy.py' file. There might be several facility ids for several different embassies. They can be added too. Please use the picture below as an illustration of the process.
![Finding Facility id](https://github.com/Soroosh-N/us_visa_scheduler/blob/main/_img.png?raw=true)

## Initial Setup
### Pre-requisites
1. Linux
2. Chromium

Neither of these are strictly required, and should only need minor code changes to replace.

### Setup
- Install a virtual environment in the root directory - `python -m venv .venv`
- Run the install script - `scripts/init.sh`

## How to use
- Initial setup!
- Edit information [config.ini.example file]. Then remove the ".example" from file name.
- Edit your push notification accounts information [config.ini.example file].
- The default timing settings (TIME::WORK_LIMIT_TIME) make the script run for ~50 minutes.
- The Selenium logic is not bulletprood, and the Visa website is badly designed. To avoid an exception for one run killing a forever running script, I would recommend the following timing config/scheduling setup - 
    - Keep the WORK_LIMIT_TIME in the config to 0.8 hours
    - Schedule the script to run every hour via cron. For e.g - `11 * * * * /home/vineet/code/us_visa_scheduler/visa_multiple.py`
- As of Jun 2024, appointments in Canadian Embassies were only released everyday around ~3PM to ~3AM PT. Outside of these times, it was common to get no results, failure to log in or even a `503 under construction` error from the website.

## Acknowledgement
Thanks to everyone who participated in this repo. Lots of people are using your excellent product without even appreciating you.
