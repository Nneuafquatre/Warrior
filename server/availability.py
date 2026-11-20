"""Working hours and free-slot calculation."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHOP_TZ = ZoneInfo("Europe/Stockholm")
FMT = "%Y-%m-%dT%H:%M"


def now_local() -> datetime:
    """Current shop time, as a naive datetime (matches what is stored)."""
    return datetime.now(SHOP_TZ).replace(tzinfo=None, second=0, microsecond=0)


def fmt(dt: datetime) -> str:
    return dt.strftime(FMT)


def parse(value: str) -> datetime:
    return datetime.strptime(value, FMT)


def day_window(conn, day: date):
    """Return (open, close) datetimes for a date, or None if the shop is closed."""
    row = conn.execute("SELECT * FROM date_overrides WHERE day = ?", (day.isoformat(),)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM weekly_hours WHERE weekday = ?", (day.weekday(),)).fetchone()
    if row is None or row["closed"] or not row["open_time"] or not row["close_time"]:
        return None
    start = datetime.combine(day, time.fromisoformat(row["open_time"]))
    end = datetime.combine(day, time.fromisoformat(row["close_time"]))
    return (start, end) if end > start else None


def busy_intervals(conn, start: datetime, end: datetime, exclude_booking_id=None):
    """Bookings and blocked time that overlap [start, end)."""
    params = (fmt(end), fmt(start))
    rows = conn.execute(
        "SELECT id, start_at, end_at FROM bookings"
        " WHERE status = 'booked' AND start_at < ? AND end_at > ?",
        params,
    ).fetchall()
    busy = [(parse(r["start_at"]), parse(r["end_at"])) for r in rows if r["id"] != exclude_booking_id]
    rows = conn.execute("SELECT start_at, end_at FROM time_off WHERE start_at < ? AND end_at > ?", params)
    busy += [(parse(r["start_at"]), parse(r["end_at"])) for r in rows]
    return busy


def is_free(conn, start: datetime, end: datetime, exclude_booking_id=None, within_hours=True) -> bool:
    if within_hours:
        window = day_window(conn, start.date())
        if window is None or start < window[0] or end > window[1]:
            return False
    return not busy_intervals(conn, start, end, exclude_booking_id)


def slots_for_day(conn, day: date, duration_min: int, step_min: int, earliest: datetime,
                  exclude_booking_id=None):
    """Free start times ("HH:MM") on a date for a service of the given length."""
    window = day_window(conn, day)
    if window is None:
        return []
    open_at, close_at = window
    busy = busy_intervals(conn, open_at, close_at, exclude_booking_id)
    length = timedelta(minutes=duration_min)
    step = timedelta(minutes=step_min)
    slots = []
    start = open_at
    while start + length <= close_at:
        end = start + length
        if start >= earliest and all(end <= b_start or start >= b_end for b_start, b_end in busy):
            slots.append(start.strftime("%H:%M"))
        start += step
    return slots
