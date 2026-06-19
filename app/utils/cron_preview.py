from typing import Optional
from datetime import datetime, timedelta
from apscheduler.triggers.cron import CronTrigger


def get_next_run_times(cron_expr: str, count: int = 5) -> list[str]:
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        now = datetime.now(trigger.timezone)
        times = []
        for _ in range(count):
            next_time = trigger.get_next_fire_time(None, now)
            if next_time is None:
                break
            times.append(next_time.strftime("%Y-%m-%d %H:%M:%S"))
            now = next_time + timedelta(seconds=1)
        return times
    except Exception:
        return []
