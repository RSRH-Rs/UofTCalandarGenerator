import json
import requests


def get_courses_info(
    cookies_dict: dict, token: str, only_course_code: bool = False
) -> list:
    course_codes_list = []

    TIMETABLEAPI = "https://acorn.utoronto.ca/sws/rest/timetable/viewTimetable"
    headers = {
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": token,
    }

    registration_infos_response = requests.get(
        url="https://acorn.utoronto.ca/sws/rest/enrolment/current-registrations",
        cookies=cookies_dict,
    )
    registration_infos = registration_infos_response.text

    registration_info_post_code = (
        json.loads(registration_infos)[0].get("post").get("code")
    )
    registration_info_session_code = json.loads(registration_infos)[0].get(
        "sessionCode"
    )

    data = {
        "code": registration_info_session_code,
        "posts": [
            {
                "code": registration_info_post_code,
            }
        ],
    }

    response = requests.post(
        TIMETABLEAPI,
        headers=headers,
        data=json.dumps(data),
        cookies=cookies_dict,
    )
    response = json.loads(response.text)

    courses_infos = (
        response.get("schedule").get("registrations")[0].get("academicActivitiesList")
    )

    if not only_course_code:
        return courses_infos

    for course in courses_infos:
        course_codes_list.append(course.get("code"))

    return course_codes_list
