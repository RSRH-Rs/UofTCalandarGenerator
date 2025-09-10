import requests
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from config import *


def login_utoronto_and_get_tokens():
    # Chrome settings
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # hide window
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-notifications")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        print("正在访问登录页面...")
        driver.get("https://acorn.utoronto.ca/")

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )

        # input username and pwd
        username = driver.find_element(By.ID, "username")
        password = driver.find_element(By.ID, "password")

        # 账号密码在这换
        username.send_keys(UTUSERNAME)
        password.send_keys(UTPASSWORD)

        login_button = driver.find_element(By.NAME, "_eventId_proceed")
        login_button.click()
        current_url = driver.current_url
        if "idpz.utorauth.utoronto.ca" in current_url:
            print("账号或密码错误，请检查后重试。")
            return None, None
        else:
            print("登录成功！")

        print("等待登录完成...")
        time.sleep(1)

        try:
            continue_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "continue"))
            )
            continue_btn.click()
            print("检测到并处理了额外的安全验证步骤")
        except:
            print("未检测到额外的安全验证步骤")

        print("等待信任设备按钮出现...")
        try:
            trust_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.ID, "trust-browser-button"))
            )
            print("找到信任设备按钮，准备点击...")

            trust_button.click()
            print("已点击信任设备按钮")

            time.sleep(3)

        except TimeoutException:
            print("未找到信任设备按钮")

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # get cookies
        cookies = driver.get_cookies()
        cookies_dict = {cookie["name"]: cookie["value"] for cookie in cookies}

        # get X-XSRF-TOKEN
        xsrf_token = None
        if "XSRF-TOKEN" in cookies_dict:
            xsrf_token = cookies_dict["XSRF-TOKEN"]
        else:
            # localStorage get token
            try:
                xsrf_token = driver.execute_script(
                    "return window.localStorage.getItem('X-XSRF-TOKEN');"
                )
            except:
                pass

        print("\n成功获取到以下信息:")
        print("Cookies:", json.dumps(cookies_dict, indent=2))
        print("X-XSRF-TOKEN:", xsrf_token)
        print("=" * 80)

        return cookies_dict, xsrf_token

    except Exception as e:
        print(f"登录过程中出现错误: {str(e)}")
        return None, None
    finally:
        driver.quit()


cookies_dict, token = login_utoronto_and_get_tokens()


url = "https://acorn.utoronto.ca/sws/rest/timetable/viewTimetable"

headers = {
    "Content-Type": "application/json",
    "X-XSRF-TOKEN": token,
}

registration_infos_response = requests.get(
    url="https://acorn.utoronto.ca/sws/rest/enrolment/current-registrations",
    cookies=cookies_dict,
)
registration_infos = registration_infos_response.text
registration_info_post_code = json.loads(registration_infos)[0].get("post").get("code")
registration_info_session_code = json.loads(registration_infos)[0].get("sessionCode")
data = {
    "code": registration_info_session_code,
    "posts": [
        {
            "code": registration_info_post_code,
        }
    ],
}
all_courses = {}
response = requests.post(
    url, headers=headers, data=json.dumps(data), cookies=cookies_dict
)
response = json.loads(response.text)
courses_infos = (
    response.get("schedule").get("registrations")[0].get("academicActivitiesList")
)
for course in courses_infos:
    print(course.get("code"))
