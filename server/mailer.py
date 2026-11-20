"""Booking e-mails. Does nothing unless SMTP_HOST is set in .env."""
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage

from . import config

WEEKDAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
          "augusti", "september", "oktober", "november", "december"]


def pretty(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt.day} {MONTHS[dt.month - 1]} kl. {dt:%H:%M}"


def _send(to: str, subject: str, body: str) -> None:
    host = config.get("SMTP_HOST")
    if not host or not to:
        return
    message = EmailMessage()
    message["From"] = config.get("MAIL_FROM") or config.get("SMTP_USER")
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, int(config.get("SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls()
            if config.get("SMTP_USER"):
                smtp.login(config.get("SMTP_USER"), config.get("SMTP_PASSWORD"))
            smtp.send_message(message)
    except Exception as error:  # a failed e-mail must never break a booking
        print(f"[mail] could not send to {to}: {error}")


def send(to: str, subject: str, body: str) -> None:
    threading.Thread(target=_send, args=(to, subject, body), daemon=True).start()


def booking_event(kind: str, booking: dict) -> None:
    """kind: 'created', 'moved' or 'cancelled'. Mails the customer and the barber."""
    when = pretty(datetime.strptime(booking["start"], "%Y-%m-%dT%H:%M"))
    link = f"{config.get('PUBLIC_URL').rstrip('/')}/bokning?t={booking['token']}"
    subject = {
        "created": f"Bokningsbekräftelse – {when}",
        "moved": f"Din tid är ändrad – {when}",
        "cancelled": "Din bokning är avbokad",
    }[kind]
    lead = {
        "created": "Tack för din bokning hos Warrior Barbershop!",
        "moved": "Din tid hos Warrior Barbershop har ändrats.",
        "cancelled": "Din tid hos Warrior Barbershop är avbokad.",
    }[kind]
    lines = [f"Hej {booking['customer_name']}!", "", lead, "",
             f"Tjänst: {booking['service']}", f"Tid: {when}",
             f"Pris: {booking['price_sek']} kr (betalas i salongen)",
             "Adress: Långholmsgatan 11, Stockholm", ""]
    if kind != "cancelled":
        lines += ["Behöver du boka om eller avboka? Använd länken:", link, ""]
    lines += ["Välkommen!", "Warrior Barbershop"]
    send(booking["email"], subject, "\n".join(lines))

    barber = {"created": "Ny bokning", "moved": "Ombokning", "cancelled": "Avbokning"}[kind]
    send(
        config.get("NOTIFY_EMAIL"),
        f"{barber}: {booking['customer_name']} – {when}",
        f"{barber}\n\n{booking['customer_name']} ({booking['phone']})\n{booking['service']}\n{when}\n"
        + (f"\nMeddelande: {booking['note']}\n" if booking["note"] else ""),
    )
