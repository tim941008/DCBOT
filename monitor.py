import logging

from discord.ext import tasks
import discord
from config import COURSE_SELECTION_URL
from formatters import create_course_embed
from course_api import build_course_payload, fetch_course_data
from database import get_tracking_records

logger = logging.getLogger(__name__)
notified_records: set[tuple[str, str]] = set()


def _safe_threshold(value) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def setup_monitor(bot, supabase):
    """建立並回傳自動監控任務。"""

    @tasks.loop(minutes=2)
    async def monitor_courses():
        logger.info("正在自動掃描追蹤清單...")

        records = get_tracking_records(supabase)
        if not records:
            return

        course_cache: dict[str, list[dict]] = {}
        for item in records:
            course_no = item.get("course_no", "").strip().upper()
            user_id = str(item.get("user_id", "")).strip()
            course_name = item.get("course_name", "未知課程")
            if not course_no or not user_id:
                continue

            if course_no not in course_cache:
                payload = build_course_payload(course_no=course_no)
                course_cache[course_no] = await fetch_course_data(payload)
            courses = course_cache[course_no]
            if not courses:
                continue

            current = _safe_int(courses[0].get("AllStudent", 0))
            maximum = _safe_int(courses[0].get("Restrict2", 0))
            remaining = maximum - current
            if remaining < 0:
                logger.warning("課程 %s 人數資料異常：current=%s maximum=%s", course_no, current, maximum)
                remaining = 0

            # 使用每筆追蹤紀錄上的 threshold（預設 1）來判斷是否通知
            threshold = _safe_threshold(item.get("threshold", 1))
            notification_key = (user_id, course_no)

            if remaining >= threshold and notification_key not in notified_records:
                try:
                    user = await bot.fetch_user(int(user_id))
                    await user.send(
                        f"🚨 **通知：你追蹤的課程「{course_name} ({course_no})」有名額了！剩餘 {remaining} 個！**"
                    )
                    embed = create_course_embed(courses[0], title="🔥 搶課警報！有名額了")
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="前往選課系統", style=discord.ButtonStyle.link, url=COURSE_SELECTION_URL))
                    await user.send(embed=embed, view=view)
                    notified_records.add(notification_key)
                except Exception as error:
                    logger.warning("無法私訊使用者 %s: %s", user_id, error)
            elif remaining < threshold and notification_key in notified_records:
                notified_records.remove(notification_key)

    @monitor_courses.before_loop
    async def before_monitor():
        await bot.wait_until_ready()

    return monitor_courses
