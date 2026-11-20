"""Warrior Barbershop - website and booking API."""
import hmac
import re
import secrets
import time as clock
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session

from . import config, db, mailer
from .availability import fmt, is_free, now_local, parse, slots_for_day

ENV_CREATED = config.load()
db.init()

PUBLIC_DIR = config.ROOT / "public"
app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
app.config.update(
    SECRET_KEY=config.get("SECRET_KEY"),
    SESSION_COOKIE_NAME="warrior_admin",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.get("COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=64 * 1024,
)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d{7,15}$")


# ---------------------------------------------------------------- plumbing

class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@app.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return jsonify(error=error.message), error.status


@app.errorhandler(404)
def handle_not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="Hittades inte."), 404
    return send_from_directory(PUBLIC_DIR, "404.html"), 404


@app.errorhandler(405)
def handle_bad_method(_error):
    return jsonify(error="Metoden stöds inte."), 405


@app.errorhandler(413)
def handle_too_large(_error):
    return jsonify(error="För mycket data."), 413


def conn():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


@app.after_request
def add_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.path.startswith("/api/") or request.path in ("/admin", "/bokning"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Transaction:
    """BEGIN IMMEDIATE takes the write lock up front, so two people can never
    both pass the "is this time free?" check for the same slot."""

    def __enter__(self):
        conn().execute("BEGIN IMMEDIATE")
        return conn()

    def __exit__(self, exc_type, _exc, _tb):
        conn().execute("ROLLBACK" if exc_type else "COMMIT")
        return False


_hits: dict = {}


def rate_limit(bucket: str, limit: int, per_seconds: int, message: str) -> None:
    key = (bucket, request.remote_addr or "?")
    now = clock.monotonic()
    recent = [t for t in _hits.get(key, []) if now - t < per_seconds]
    if len(recent) >= limit:
        _hits[key] = recent
        raise ApiError(429, message)
    recent.append(now)
    _hits[key] = recent


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Ogiltig förfrågan.")
    return data


def text(data: dict, key: str, label: str, max_len: int, required: bool = False) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ApiError(400, f"{label}: ogiltigt värde.")
    value = " ".join(value.split()) if key != "note" else value.strip()
    if required and not value:
        raise ApiError(400, f"{label} måste fyllas i.")
    if len(value) > max_len:
        raise ApiError(400, f"{label} är för långt (max {max_len} tecken).")
    return value


def integer(value, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ApiError(400, f"{label}: ogiltigt värde.")
    try:
        number = int(value)
    except ValueError:
        raise ApiError(400, f"{label}: ogiltigt värde.") from None
    if not low <= number <= high:
        raise ApiError(400, f"{label} måste vara mellan {low} och {high}.")
    return number


def a_date(value, label: str = "Datum") -> date:
    try:
        return date.fromisoformat(value if isinstance(value, str) else "")
    except ValueError:
        raise ApiError(400, f"{label}: ogiltigt datum.") from None


def a_datetime(value, label: str = "Tid") -> datetime:
    try:
        return parse(value if isinstance(value, str) else "")
    except ValueError:
        raise ApiError(400, f"{label}: ogiltig tid.") from None


def a_time(value, label: str) -> str:
    if not isinstance(value, str) or not TIME_RE.match(value):
        raise ApiError(400, f"{label}: ogiltig tid.")
    return value


def customer_fields(data: dict, strict: bool) -> dict:
    """strict = a customer booking online: phone required and checked."""
    name = text(data, "customer_name", "Namn", 80, required=True)
    phone = re.sub(r"[\s\-()]", "", text(data, "phone", "Telefon", 30, required=strict))
    email = text(data, "email", "E-post", 120).lower()
    note = text(data, "note", "Meddelande", 300)
    if strict and len(name) < 2:
        raise ApiError(400, "Skriv ditt namn.")
    if phone and not PHONE_RE.match(phone):
        raise ApiError(400, "Telefonnumret ser inte rätt ut.")
    if email and not EMAIL_RE.match(email):
        raise ApiError(400, "E-postadressen ser inte rätt ut.")
    return {"customer_name": name, "phone": phone, "email": email, "note": note}


def get_service(service_id, only_active: bool):
    row = conn().execute(
        "SELECT * FROM services WHERE id = ?", (integer(service_id, "Tjänst", 1, 10**9),)
    ).fetchone()
    if row is None or (only_active and not row["active"]):
        raise ApiError(400, "Tjänsten finns inte.")
    return row


BOOKING_SQL = (
    "SELECT b.*, s.name AS service, s.price_sek, s.duration_min"
    " FROM bookings b JOIN services s ON s.id = b.service_id"
)


def booking_json(row, admin: bool = False) -> dict:
    settings = db.get_settings(conn())
    start = parse(row["start_at"])
    data = {
        "token": row["token"],
        "service_id": row["service_id"],
        "service": row["service"],
        "price_sek": row["price_sek"],
        "start": row["start_at"],
        "end": row["end_at"],
        "status": row["status"],
        "customer_name": row["customer_name"],
        "phone": row["phone"],
        "email": row["email"],
        "note": row["note"],
        # Customers can change a booking themselves until this close to the start.
        "can_change": row["status"] == "booked"
        and now_local() + timedelta(minutes=settings["cancel_notice_min"]) <= start,
    }
    if admin:
        data.update(id=row["id"], source=row["source"], created_at=row["created_at"])
    return data


def service_json(row) -> dict:
    return {key: row[key] for key in ("id", "name", "description", "duration_min", "price_sek", "active", "sort")}


def serve_page(name: str):
    return send_from_directory(PUBLIC_DIR, name)


# ------------------------------------------------------------------- pages

@app.get("/")
def page_home():
    return serve_page("index.html")


@app.get("/admin")
def page_admin():
    return serve_page("admin.html")


@app.get("/bokning")
def page_booking():
    return serve_page("bokning.html")


# -------------------------------------------------------------- public API

@app.get("/api/info")
def api_info():
    c = conn()
    settings = db.get_settings(c)
    return jsonify(
        services=[service_json(r) for r in c.execute("SELECT * FROM services WHERE active = 1 ORDER BY sort, id")],
        hours=[dict(r) for r in c.execute("SELECT * FROM weekly_hours ORDER BY weekday")],
        today=now_local().date().isoformat(),
        max_days_ahead=settings["max_days_ahead"],
        cancel_notice_min=settings["cancel_notice_min"],
    )


def public_slots(day: date, service, exclude_booking_id=None):
    """Slots a customer may book: inside the booking window and with notice."""
    c = conn()
    settings = db.get_settings(c)
    now = now_local()
    if not now.date() <= day <= now.date() + timedelta(days=settings["max_days_ahead"]):
        return []
    earliest = now + timedelta(minutes=settings["min_notice_min"])
    return slots_for_day(c, day, service["duration_min"], settings["slot_step_min"], earliest, exclude_booking_id)


def booking_by_token(token: str):
    row = conn().execute(BOOKING_SQL + " WHERE b.token = ?", (token,)).fetchone()
    if row is None:
        raise ApiError(404, "Bokningen hittades inte.")
    return row


@app.get("/api/availability")
def api_availability():
    service = get_service(request.args.get("service_id"), only_active=True)
    first = a_date(request.args.get("from"))
    days = integer(request.args.get("days", "14"), "Antal dagar", 1, 31)
    exclude = None
    if request.args.get("token"):  # a customer moving their own booking
        exclude = booking_by_token(request.args["token"])["id"]
    result = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        result.append({"date": day.isoformat(), "slots": public_slots(day, service, exclude)})
    return jsonify(days=result)


@app.post("/api/bookings")
def api_create_booking():
    data = body()
    if data.get("website"):  # hidden field that only bots fill in
        raise ApiError(400, "Ogiltig förfrågan.")
    rate_limit("book", 6, 3600, "För många bokningar på kort tid. Försök igen senare eller ring oss.")
    service = get_service(data.get("service_id"), only_active=True)
    start = a_datetime(data.get("start"))
    fields = customer_fields(data, strict=True)
    end = start + timedelta(minutes=service["duration_min"])
    token = secrets.token_urlsafe(18)

    with Transaction() as c:
        if start.strftime("%H:%M") not in public_slots(start.date(), service):
            raise ApiError(409, "Tiden är tyvärr inte längre ledig. Välj en annan tid.")
        upcoming = c.execute(
            "SELECT COUNT(*) FROM bookings WHERE phone = ? AND status = 'booked' AND start_at > ?",
            (fields["phone"], fmt(now_local())),
        ).fetchone()[0]
        if upcoming >= 3:
            raise ApiError(409, "Du har redan flera kommande bokningar. Ring oss om du behöver fler.")
        c.execute(
            "INSERT INTO bookings (service_id, start_at, end_at, customer_name, phone, email, note,"
            " source, token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'web', ?, ?)",
            (service["id"], fmt(start), fmt(end), fields["customer_name"], fields["phone"],
             fields["email"], fields["note"], token, fmt(now_local())),
        )
    booking = booking_json(booking_by_token(token))
    mailer.booking_event("created", booking)
    return jsonify(booking=booking), 201


@app.get("/api/bookings/<token>")
def api_get_booking(token):
    return jsonify(booking=booking_json(booking_by_token(token)))


def require_changeable(row) -> None:
    if row["status"] != "booked":
        raise ApiError(409, "Bokningen är redan avbokad.")
    if not booking_json(row)["can_change"]:
        raise ApiError(409, "Det är för nära inpå för att ändra online. Ring oss så hjälper vi dig.")


@app.post("/api/bookings/<token>/cancel")
def api_cancel_booking(token):
    with Transaction() as c:
        row = booking_by_token(token)
        require_changeable(row)
        c.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (row["id"],))
    booking = booking_json(booking_by_token(token))
    mailer.booking_event("cancelled", booking)
    return jsonify(booking=booking)


@app.post("/api/bookings/<token>/reschedule")
def api_reschedule_booking(token):
    start = a_datetime(body().get("start"))
    with Transaction() as c:
        row = booking_by_token(token)
        require_changeable(row)
        service = get_service(row["service_id"], only_active=False)
        if start.strftime("%H:%M") not in public_slots(start.date(), service, row["id"]):
            raise ApiError(409, "Tiden är tyvärr inte längre ledig. Välj en annan tid.")
        end = start + timedelta(minutes=service["duration_min"])
        c.execute("UPDATE bookings SET start_at = ?, end_at = ? WHERE id = ?", (fmt(start), fmt(end), row["id"]))
    booking = booking_json(booking_by_token(token))
    mailer.booking_event("moved", booking)
    return jsonify(booking=booking)


# --------------------------------------------------------------- admin API

def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            raise ApiError(401, "Logga in först.")
        # Browsers never add this header to cross-site form posts.
        if request.method != "GET" and request.headers.get("X-Requested-With") != "fetch":
            raise ApiError(403, "Ogiltig förfrågan.")
        return view(*args, **kwargs)
    return wrapper


@app.post("/api/admin/login")
def api_login():
    rate_limit("login", 8, 600, "För många försök. Vänta tio minuter och försök igen.")
    password = body().get("password")
    expected = config.get("ADMIN_PASSWORD")
    if not expected or not isinstance(password, str) or not hmac.compare_digest(
        password.encode(), expected.encode()
    ):
        raise ApiError(401, "Fel lösenord.")
    session.clear()
    session["admin"] = True
    session.permanent = True
    return jsonify(ok=True)


@app.post("/api/admin/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/admin/me")
def api_me():
    return jsonify(admin=bool(session.get("admin")))


@app.get("/api/admin/bookings")
@admin_required
def api_admin_bookings():
    first = a_date(request.args.get("from"), "Från")
    last = a_date(request.args.get("to"), "Till")  # exclusive
    rows = conn().execute(
        BOOKING_SQL + " WHERE b.start_at >= ? AND b.start_at < ? ORDER BY b.start_at, b.id",
        (first.isoformat() + "T00:00", last.isoformat() + "T00:00"),
    ).fetchall()
    return jsonify(bookings=[booking_json(r, admin=True) for r in rows])


@app.get("/api/admin/availability")
@admin_required
def api_admin_availability():
    """Free times for the barber: no notice rule, and can skip one booking."""
    service = get_service(request.args.get("service_id"), only_active=False)
    day = a_date(request.args.get("date"))
    exclude = request.args.get("exclude_id")
    exclude = integer(exclude, "Bokning", 1, 10**9) if exclude else None
    step = db.get_settings(conn())["slot_step_min"]
    return jsonify(slots=slots_for_day(conn(), day, service["duration_min"], step, datetime.min, exclude))


def admin_booking(booking_id: int):
    row = conn().execute(BOOKING_SQL + " WHERE b.id = ?", (booking_id,)).fetchone()
    if row is None:
        raise ApiError(404, "Bokningen hittades inte.")
    return row


@app.post("/api/admin/bookings")
@admin_required
def api_admin_create_booking():
    data = body()
    service = get_service(data.get("service_id"), only_active=False)
    start = a_datetime(data.get("start"))
    fields = customer_fields(data, strict=False)
    end = start + timedelta(minutes=service["duration_min"])
    token = secrets.token_urlsafe(18)
    with Transaction() as c:
        # The barber may book outside opening hours, but never on top of something.
        if not is_free(c, start, end, within_hours=False):
            raise ApiError(409, "Tiden krockar med en annan bokning eller blockerad tid.")
        cursor = c.execute(
            "INSERT INTO bookings (service_id, start_at, end_at, customer_name, phone, email, note,"
            " source, token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'admin', ?, ?)",
            (service["id"], fmt(start), fmt(end), fields["customer_name"], fields["phone"],
             fields["email"], fields["note"], token, fmt(now_local())),
        )
    booking = booking_json(admin_booking(cursor.lastrowid), admin=True)
    mailer.booking_event("created", booking)
    return jsonify(booking=booking), 201


@app.patch("/api/admin/bookings/<int:booking_id>")
@admin_required
def api_admin_update_booking(booking_id):
    """Rebook (start / service), edit customer details, cancel or restore."""
    data = body()
    with Transaction() as c:
        row = admin_booking(booking_id)
        service = get_service(data.get("service_id", row["service_id"]), only_active=False)
        start = a_datetime(data["start"]) if "start" in data else parse(row["start_at"])
        end = start + timedelta(minutes=service["duration_min"])
        status = data.get("status", row["status"])
        if status not in ("booked", "cancelled"):
            raise ApiError(400, "Ogiltig status.")
        merged = {key: data.get(key, row[key]) for key in ("customer_name", "phone", "email", "note")}
        fields = customer_fields(merged, strict=False)

        moved = fmt(start) != row["start_at"] or fmt(end) != row["end_at"]
        restored = status == "booked" and row["status"] == "cancelled"
        if status == "booked" and (moved or restored) and not is_free(c, start, end, booking_id, within_hours=False):
            raise ApiError(409, "Tiden krockar med en annan bokning eller blockerad tid.")
        c.execute(
            "UPDATE bookings SET service_id = ?, start_at = ?, end_at = ?, status = ?,"
            " customer_name = ?, phone = ?, email = ?, note = ? WHERE id = ?",
            (service["id"], fmt(start), fmt(end), status, fields["customer_name"], fields["phone"],
             fields["email"], fields["note"], booking_id),
        )
    booking = booking_json(admin_booking(booking_id), admin=True)
    if status == "cancelled" and row["status"] == "booked":
        mailer.booking_event("cancelled", booking)
    elif status == "booked" and (moved or restored):
        mailer.booking_event("moved", booking)
    return jsonify(booking=booking)


def conflicts(start: str, end: str) -> int:
    """How many active bookings fall inside a period the barber just closed."""
    return conn().execute(
        "SELECT COUNT(*) FROM bookings WHERE status = 'booked' AND start_at < ? AND end_at > ?", (end, start)
    ).fetchone()[0]


@app.get("/api/admin/schedule")
@admin_required
def api_schedule():
    c = conn()
    now = now_local()
    return jsonify(
        hours=[dict(r) for r in c.execute("SELECT * FROM weekly_hours ORDER BY weekday")],
        overrides=[dict(r) for r in c.execute(
            "SELECT * FROM date_overrides WHERE day >= ? ORDER BY day", (now.date().isoformat(),))],
        time_off=[dict(r) for r in c.execute(
            "SELECT * FROM time_off WHERE end_at > ? ORDER BY start_at", (fmt(now),))],
        settings=db.get_settings(c),
    )


@app.put("/api/admin/hours")
@admin_required
def api_set_hours():
    days = body().get("hours")
    if not isinstance(days, list) or len(days) != 7:
        raise ApiError(400, "Ogiltigt schema.")
    cleaned = []
    for weekday, item in enumerate(days):
        if not isinstance(item, dict):
            raise ApiError(400, "Ogiltigt schema.")
        closed = bool(item.get("closed"))
        open_time = a_time(item.get("open_time"), "Öppnar")
        close_time = a_time(item.get("close_time"), "Stänger")
        if not closed and close_time <= open_time:
            raise ApiError(400, "Stängningstiden måste vara efter öppningstiden.")
        cleaned.append((open_time, close_time, int(closed), weekday))
    with Transaction() as c:
        c.executemany("UPDATE weekly_hours SET open_time = ?, close_time = ?, closed = ? WHERE weekday = ?", cleaned)
    return jsonify(ok=True)


@app.put("/api/admin/overrides/<day>")
@admin_required
def api_set_override(day):
    data = body()
    the_day = a_date(day)
    closed = bool(data.get("closed"))
    note = text(data, "note", "Anteckning", 120)
    open_time = close_time = None
    if not closed:
        open_time = a_time(data.get("open_time"), "Öppnar")
        close_time = a_time(data.get("close_time"), "Stänger")
        if close_time <= open_time:
            raise ApiError(400, "Stängningstiden måste vara efter öppningstiden.")
    with Transaction() as c:
        c.execute(
            "INSERT INTO date_overrides (day, open_time, close_time, closed, note) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(day) DO UPDATE SET open_time = excluded.open_time,"
            " close_time = excluded.close_time, closed = excluded.closed, note = excluded.note",
            (the_day.isoformat(), open_time, close_time, int(closed), note),
        )
    iso = the_day.isoformat()
    if closed:
        affected = conflicts(iso + "T00:00", iso + "T24:00")
    else:  # bookings that now fall before opening or after closing
        affected = conflicts(iso + "T00:00", f"{iso}T{open_time}") + conflicts(f"{iso}T{close_time}", iso + "T24:00")
    return jsonify(ok=True, conflicts=affected)


@app.delete("/api/admin/overrides/<day>")
@admin_required
def api_delete_override(day):
    with Transaction() as c:
        c.execute("DELETE FROM date_overrides WHERE day = ?", (a_date(day).isoformat(),))
    return jsonify(ok=True)


@app.post("/api/admin/time-off")
@admin_required
def api_add_time_off():
    data = body()
    start = a_datetime(data.get("start"), "Från")
    end = a_datetime(data.get("end"), "Till")
    note = text(data, "note", "Anteckning", 120)
    if end <= start:
        raise ApiError(400, "Sluttiden måste vara efter starttiden.")
    with Transaction() as c:
        c.execute("INSERT INTO time_off (start_at, end_at, note) VALUES (?, ?, ?)", (fmt(start), fmt(end), note))
    return jsonify(ok=True, conflicts=conflicts(fmt(start), fmt(end))), 201


@app.delete("/api/admin/time-off/<int:item_id>")
@admin_required
def api_delete_time_off(item_id):
    with Transaction() as c:
        c.execute("DELETE FROM time_off WHERE id = ?", (item_id,))
    return jsonify(ok=True)


@app.get("/api/admin/services")
@admin_required
def api_admin_services():
    return jsonify(services=[service_json(r) for r in conn().execute("SELECT * FROM services ORDER BY sort, id")])


def service_fields(data: dict) -> tuple:
    return (
        text(data, "name", "Namn", 60, required=True),
        text(data, "description", "Beskrivning", 200),
        integer(data.get("duration_min"), "Längd", 5, 480),
        integer(data.get("price_sek"), "Pris", 0, 100000),
        int(bool(data.get("active", True))),
        integer(data.get("sort", 0), "Ordning", 0, 1000),
    )


@app.post("/api/admin/services")
@admin_required
def api_add_service():
    fields = service_fields(body())
    with Transaction() as c:
        c.execute(
            "INSERT INTO services (name, description, duration_min, price_sek, active, sort)"
            " VALUES (?, ?, ?, ?, ?, ?)", fields)
    return jsonify(ok=True), 201


@app.put("/api/admin/services/<int:service_id>")
@admin_required
def api_update_service(service_id):
    fields = service_fields(body())
    with Transaction() as c:
        updated = c.execute(
            "UPDATE services SET name = ?, description = ?, duration_min = ?, price_sek = ?,"
            " active = ?, sort = ? WHERE id = ?", fields + (service_id,)).rowcount
    if not updated:
        raise ApiError(404, "Tjänsten finns inte.")
    return jsonify(ok=True)


@app.put("/api/admin/settings")
@admin_required
def api_set_settings():
    data = body()
    limits = {
        "slot_step_min": ("Tidsintervall", 5, 120),
        "min_notice_min": ("Framförhållning", 0, 7 * 24 * 60),
        "max_days_ahead": ("Bokningsfönster", 1, 365),
        "cancel_notice_min": ("Avbokningsgräns", 0, 7 * 24 * 60),
    }
    values = [(key, str(integer(data[key], label, low, high)))
              for key, (label, low, high) in limits.items() if key in data]
    with Transaction() as c:
        c.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value", values)
    return jsonify(ok=True)
