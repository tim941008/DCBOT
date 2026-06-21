import logging

import aiohttp

from config import COURSE_API_URL, COURSE_SEMESTER

logger = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None


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


def _get_timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=15, connect=5)


async def get_course_api_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(ssl=False)
        _session = aiohttp.ClientSession(connector=connector, timeout=_get_timeout())
    return _session


async def close_course_api_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def fetch_course_data(payload: dict) -> list[dict]:
    try:
        session = await get_course_api_session()
        async with session.post(COURSE_API_URL, json=payload) as response:
            if response.status == 200:
                data = await response.json(content_type=None)
                if isinstance(data, list):
                    return data
                logger.warning("查課 API 回傳格式非清單：%s", type(data).__name__)
                return []
            logger.warning("查課 API 回傳狀態碼：%s", response.status)
    except Exception as error:
        logger.exception("API 請求失敗：%s", error)
    return []
