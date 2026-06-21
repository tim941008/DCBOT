import asyncio
import logging
from math import ceil

import discord
from discord.ext import commands

from config import COURSE_SELECTION_URL
from course_api import build_course_payload, close_course_api_session, fetch_course_data, normalize_course_no
from database import (
    delete_tracking_record,
    get_tracking_record,
    get_tracking_records,
    get_tracking_stats,
    get_user_tracking_records,
    insert_tracking_record,
    check_supabase_connection,
    update_tracking_fields,
    update_tracking_threshold,
)
from formatters import create_course_embed, format_course_status, format_search_results

logger = logging.getLogger(__name__)

PAGE_SIZE = 5
THRESHOLD_CHOICES = (1, 2, 3, 5)


def _safe_positive_int(value, default: int = 1) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "開", "啟用", "是"}


def _course_remaining(course: dict) -> tuple[int, int, int]:
    current = _safe_int(course.get("AllStudent", 0))
    maximum = _safe_int(course.get("Restrict2", 0))
    return current, maximum, max(0, maximum - current)


def _course_time(course: dict) -> str:
    return str(course.get("Node") or course.get("CourseTimes") or course.get("Time") or "未定")


def _record_note(record: dict) -> str:
    note = str(record.get("note") or "").strip()
    return f" | 備註：{note}" if note else ""


async def _fetch_first_course(course_no: str) -> dict | None:
    courses = await fetch_course_data(build_course_payload(course_no=course_no))
    return courses[0] if courses else None


async def _format_tracking_page(records: list[dict], page: int) -> str:
    total_pages = max(1, ceil(len(records) / PAGE_SIZE))
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    page_records = records[start:start + PAGE_SIZE]

    tasks = [
        fetch_course_data(build_course_payload(course_no=normalize_course_no(item.get("course_no", ""))))
        for item in page_records
    ]
    course_results = await asyncio.gather(*tasks, return_exceptions=True)

    lines = [f"📋 **你的追蹤清單** 第 {page + 1}/{total_pages} 頁\n"]
    for item, courses in zip(page_records, course_results):
        course_no = normalize_course_no(item.get("course_no", ""))
        course_name = item.get("course_name", "未知課程")
        threshold = _safe_positive_int(item.get("threshold", 1))
        auto_remove = " | 通知後自動移除" if _truthy(item.get("auto_remove", False)) else ""
        wishlist = " | 收藏" if _truthy(item.get("is_wishlist", False)) else ""
        notify_disabled = " | 不通知" if str(item.get("notify_enabled", "true")).lower() in {"false", "0"} else ""

        if isinstance(courses, Exception) or not courses:
            lines.append(f"🔹 **{course_name}** ({course_no}) | 查詢失敗 | 門檻：{threshold}{auto_remove}{wishlist}{notify_disabled}{_record_note(item)}\n")
            continue

        course = courses[0]
        current, maximum, _ = _course_remaining(course)
        status = format_course_status(current, maximum)
        lines.append(
            f"🔹 **{course_name}** ({course_no}) | 👥 {current}/{maximum} ➡️ {status} | "
            f"門檻：{threshold}{auto_remove}{wishlist}{notify_disabled}{_record_note(item)}\n"
        )
    return "".join(lines)


class ThresholdButton(discord.ui.Button):
    def __init__(self, supabase, course: dict, course_no: str, threshold: int):
        super().__init__(label=str(threshold), style=discord.ButtonStyle.gray, row=1)
        self.supabase = supabase
        self.course = course
        self.course_no = course_no
        self.threshold = threshold

    async def callback(self, interaction: discord.Interaction) -> None:
        user_id = str(interaction.user.id)
        course_name = self.course.get("CourseName", "未知課程")
        record = get_tracking_record(self.supabase, user_id, self.course_no)
        if record:
            updated = update_tracking_fields(self.supabase, user_id, self.course_no, {"threshold": self.threshold, "notify_enabled": True})
            message = f"✅ 已將 **{course_name} ({self.course_no})** 的門檻設為 {self.threshold}。"
        else:
            updated = insert_tracking_record(self.supabase, user_id, self.course_no, course_name, self.threshold)
            message = f"📌 已加入 **{course_name} ({self.course_no})**，門檻：{self.threshold}。"

        if updated:
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 設定失敗，請確認資料表欄位與權限。", ephemeral=True)


