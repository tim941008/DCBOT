import logging

import discord
from discord.ext import commands

from course_api import build_course_payload, fetch_course_data, normalize_course_no
from database import delete_tracking_record, get_user_tracking_records, insert_tracking_record
from formatters import format_course_card, format_course_status, format_search_results

logger = logging.getLogger(__name__)


class CourseTrackingCog(commands.Cog):
    def __init__(self, bot: commands.Bot, supabase):
        self.bot = bot
        self.supabase = supabase

    @commands.command(name="hello")
    async def hello(self, ctx: commands.Context) -> None:
        await ctx.send("Hello！")

    @commands.command(name="查課")
    async def search_course(self, ctx: commands.Context, *, keyword: str) -> None:
        await ctx.send(f"🔍 正在查詢含有「{keyword}」的課程，請稍候...")
        payload = build_course_payload(course_name=keyword)
        courses = await fetch_course_data(payload)
        await ctx.send(format_search_results(courses, keyword))

    @commands.command(name="查課號")
    async def search_course_by_number(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        await ctx.send(f"🔍 正在查詢課號「{course_no}」，請稍候...")
        payload = build_course_payload(course_no=course_no)
        courses = await fetch_course_data(payload)

        if not courses:
            await ctx.send(f"❌ 找不到課號 {course_no} 的課程，請確認課號是否正確。")
            return

        course = courses[0]
        await ctx.send(format_course_card(course))

    @commands.command(name="指令", aliases=["help", "幫助"])
    async def list_commands(self, ctx: commands.Context) -> None:
        help_text = (
            "**🤖 可用指令列表：**\n"
            "──────────────────\n"
            "`$hello` - 測試 Bot 是否回應\n"
            "`$查課 <關鍵字>` - 查詢課程，例如 `$查課 排球`\n"
            "`$查課號 <課號>` - 查詢指定課號課程，例如 `$查課號 PE115A012`\n"
            "`$加追蹤 <課號>` - 將課程加入你的追蹤清單\n"
            "`$我的追蹤` - 查看你目前的課程追蹤清單\n"
            "`$刪追蹤 <課號>` - 從追蹤清單移除課程\n"
            "──────────────────"
        )
        await ctx.send(help_text)

    @commands.command(name="加追蹤")
    async def add_tracking(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        user_id = str(ctx.author.id)
        payload = build_course_payload(course_no=course_no)
        courses = await fetch_course_data(payload)

        if not courses:
            await ctx.send(f"❌ 查無此課號 ({course_no})")
            return

        course_name = courses[0].get("CourseName", "未知課程")
        success = insert_tracking_record(self.supabase, user_id, course_no, course_name)
        if success:
            await ctx.send(f"📌 成功將 **{course_name} ({course_no})** 加入你的追蹤清單！")
        else:
            await ctx.send("⚠️ 你可能已經追蹤過這門課了，或資料庫寫入失敗。")

    @commands.command(name="我的追蹤")
    async def view_tracking(self, ctx: commands.Context) -> None:
        user_id = str(ctx.author.id)
        records = get_user_tracking_records(self.supabase, user_id)

        if not records:
            await ctx.send("📭 你的追蹤清單目前是空的喔！")
            return

        lines = ["📋 **你的專屬追蹤清單：**\n"]
        for item in records:
            course_no = normalize_course_no(item.get("course_no", ""))
            course_name = item.get("course_name", "未知課程")
            payload = build_course_payload(course_no=course_no)
            courses = await fetch_course_data(payload)
            if not courses:
                lines.append(f"🔹 **{course_name}** ({course_no}) | 查詢失敗\n")
                continue

            course = courses[0]
            current = int(course.get("AllStudent", 0))
            maximum = int(course.get("Restrict2", 0))
            status = format_course_status(current, maximum)
            lines.append(f"🔹 **{course_name}** ({course_no}) | 👥 {current}/{maximum} ➡️ {status}\n")

        await ctx.send("".join(lines))

    @commands.command(name="刪追蹤")
    async def remove_tracking(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        user_id = str(ctx.author.id)
        deleted = delete_tracking_record(self.supabase, user_id, course_no)

        if deleted:
            await ctx.send(f"🗑️ 已將課號 **{course_no}** 從你的清單中移除。")
        else:
            await ctx.send(f"❓ 清單裡好像沒有課號為 **{course_no}** 的課喔！")


def create_bot(supabase):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="$", intents=intents, help_command=None)

    @bot.event
    async def on_ready():
        logger.info("✅ Bot 已登入：%s", bot.user)

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception) -> None:
        original = getattr(error, "original", error)
        logger.exception("指令執行錯誤：%s", original)
        try:
            if hasattr(ctx, "send"):
                await ctx.send(f"⚠️ 指令執行發生錯誤：{original.__class__.__name__}: {original}")
        except Exception:
            pass

    bot.add_cog(CourseTrackingCog(bot, supabase))
    return bot
