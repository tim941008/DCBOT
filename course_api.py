import logging

import aiohttp

from config import COURSE_API_URL, COURSE_SEMESTER

logger = logging.getLogger(__name__)


def build_course_payload(course_no: str = "", course_name: str = "") -> dict:
    return {
        "Semester": COURSE_SEMESTER,
        "CourseNo": course_no,
        "CourseName": course_name,
        "CourseTeacher": "",
        "Dimension": "",
        "CourseNotes": "",
        "CampusNotes": "",
        "ForeignLanguage": 0,
        "OnlyIntensive": 0,
        "OnlyGeneral": 0,
        "OnleyNTUST": 0,
        "OnlyMaster": 0,
        "OnlyUnderGraduate": 0,
        "OnlyNode": 0,
        "Language": "zh",
    }


def normalize_course_no(course_no: str) -> str:
    return course_no.strip().upper()


async def fetch_course_data(payload: dict) -> list[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(COURSE_API_URL, json=payload, ssl=False) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning("查課 API 回傳狀態碼：%s", response.status)
    except Exception as error:
        logger.exception("API 請求失敗：%s", error)
    return []