class CourseTrackView(discord.ui.View):
    def __init__(self, supabase, course: dict, course_no: str, author_id: int):
        super().__init__(timeout=180.0)
        self.supabase = supabase
        self.course = course
        self.course_no = course_no
        self.author_id = author_id
        self.add_item(discord.ui.Button(label="前往選課系統", style=discord.ButtonStyle.link, url=COURSE_SELECTION_URL))
        for threshold in THRESHOLD_CHOICES:
            self.add_item(ThresholdButton(supabase, course, course_no, threshold))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="加追蹤", style=discord.ButtonStyle.green)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        course_name = self.course.get("CourseName", "未知課程")
        success = insert_tracking_record(self.supabase, str(interaction.user.id), self.course_no, course_name, 1)
        if success:
            await interaction.response.send_message(f"📌 已將 **{course_name} ({self.course_no})** 加入你的追蹤清單。", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 加入失敗或已存在於追蹤清單。", ephemeral=True)

    @discord.ui.button(label="刪追蹤", style=discord.ButtonStyle.red)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        deleted = delete_tracking_record(self.supabase, str(interaction.user.id), self.course_no)
        if deleted:
            await interaction.response.send_message(f"🗑️ 已將課號 **{self.course_no}** 從你的追蹤清單移除。", ephemeral=True)
        else:
            await interaction.response.send_message("❓ 移除失敗或清單中不存在該課程。", ephemeral=True)


class SearchTrackingView(discord.ui.View):
    def __init__(self, supabase, courses: list[dict], author_id: int, keyword: str, page: int = 0):
        super().__init__(timeout=180.0)
        self.supabase = supabase
        self.courses = courses
        self.author_id = author_id
        self.keyword = keyword
        self.page = page
        self.total_pages = max(1, ceil(len(courses) / PAGE_SIZE))
        self.page = min(max(self.page, 0), self.total_pages - 1)
        self._build_items()

    def _build_items(self) -> None:
        self.clear_items()
        start = self.page * PAGE_SIZE
        for course in self.courses[start:start + PAGE_SIZE]:
            course_no = normalize_course_no(course.get("CourseNo", ""))
            label = course_no if len(course_no) <= 70 else course_no[:67] + "..."
            button = discord.ui.Button(label=f"加追蹤 {label}", style=discord.ButtonStyle.green)
            button.callback = self._create_add_callback(course, course_no)
            self.add_item(button)

        prev_button = discord.ui.Button(label="上一頁", style=discord.ButtonStyle.gray, disabled=self.page <= 0, row=1)
        next_button = discord.ui.Button(label="下一頁", style=discord.ButtonStyle.gray, disabled=self.page >= self.total_pages - 1, row=1)
        prev_button.callback = self._prev_page_callback
        next_button.callback = self._next_page_callback
        self.add_item(prev_button)
        self.add_item(next_button)

    def _create_add_callback(self, course: dict, course_no: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
                return

            course_name = course.get("CourseName", "未知課程")
            success = insert_tracking_record(self.supabase, str(interaction.user.id), course_no, course_name, 1)
            if success:
                await interaction.response.send_message(f"📌 已將 **{course_name} ({course_no})** 加入你的追蹤清單。", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ 加入失敗或已存在於追蹤清單。", ephemeral=True)

        return callback

    async def _prev_page_callback(self, interaction: discord.Interaction) -> None:
        await self._change_page(interaction, self.page - 1)

    async def _next_page_callback(self, interaction: discord.Interaction) -> None:
        await self._change_page(interaction, self.page + 1)

    async def _change_page(self, interaction: discord.Interaction, page: int) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
            return

        self.page = min(max(page, 0), self.total_pages - 1)
        self._build_items()
        content = format_search_results(self.courses, self.keyword, self.page, PAGE_SIZE)
        await interaction.response.edit_message(content=content, view=self)


class TrackingListView(discord.ui.View):
    def __init__(self, supabase, records: list[dict], author_id: int, page: int = 0):
        super().__init__(timeout=180.0)
        self.supabase = supabase
        self.records = records
        self.author_id = author_id
        self.page = page
        self.total_pages = max(1, ceil(len(records) / PAGE_SIZE))
        self._build_items()

    def _build_items(self) -> None:
        self.clear_items()
        start = self.page * PAGE_SIZE
        for item in self.records[start:start + PAGE_SIZE]:
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

        prev_button = discord.ui.Button(label="上一頁", style=discord.ButtonStyle.gray, disabled=self.page <= 0, row=1)
        next_button = discord.ui.Button(label="下一頁", style=discord.ButtonStyle.gray, disabled=self.page >= self.total_pages - 1, row=1)

        async def prev_callback(interaction: discord.Interaction):
            await self._change_page(interaction, self.page - 1)

        async def next_callback(interaction: discord.Interaction):
            await self._change_page(interaction, self.page + 1)

        prev_button.callback = prev_callback
        next_button.callback = next_callback
        self.add_item(prev_button)
        self.add_item(next_button)

    async def _change_page(self, interaction: discord.Interaction, page: int) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("只有原始使用者可操作此按鈕。", ephemeral=True)
            return
        self.page = min(max(page, 0), self.total_pages - 1)
        self._build_items()
        content = await _format_tracking_page(self.records, self.page)
        await interaction.response.edit_message(content=content, view=self)


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
        courses = await fetch_course_data(build_course_payload(course_name=keyword))
        if not courses:
            await ctx.send(f"❌ 找不到含有「{keyword}」的課程，請換個關鍵字再試試。")
            return

        await ctx.send(
            format_search_results(courses, keyword, page=0, limit=PAGE_SIZE),
            view=SearchTrackingView(self.supabase, courses, ctx.author.id, keyword, page=0),
        )

    @commands.command(name="查老師")
    async def search_teacher(self, ctx: commands.Context, *, teacher: str) -> None:
        await ctx.send(f"🔍 正在查詢「{teacher}」老師的課程，請稍候...")
        courses = await fetch_course_data(build_course_payload(course_teacher=teacher))
        matches = [course for course in courses if teacher in str(course.get("CourseTeacher", ""))]
        if not matches:
            await ctx.send(f"❌ 找不到「{teacher}」老師的課程。")
            return
        await ctx.send(
            format_search_results(matches, teacher, page=0, limit=PAGE_SIZE),
            view=SearchTrackingView(self.supabase, matches, ctx.author.id, teacher, page=0),
        )

    @commands.command(name="查時間")
    async def search_time(self, ctx: commands.Context, *, time_keyword: str) -> None:
        await ctx.send(f"🔍 正在查詢上課時間含有「{time_keyword}」的課程，請稍候...")
        courses = await fetch_course_data(build_course_payload())
        matches = [course for course in courses if time_keyword in _course_time(course)]
        if not matches:
            await ctx.send(
                f"❌ 找不到上課時間含有「{time_keyword}」的課程。請確認時間格式，例如 `週一 1-2 節`、`週二`、`星期三`，再試一次。"
            )
            return
        await ctx.send(
            format_search_results(matches, time_keyword, page=0, limit=PAGE_SIZE),
            view=SearchTrackingView(self.supabase, matches, ctx.author.id, time_keyword, page=0),
        )

    @commands.command(name="查課號")
    async def search_course_by_number(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        await ctx.send(f"🔍 正在查詢課號「{course_no}」，請稍候...")
        course = await _fetch_first_course(course_no)
        if not course:
            await ctx.send(f"❌ 找不到課號 {course_no} 的課程，請確認課號是否正確。")
            return

        await ctx.send(embed=create_course_embed(course), view=CourseTrackView(self.supabase, course, course_no, ctx.author.id))

    @commands.command(name="指令", aliases=["help", "幫助"])
    async def list_commands(self, ctx: commands.Context) -> None:
        help_text = (
            "**🤖 可用指令列表：**\n"
            "──────────────────\n"
            "`$hello` - 測試 Bot 是否回應\n"
            "`$查課 <關鍵字>` / `$查課號 <課號>` / `$查老師 <老師>` / `$查時間 <時間>`\n"
            "`$我的追蹤` - 分頁查看追蹤清單\n"
            "`$加追蹤 <課號> [門檻]` / `$刪追蹤 <課號>` / `$設定門檻 <課號> <數字>`\n"
            "`$設定頻道 <課號>` / `$清除頻道 <課號>` - 設定或清除課程通知頻道\n"
            "`$自動移除 <課號> <開|關>` - 通知成功後自動移除追蹤\n"
            "`$收藏 <課號> [備註]` / `$備註 <課號> <內容>` / `$衝堂` / `$每日摘要`\n"
            "`$狀態` / `$管理` - 查看服務狀態與統計\n"
            "──────────────────"
        )
        await ctx.send(help_text)

    @commands.command(name="加追蹤")
    async def add_tracking(self, ctx: commands.Context, course_no: str, threshold: int = 1) -> None:
        course_no = normalize_course_no(course_no)
        threshold = _safe_positive_int(threshold)
        course = await _fetch_first_course(course_no)
        if not course:
            await ctx.send(f"❌ 查無此課號 ({course_no})")
            return

        course_name = course.get("CourseName", "未知課程")
        existing = get_tracking_record(self.supabase, str(ctx.author.id), course_no)
        if existing:
            updated = update_tracking_fields(
                self.supabase,
                str(ctx.author.id),
                course_no,
                {"threshold": threshold, "notify_enabled": True},
            )
            if updated:
                await ctx.send(f"📌 已將 **{course_name} ({course_no})** 轉為追蹤通知！(門檻：{threshold})")
            else:
                await ctx.send("⚠️ 你已收藏或追蹤這門課，但更新通知設定失敗。")
            return

        success = insert_tracking_record(self.supabase, str(ctx.author.id), course_no, course_name, threshold)
        if success:
            await ctx.send(f"📌 成功將 **{course_name} ({course_no})** 加入你的追蹤清單！(門檻：{threshold})")
        else:
            await ctx.send("⚠️ 你可能已經追蹤過這門課了，或資料庫寫入失敗。")

    @commands.command(name="我的追蹤")
    async def view_tracking(self, ctx: commands.Context) -> None:
        records = get_user_tracking_records(self.supabase, str(ctx.author.id))
        if not records:
            await ctx.send("📭 你的追蹤清單目前是空的喔！")
            return

        content = await _format_tracking_page(records, 0)
        await ctx.send(content, view=TrackingListView(self.supabase, records, ctx.author.id))

    @commands.command(name="刪追蹤")
    async def remove_tracking(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        deleted = delete_tracking_record(self.supabase, str(ctx.author.id), course_no)
        if deleted:
            await ctx.send(f"🗑️ 已將課號 **{course_no}** 從你的清單中移除。")
        else:
            await ctx.send(f"❓ 清單裡好像沒有課號為 **{course_no}** 的課喔！")

    @commands.command(name="設定門檻")
    async def set_threshold(self, ctx: commands.Context, course_no: str, threshold: int) -> None:
        course_no = normalize_course_no(course_no)
        threshold = _safe_positive_int(threshold)
        updated = update_tracking_fields(self.supabase, str(ctx.author.id), course_no, {"threshold": threshold, "notify_enabled": True})
        if updated:
            await ctx.send(f"✅ 已將課號 **{course_no}** 的通知門檻更新為 {threshold}。")
        else:
            await ctx.send(f"❌ 更新失敗，請確認你是否已追蹤課號 {course_no}。")

    @commands.command(name="設定頻道")
    @commands.has_permissions(manage_channels=True)
    async def set_notify_channel(self, ctx: commands.Context, course_no: str, channel: discord.TextChannel | None = None) -> None:
        course_no = normalize_course_no(course_no)
        target = channel or ctx.channel
        updated = update_tracking_fields(self.supabase, str(ctx.author.id), course_no, {"notify_channel_id": str(target.id)})
        if updated:
            await ctx.send(f"✅ 課號 **{course_no}** 有名額時會通知 {target.mention}。")
        else:
            await ctx.send("❌ 設定失敗，請確認你已追蹤此課程，且資料表已有 `notify_channel_id` 欄位。")

    @commands.command(name="清除頻道")
    async def clear_notify_channel(self, ctx: commands.Context, course_no: str) -> None:
        course_no = normalize_course_no(course_no)
        updated = update_tracking_fields(self.supabase, str(ctx.author.id), course_no, {"notify_channel_id": None})
        if updated:
            await ctx.send(f"✅ 已清除課號 **{course_no}** 的頻道通知。")
        else:
            await ctx.send("❌ 清除失敗，請確認你已追蹤此課程，且資料表已有 `notify_channel_id` 欄位。")

    @commands.command(name="自動移除")
    async def set_auto_remove(self, ctx: commands.Context, course_no: str, enabled: str) -> None:
        course_no = normalize_course_no(course_no)
        enabled_value = _truthy(enabled)
        updated = update_tracking_fields(self.supabase, str(ctx.author.id), course_no, {"auto_remove": enabled_value})
        if updated:
            await ctx.send(f"✅ 課號 **{course_no}** 通知後自動移除：{'開' if enabled_value else '關'}。")
        else:
            await ctx.send("❌ 設定失敗，請確認你已追蹤此課程，且資料表已有 `auto_remove` 欄位。")

    @commands.command(name="收藏")
    async def add_wishlist(self, ctx: commands.Context, course_no: str, *, note: str = "") -> None:
        course_no = normalize_course_no(course_no)
        course = await _fetch_first_course(course_no)
        if not course:
            await ctx.send(f"❌ 查無此課號 ({course_no})")
            return

        course_name = course.get("CourseName", "未知課程")
        success = insert_tracking_record(
            self.supabase,
            str(ctx.author.id),
            course_no,
            course_name,
            1,
            is_wishlist=True,
            notify_enabled=False,
            note=note,
        )
        if success:
            await ctx.send(f"⭐ 已收藏 **{course_name} ({course_no})**。")
        else:
            updated = update_tracking_fields(self.supabase, str(ctx.author.id), course_no, {"is_wishlist": True, "note": note})
            if updated:
                await ctx.send(f"⭐ 已將 **{course_name} ({course_no})** 標記為收藏。")
            else:
                await ctx.send("❌ 收藏失敗，請確認資料表已有 `is_wishlist` 與 `note` 欄位。")

    @commands.command(name="備註")
    async def set_note(self, ctx: commands.Context, course_no: str, *, note: str) -> None:
        course_no = normalize_course_no(course_no)
        updated = update_tracking_fields(self.supabase, str(ctx.author.id), course_no, {"note": note[:200]})
        if updated:
            await ctx.send(f"📝 已更新課號 **{course_no}** 的備註。")
        else:
            await ctx.send("❌ 更新失敗，請確認你已追蹤此課程，且資料表已有 `note` 欄位。")

    @commands.command(name="衝堂")
    async def check_conflicts(self, ctx: commands.Context) -> None:
        records = get_user_tracking_records(self.supabase, str(ctx.author.id))
        if len(records) < 2:
            await ctx.send("目前追蹤少於兩門課，沒有可檢查的衝堂組合。")
            return

        tasks = [_fetch_first_course(normalize_course_no(item.get("course_no", ""))) for item in records]
        courses = await asyncio.gather(*tasks)
        by_time: dict[str, list[str]] = {}
        for record, course in zip(records, courses):
            if not course:
                continue
            time_text = _course_time(course)
            if not time_text or time_text == "未定":
                continue
            by_time.setdefault(time_text, []).append(f"{record.get('course_name', '未知課程')} ({record.get('course_no')})")

        conflicts = {time_text: names for time_text, names in by_time.items() if len(names) > 1}
        if not conflicts:
            await ctx.send("✅ 目前沒有發現明顯衝堂。")
            return

        lines = ["⚠️ **可能衝堂：**\n"]
        for time_text, names in conflicts.items():
            lines.append(f"`{time_text}`：{', '.join(names)}\n")
        await ctx.send("".join(lines))

    @commands.command(name="每日摘要")
    async def daily_summary(self, ctx: commands.Context) -> None:
        records = get_user_tracking_records(self.supabase, str(ctx.author.id))
        if not records:
            await ctx.send("📭 你的追蹤清單目前是空的喔！")
            return
        content = await _format_tracking_page(records, 0)
        await ctx.author.send("🌅 **今日追蹤課程摘要**\n" + content)
        await ctx.send("✅ 已將今日摘要私訊給你。")

    @commands.command(name="狀態")
    async def health_check(self, ctx: commands.Context) -> None:
        supabase_ok = check_supabase_connection(self.supabase)
        api_ok = bool(await fetch_course_data(build_course_payload(course_name="")))
        monitor_running = bool(getattr(self.bot, "_monitor_task", None) and self.bot._monitor_task.is_running())
        daily_running = bool(getattr(self.bot, "_daily_summary_task", None) and self.bot._daily_summary_task.is_running())
        await ctx.send(
            "**系統狀態**\n"
            f"Discord：✅ 已連線\n"
            f"Supabase：{'✅' if supabase_ok else '❌'}\n"
            f"查課 API：{'✅' if api_ok else '❌'}\n"
            f"監控任務：{'✅ 執行中' if monitor_running else '❌ 未執行'}\n"
            f"每日摘要：{'✅ 執行中' if daily_running else '❌ 未執行'}"
        )

    @commands.command(name="管理")
    @commands.has_permissions(manage_guild=True)
    async def admin_stats(self, ctx: commands.Context) -> None:
        stats = get_tracking_stats(self.supabase)
        monitor_running = bool(getattr(self.bot, "_monitor_task", None) and self.bot._monitor_task.is_running())
        daily_running = bool(getattr(self.bot, "_daily_summary_task", None) and self.bot._daily_summary_task.is_running())
        await ctx.send(
            "**管理統計**\n"
            f"追蹤筆數：{stats['records']}\n"
            f"使用者數：{stats['users']}\n"
            f"課程數：{stats['courses']}\n"
            f"監控任務：{'執行中' if monitor_running else '未執行'}\n"
            f"每日摘要：{'執行中' if daily_running else '未執行'}"
        )


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
        if getattr(bot, "_initialized", False):
            return

        try:
            await bot.add_cog(CourseTrackingCog(bot, supabase))
            bot._initialized = True
        except Exception:
            try:
                bot.add_cog(CourseTrackingCog(bot, supabase))
                bot._initialized = True
            except Exception:
                logger.exception("無法註冊 Cog")

        try:
            from monitor import setup_daily_summary, setup_monitor

            monitor_task = setup_monitor(bot, supabase)
            monitor_task.start()
            bot._monitor_task = monitor_task
            daily_summary_task = setup_daily_summary(bot, supabase)
            daily_summary_task.start()
            bot._daily_summary_task = daily_summary_task
            logger.info("✅ 自動監聽系統 (monitor.py) 已啟動！")
        except Exception:
            logger.exception("無法啟動監控任務")

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, commands.MissingRequiredArgument):
            usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}" if ctx.command else "請參考指令說明使用方式"
            await ctx.send(f"⚠️ 缺少必要參數：`{original.param.name}`。用法：{usage}")
            return
        if isinstance(original, commands.MissingPermissions):
            await ctx.send("⚠️ 你沒有權限使用這個指令。")
            return
        if isinstance(original, commands.BadArgument):
            await ctx.send("⚠️ 參數格式不正確，請用 `$指令` 查看用法。")
            return

        logger.exception("指令執行錯誤：%s", original)
        try:
            await ctx.send(f"⚠️ 指令執行發生錯誤：{original.__class__.__name__}: {original}")
        except Exception:
            pass

    return bot
