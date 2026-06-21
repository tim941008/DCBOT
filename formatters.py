import discord
from course_api import normalize_course_no


def format_course_status(current: int, maximum: int) -> str:
    remaining = maximum - current
    if remaining > 0:
        return f"🟢 還有空位！剩 {remaining} 個位子"
    return "🔴 已額滿"


def format_course_card(course: dict) -> str:
    name = course.get("CourseName", "未知")
    course_no = course.get("CourseNo", "未知")
    teacher = course.get("CourseTeacher", "未知")
    node = course.get("Node", "未定")
    current = int(course.get("AllStudent", 0))
    maximum = int(course.get("Restrict2", 0))
    status = format_course_status(current, maximum)

    return (
        f"**{name}** ({course_no}) | {teacher} 老師 | 時間: {node}\n"
        f"👥 人數: {current}/{maximum} ➡️ {status}\n"
        "──────────────────\n"
    )


def format_search_results(courses: list[dict], keyword: str, limit: int = 5) -> str:
    if not courses:
        return f"❌ 找不到相關課程，請換個關鍵字再試試。"

    result_lines = [f"✅ 找到了！以下是 **{keyword}** 的前 {min(limit, len(courses))} 筆搜尋結果：\n\n"]
    for course in courses[:limit]:
        result_lines.append(format_course_card(course))
    return "".join(result_lines)


def format_tracking_overview(records: list[dict]) -> str:
    if not records:
        return "📭 你的追蹤清單目前是空的喔！"

    return "\n".join(records)


def normalize_course_input(course_no: str) -> str:
    return normalize_course_no(course_no)

def create_course_embed(course: dict, title: str = "課程即時狀態") -> discord.Embed:
    name = course.get("CourseName", "未知")
    course_no = course.get("CourseNo", "未知")
    teacher = course.get("CourseTeacher", "未知")
    node = course.get("Node", "未定")
    current = int(course.get("AllStudent", 0))
    maximum = int(course.get("Restrict2", 0))
    remaining = maximum - current
    
    # 決定顏色：綠色(有名額) 或 紅色(額滿)
    color = discord.Color.green() if remaining > 0 else discord.Color.red()
    
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="課程名稱", value=f"{name} ({course_no})", inline=False)
    embed.add_field(name="授課教師", value=teacher, inline=True)
    embed.add_field(name="上課時間", value=node, inline=True)
    embed.add_field(name="名額狀態", value=f"{current}/{maximum} (剩餘 {remaining})", inline=False)
    
    return embed