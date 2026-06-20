from config import get_env_variable
from database import create_supabase_client
from bot import create_bot
from monitor import setup_monitor


def main() -> None:
    supabase = create_supabase_client()
    bot = create_bot(supabase)
    monitor_task = setup_monitor(bot, supabase)
    monitor_task.start()
    bot.run(get_env_variable("DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
