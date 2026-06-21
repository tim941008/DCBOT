import logging
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

from config import ADMIN_NOTIFY_USER_ID, COURSE_SELECTION_URL
from course_api import build_course_payload, fetch_course_data
from database import delete_tracking_record, get_tracking_records
from formatters import create_course_embed

logger = logging.getLogger(__name__)
notified_records: set[tuple[str, str]] = set()
failure_count = 0
SUMMARY_TIMEZONE = timezone(timedelta(hours=8), "Asia/Taipei")
SUMMARY_HOUR = 8


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


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "開", "啟用", "是"}


def _seconds_until_next_summary() -> float:
    now = datetime.now(SUMMARY_TIMEZONE)
    target = now.replace(hour=SUMMARY_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _notify_admin(bot, message: str) -> None:
    if not ADMIN_NOTIFY_USER_ID:
        return
    try:
        user = await bot.fetch_user(int(ADMIN_NOTIFY_USER_ID))
        await user.send(message)
    except Exception:
        logger.exception("無法通知管理員")


async def _send_vacancy_notice(bot, item: dict, course: dict, remaining: int) -> bool:
    user_id = str(item.get("user_id", "")).strip()
    course_no = str(item.get("course_no", "")).strip().upper()
    course_name = item.get("course_name", "未知課程")
    notify_channel_id = str(item.get("notify_channel_id") or "").strip()
    message = f"🚨 **通知：你追蹤的課程「{course_name} ({course_no})」有名額了！剩餘 {remaining} 個！**"
    embed = create_course_embed(course, title="🔥 搶課警報！有名額了")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="前往選課系統", style=discord.ButtonStyle.link, url=COURSE_SELECTION_URL))

    delivered = False
    if user_id:
        try:
            user = await bot.fetch_user(int(user_id))
            await user.send(message)
            await user.send(embed=embed, view=view)
            delivered = True
        except Exception as error:
            logger.warning("無法私訊使用者 %s: %s", user_id, error)

    if notify_channel_id:
        try:
            channel = bot.get_channel(int(notify_channel_id)) or await bot.fetch_channel(int(notify_channel_id))
            await channel.send(message, embed=embed, view=view)
            delivered = True
        except Exception as error:
            logger.warning("無法通知頻道 %s: %s", notify_channel_id, error)

    return delivered


async def _build_summary(records: list[dict]) -> str:
    lines = ["🌅 **今日追蹤課程摘要**\n"]
    course_cache: dict[str, list[dict]] = {}
    for item in records:
        course_no = str(item.get("course_no", "")).strip().upper()
        if not course_no:
            continue
        if course_no not in course_cache:
            course_cache[course_no] = await fetch_course_data(build_course_payload(course_no=course_no))
        courses = course_cache[course_no]
        course_name = item.get("course_name", "未知課程")
        if not courses:
            lines.append(f"🔹 **{course_name}** ({course_no}) | 查詢失敗\n")
            continue
        current = _safe_int(courses[0].get("AllStudent", 0))
        maximum = _safe_int(courses[0].get("Restrict2", 0))
        remaining = max(0, maximum - current)
        lines.append(f"🔹 **{course_name}** ({course_no}) | {current}/{maximum} | 剩餘 {remaining}\n")
    return "".join(lines)


def setup_monitor(bot, supabase):
    """建立並回傳自動監控任務。"""

    @tasks.loop(minutes=2)
    async def monitor_courses():
        global failure_count
        logger.info("正在自動掃描追蹤清單...")

        records = get_tracking_records(supabase)
        if not records:
            return

        course_cache: dict[str, list[dict]] = {}
        for item in records:
            course_no = str(item.get("course_no", "")).strip().upper()
            user_id = str(item.get("user_id", "")).strip()
            if not course_no or not user_id:
                continue
            if str(item.get("notify_enabled", "true")).strip().lower() in {"false", "0", "no", "off"}:
                continue

            if course_no not in course_cache:
                course_cache[course_no] = await fetch_course_data(build_course_payload(course_no=course_no))
            courses = course_cache[course_no]
            if not courses:
                failure_count += 1
                if failure_count in {3, 10, 30}:
                    await _notify_admin(bot, f"⚠️ 查課 API 已連續出現查無資料或失敗，累計 {failure_count} 次。")
                continue

            current = _safe_int(courses[0].get("AllStudent", 0))
            maximum = _safe_int(courses[0].get("Restrict2", 0))
            remaining = max(0, maximum - current)
            threshold = _safe_threshold(item.get("threshold", 1))
            notification_key = (user_id, course_no)

            if remaining >= threshold and notification_key not in notified_records:
                delivered = await _send_vacancy_notice(bot, item, courses[0], remaining)
                if delivered:
                    notified_records.add(notification_key)
                    failure_count = 0
                    if _truthy(item.get("auto_remove", False)):
                        delete_tracking_record(supabase, user_id, course_no)
                        notified_records.discard(notification_key)
                else:
                    failure_count += 1
                    if failure_count in {3, 10, 30}:
                        await _notify_admin(bot, f"⚠️ 課程 {course_no} 有名額，但通知送出失敗，累計 {failure_count} 次。")
            elif remaining < threshold and notification_key in notified_records:
                notified_records.remove(notification_key)

    @monitor_courses.before_loop
    async def before_monitor():
        await bot.wait_until_ready()

    return monitor_courses


def setup_daily_summary(bot, supabase):
    """建立並回傳每日 08:00 私訊摘要任務。"""

    @tasks.loop(hours=24)
    async def daily_summary():
        records = get_tracking_records(supabase)
        by_user: dict[str, list[dict]] = {}
        for item in records:
            user_id = str(item.get("user_id", "")).strip()
            if user_id:
                by_user.setdefault(user_id, []).append(item)

        for user_id, user_records in by_user.items():
            try:
                user = await bot.fetch_user(int(user_id))
                await user.send(await _build_summary(user_records))
            except Exception as error:
                logger.warning("無法傳送每日摘要給使用者 %s: %s", user_id, error)

    @daily_summary.before_loop
    async def before_daily_summary():
        await bot.wait_until_ready()
        await asyncio.sleep(_seconds_until_next_summary())

    return daily_summary
