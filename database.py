import logging

from supabase import create_client

from config import get_env_variable

logger = logging.getLogger(__name__)


def create_supabase_client():
    url = get_env_variable("SUPABASE_URL")
    key = get_env_variable("SUPABASE_KEY")
    return create_client(url, key)


def get_tracking_records(supabase):
    try:
        response = supabase.table("tracking_list").select("*").execute()
        return response.data or []
    except Exception as error:
        logger.exception("讀取 Supabase 追蹤清單失敗：%s", error)
        return []


def get_user_tracking_records(supabase, user_id: str):
    try:
        response = supabase.table("tracking_list").select("*").eq("user_id", user_id).execute()
        return response.data or []
    except Exception as error:
        logger.exception("讀取 Supabase 使用者追蹤失敗：%s", error)
        return []


def insert_tracking_record(supabase, user_id: str, course_no: str, course_name: str, threshold: int = 1) -> bool:
    """新增追蹤紀錄，支援可選的通知門檻 `threshold`（預設 1）。"""
    try:
        existing = (
            supabase.table("tracking_list")
            .select("user_id,course_no")
            .eq("user_id", user_id)
            .eq("course_no", course_no)
            .execute()
        )
        if existing.data:
            logger.info("追蹤紀錄已存在：user_id=%s course_no=%s", user_id, course_no)
            return False

        result = supabase.table("tracking_list").insert({
            "user_id": user_id,
            "course_no": course_no,
            "course_name": course_name,
            "threshold": int(threshold),
        }).execute()
        return bool(result.data)
    except Exception as error:
        logger.exception("新增追蹤紀錄失敗：%s", error)
        return False


def delete_tracking_record(supabase, user_id: str, course_no: str) -> bool:
    try:
        result = supabase.table("tracking_list").delete().eq("user_id", user_id).eq("course_no", course_no).execute()
        return bool(result.data)
    except Exception as error:
        logger.exception("刪除追蹤紀錄失敗：%s", error)
        return False


def update_tracking_threshold(supabase, user_id: str, course_no: str, threshold: int) -> bool:
    """更新使用者針對單一課程的通知門檻值。回傳是否更新成功。"""
    try:
        result = supabase.table("tracking_list").update({"threshold": int(threshold)}).eq("user_id", user_id).eq("course_no", course_no).execute()
        return bool(result.data)
    except Exception as error:
        logger.exception("更新追蹤門檻失敗：%s", error)
        return False
