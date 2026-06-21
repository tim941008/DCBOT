import logging
import asyncio

import discord
from discord.ext import commands

from course_api import build_course_payload, close_course_api_session, fetch_course_data, normalize_course_no
from config import COURSE_SELECTION_URL
from database import delete_tracking_record, get_user_tracking_records, insert_tracking_record, update_tracking_threshold
from formatters import format_course_card, format_course_status, format_search_results, create_course_embed

logger = logging.getLogger(__name__)


def _safe_positive_threshold(threshold: int) -> int:
    try:
        return max(1, int(threshold))
    except (TypeError, ValueError):
        return 1


class CourseTrackView(discord.ui.View):
    def __init__(self, supabase, course: dict, course_no: str, author_id: int):
        super().__init__(timeout=180.0)
        self.supabase = supabase
        self.course = course
        self.course_no = course_no
        self.author_id = author_id
        self.add_item(discord.ui.Button(label="前往選課系統", style=discord.ButtonStyle.link, url=COURSE_SELECTION_URL))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="加追蹤", style=discord.ButtonStyle.green)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            course_name = self.course.get("CourseName", "未知課程")
            # UI 快速加入追蹤時使用預設門檻 1
            success = insert_tracking_record(self.supabase, str(interaction.user.id), self.course_no, course_name, 1)
            if success:
                await interaction.response.send_message(f"📌 已將 **{course_name} ({self.course_no})** 加入你的追蹤清單。", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ 加入失敗或已存在於追蹤清單。", ephemeral=True)
        except Exception as error:
            await interaction.response.send_message(f"⚠️ 加追蹤失敗：{error}", ephemeral=True)

    @discord.ui.button(label="刪追蹤", style=discord.ButtonStyle.red)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            deleted = delete_tracking_record(self.supabase, str(interaction.user.id), self.course_no)
            if deleted:
                await interaction.response.send_message(f"🗑️ 已將課號 **{self.course_no}** 從你的追蹤清單移除。", ephemeral=True)
            else:
                await interaction.response.send_message("❓ 移除失敗或清單中不存在該課程。", ephemeral=True)
        except Exception as error:
            await interaction.response.send_message(f"⚠️ 刪追蹤失敗：{error}", ephemeral=True)


class SearchTrackingView(discord.ui.View):
    def __init__(self, supabase, courses: list[dict], author_id: int):
        super().__init__(timeout=180.0)
        self.supabase = supabase
        self.author_id = author_id

        for course in courses:
            course_no = normalize_course_no(course.get("CourseNo", ""))
            label = course_no if len(course_no) <= 80 else course_no[:77] + "..."
            button = discord.ui.Button(label=f"加追蹤 {label}", style=discord.ButtonStyle.green)

            async def callback(interaction: discord.Interaction, course=course, course_no=course_no):
                if interaction.user.id != self.author_id:
                    await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
                    return

                course_name = course.get("CourseName", "未知課程")
                # UI 搜尋結果加入追蹤使用預設門檻 1
                success = insert_tracking_record(self.supabase, str(interaction.user.id), course_no, course_name, 1)
                if success:
                    await interaction.response.send_message(f"📌 已將 **{course_name} ({course_no})** 加入你的追蹤清單。", ephemeral=True)
                else:
                    await interaction.response.send_message("⚠️ 加入失敗或已存在於追蹤清單。", ephemeral=True)

            button.callback = callback
            self.add_item(button)


class TrackingListView(discord.ui.View):
    def __init__(self, supabase, records: list[dict], author_id: int):
        super().__init__(timeout=180.0)
        self.supabase = supabase
        self.author_id = author_id

        for item in records[:5]:
            course_no = normalize_course_no(item.get("course_no", ""))
            button = discord.ui.Button(label=f"刪追蹤 {course_no}", style=discord.ButtonStyle.red)

            async def callback(interaction: discord.Interaction, course_no=course_no):
                if interaction.user.id != self.author_id:
                    await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
                    return

                deleted = delete_tracking_record(self.supabase, str(interaction.user.id), course_no)
                if deleted:
                    await interaction.response.send_message(f"🗑️ 已將課號 **{course_no}** 從你的追蹤清單移除。", ephemeral=True)
                else:
                    await interaction.response.send_message("❓ 移除失敗或清單中不存在該課程。", ephemeral=True)

            button.callback = callback
            self.add_item(button)

        if len(records) > 5:
            self.add_item(discord.ui.Button(label="僅顯示前 5 筆追蹤", style=discord.ButtonStyle.gray, disabled=True))


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

        if not courses:
            await ctx.send(f"❌ 找不到含有「{keyword}」的課程，請換個關鍵字再試試。")
            return

        content = format_search_results(courses, keyword)
        view = SearchTrackingView(self.supabase, courses[:5], ctx.author.id)
        await ctx.send(content, view=view)

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
        embed = create_course_embed(course)
        view = CourseTrackView(self.supabase, course, course_no, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="指令", aliases=["help", "幫助"])
    async def list_commands(self, ctx: commands.Context) -> None:
        help_text = (
            "**🤖 可用指令列表：**\n"
            "──────────────────\n"
            "`$hello` - 測試 Bot 是否回應\n"
            "`$查課 <關鍵字>` - 查詢課程並直接加追蹤\n"
            "`$查課號 <課號>` - 查詢指定課號並直接加/刪追蹤\n"
            "`$我的追蹤` - 查看你的追蹤清單並可刪除追蹤\n"
            "`$加追蹤 <課號> [門檻]` - 將課程加入你的追蹤清單\n"
            "`$設定門檻 <課號> <數字>` - 更新已追蹤課程的通知門檻\n"
            "`$刪追蹤 <課號>` - 從追蹤清單移除課程\n"
            "──────────────────"
        )
        await ctx.send(help_text)

    @commands.command(name="加追蹤")
    async def add_tracking(self, ctx: commands.Context, course_no: str, threshold: int = 1) -> None:
        """加入追蹤，可選擇性帶入 `threshold`（整數），代表當剩餘 >= threshold 時才通知。"""
        course_no = normalize_course_no(course_no)
        threshold = _safe_positive_threshold(threshold)
        user_id = str(ctx.author.id)
        payload = build_course_payload(course_no=course_no)
        courses = await fetch_course_data(payload)

        if not courses:
            await ctx.send(f"❌ 查無此課號 ({course_no})")
            return

        course_name = courses[0].get("CourseName", "未知課程")
        success = insert_tracking_record(self.supabase, user_id, course_no, course_name, threshold)
        if success:
            await ctx.send(f"📌 成功將 **{course_name} ({course_no})** 加入你的追蹤清單！(門檻：{threshold})")
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
        tasks = [
            fetch_course_data(build_course_payload(course_no=normalize_course_no(item.get("course_no", ""))))
            for item in records
        ]
        course_results = await asyncio.gather(*tasks, return_exceptions=True)

        for item, courses in zip(records, course_results):
            course_no = normalize_course_no(item.get("course_no", ""))
            course_name = item.get("course_name", "未知課程")
            threshold = _safe_positive_threshold(item.get("threshold", 1))
            if isinstance(courses, Exception) or not courses:
                lines.append(f"🔹 **{course_name}** ({course_no}) | 查詢失敗 | 門檻：{threshold}\n")
                continue

            course = courses[0]
            current = int(course.get("AllStudent", 0))
            maximum = int(course.get("Restrict2", 0))
            status = format_course_status(current, maximum)
            lines.append(f"🔹 **{course_name}** ({course_no}) | 👥 {current}/{maximum} ➡️ {status} | 門檻：{threshold}\n")

        await ctx.send("".join(lines), view=TrackingListView(self.supabase, records, ctx.author.id))

    @commands.command(name="刪追蹤")
    async def remove_tracking(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        user_id = str(ctx.author.id)
        deleted = delete_tracking_record(self.supabase, user_id, course_no)

        if deleted:
            await ctx.send(f"🗑️ 已將課號 **{course_no}** 從你的清單中移除。")
        else:
            await ctx.send(f"❓ 清單裡好像沒有課號為 **{course_no}** 的課喔！")

    @commands.command(name="設定門檻")
    async def set_threshold(self, ctx: commands.Context, course_no: str, threshold: int) -> None:
        """設定已追蹤課程的通知門檻。用法：`$設定門檻 <課號> <數字>`"""
        course_no = normalize_course_no(course_no)
        threshold = _safe_positive_threshold(threshold)
        user_id = str(ctx.author.id)
        updated = update_tracking_threshold(self.supabase, user_id, course_no, threshold)
        if updated:
            await ctx.send(f"✅ 已將課號 **{course_no}** 的通知門檻更新為 {threshold}。")
        else:
            await ctx.send(f"❌ 更新失敗，請確認你是否已追蹤課號 {course_no}。")


def create_bot(supabase):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="$", intents=intents, help_command=None)
    original_close = bot.close

    async def close_with_course_api_session() -> None:
        await close_course_api_session()
        await original_close()

    bot.close = close_with_course_api_session

    @bot.event
    async def on_ready():
        logger.info("✅ Bot 已登入：%s", bot.user)
        # ensure we only initialize once (on reconnects this runs again)
        if getattr(bot, "_initialized", False):
            return
        # 註冊 Cog（discord.py 新版本 add_cog 可能為 coroutine）
        try:
            await bot.add_cog(CourseTrackingCog(bot, supabase))
            bot._initialized = True
        except Exception:
            # fallback: try sync add_cog if coroutine wasn't expected
            try:
                bot.add_cog(CourseTrackingCog(bot, supabase))
                bot._initialized = True
            except Exception:
                logger.exception("無法註冊 Cog")

        # 在 bot 啟動後再啟動監控任務，確保 event loop 已就緒
        try:
            from monitor import setup_monitor

            monitor_task = setup_monitor(bot, supabase)
            monitor_task.start()
            logger.info("✅ 自動監聽系統 (monitor.py) 已啟動！")
        except Exception:
            logger.exception("無法啟動監控任務")

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception) -> None:
        original = getattr(error, "original", error)
        # 處理缺少必要參數的情況，給使用者友善提示與用法
        try:
            from discord.ext.commands import MissingRequiredArgument

            if isinstance(original, MissingRequiredArgument):
                param_name = getattr(original, "param", None)
                if param_name and hasattr(param_name, "name"):
                    param_display = param_name.name
                else:
                    param_display = str(original)

                if ctx and getattr(ctx, "command", None):
                    usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"
                else:
                    usage = "請參考指令說明使用方式"

                await ctx.send(f"⚠️ 缺少必要參數：`{param_display}`。用法：{usage}")
                return
        except Exception:
            # 若檢查 MissingRequiredArgument 過程發生錯誤，繼續到一般錯誤處理
            pass

        # 其他未處理的錯誤，記錄並回報簡短訊息
        logger.exception("指令執行錯誤：%s", original)
        try:
            if hasattr(ctx, "send"):
                await ctx.send(f"⚠️ 指令執行發生錯誤：{original.__class__.__name__}: {original}")
        except Exception:
            pass

    return bot
