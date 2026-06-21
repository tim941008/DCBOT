import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

COURSE_API_URL = "https://querycourse.ntust.edu.tw/QueryCourse/api/courses"
COURSE_QUERY_URL = "https://querycourse.ntust.edu.tw/querycourse/#/"
COURSE_SELECTION_URL = "https://courseselection.ntust.edu.tw/Home/Index"
COURSE_SEMESTER = "1151"
ADMIN_NOTIFY_USER_ID = os.getenv("ADMIN_NOTIFY_USER_ID", "")


def get_env_variable(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if required and not value:
        raise RuntimeError(f"環境變數 {name} 未設定，請檢查 .env 檔案。")
    return value or ""
