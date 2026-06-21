from discord.ext import tasks
import discord
from config import COURSE_SELECTION_URL
from formatters import create_course_embed
from course_api import build_course_payload, fetch_course_data
from database import get_tracking_records

notified_courses: set[str] = set()


def setup_monitor(bot, supabase):
    """建立並回傳自動監控任務。"""

    @tasks.loop(minutes=2)
    async def monitor_courses():
        print("🕒 正在自動掃描追蹤清單...")

        records = get_tracking_records(supabase)
        if not records:
            return

        for item in records:
            course_no = item.get("course_no", "").strip().upper()
            user_id = int(item.get("user_id", 0))
            course_name = item.get("course_name", "未知課程")

            payload = build_course_payload(course_no=course_no)
            courses = await fetch_course_data(payload)
            if not courses:
                continue

            current = int(courses[0].get("AllStudent", 0))
            maximum = int(courses[0].get("Restrict2", 0))
            remaining = maximum - current

            # 使用每筆追蹤紀錄上的 threshold（預設 1）來判斷是否通知
            try:
                threshold = int(item.get("threshold", 1))
            except Exception:
                threshold = 1

            if remaining >= threshold and course_no not in notified_courses:
                try:
                    user = await bot.fetch_user(user_id)
                    await user.send(
                        f"🚨 **通知：你追蹤的課程「{course_name} ({course_no})」有名額了！剩餘 {remaining} 個！**"
                    )
                    embed = create_course_embed(courses[0], title="🔥 搶課警報！有名額了")
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="前往選課系統", style=discord.ButtonStyle.link, url=COURSE_SELECTION_URL))
                    await user.send(embed=embed, view=view)
                    notified_courses.add(course_no)
                except Exception as error:
                    print(f"❌ 無法私訊使用者 {user_id}: {error}")
            elif remaining <= 0 and course_no in notified_courses:
                notified_courses.remove(course_no)

    @monitor_courses.before_loop
    async def before_monitor():
        await bot.wait_until_ready()

    return monitor_courses