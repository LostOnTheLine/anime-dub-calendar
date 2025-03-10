from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
from datetime import datetime, timedelta
import yaml
from scraper import scrape_forum_post, load_cached_data, save_cached_data, needs_update

CALENDAR_ID = os.getenv("CALENDAR_ID")
TIMEZONE = "UTC"
STREAMING_EMOJIS = {
    "hidive": "🐵", "crunchyroll": "🍥", "disney+": "🏰", "netflix": "🅽",
    "amazon prime video": "ⓐ", "hulu": "ⓗ", "tubi": "🇹", "fubo": "🇫",
    "max": "Ⓜ️", "retrocrush": "📼"
}
COLORS = {
    "hidive": "Peacock", "disney+": "Cobalt", "netflix": "Tomato",
    "amazon prime video": "Banana", "hulu": "Sage", "tubi": "Amethyst",
    "fubo": "Pumpkin", "max": "Wisteria", "retrocrush": "Birch"
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def get_calendar_service():
    creds = Credentials.from_authorized_user_file("credentials.json")
    return build("calendar", "v3", credentials=creds)

def load_manual_overrides():
    try:
        with open("data/manual_overrides.yaml", "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

def get_next_day_date(day_name, ref_date=datetime.utcnow()):
    days_ahead = DAYS.index(day_name) - ref_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return ref_date + timedelta(days=days_ahead)

def create_event(service, title, start_date, all_day=False, color=None, description=None, recurring=False):
    event = {
        "summary": title,
        "start": {"date": start_date.strftime("%Y-%m-%d") if all_day else start_date.isoformat() + "Z"},
        "end": {"date": (start_date + timedelta(days=1)).strftime("%Y-%m-%d") if all_day else (start_date + timedelta(hours=1)).isoformat() + "Z"},
        "colorId": color,
        "description": description
    }
    if recurring:
        event["recurrence"] = ["RRULE:FREQ=WEEKLY;COUNT=52"]
    return service.events().insert(calendarId=CALENDAR_ID, body=event).execute()

def normalize_provider(provider):
    """Normalize provider name for case-insensitive matching."""
    return provider.lower()

def update_calendar():
    service = get_calendar_service()
    cached_data = load_cached_data()
    new_data = scrape_forum_post()
    manual_overrides = load_manual_overrides()

    if not new_data:
        return

    if needs_update(cached_data, new_data):
        # Clear future events
        now = datetime.utcnow().isoformat() + "Z"
        service.events().delete(calendarId=CALENDAR_ID, timeMin=now).execute()

        # Check update status
        cached_time = datetime.strptime(cached_data.get("last_updated", "Jan 1, 2000"), "%B %d, %Y")
        new_time = datetime.strptime(new_data["last_updated"], "%B %d, %Y")
        days_diff = (datetime.utcnow() - new_time).days

        if cached_data.get("mod_time") != new_data["mod_time"]:
            if days_diff > 3:
                create_event(service, "Parser Out Of Date", datetime.utcnow(), color="Tomato", description="Full scan required", all_day=False)
            elif days_diff > 1:
                create_event(service, "Parser Out Of Date", datetime.utcnow(), color="Tangerine", description="Data >1 day old", all_day=False)
            elif cached_time == new_time:
                create_event(service, "Parser Out Of Date", datetime.utcnow(), color="Banana", description="Time updated, no date change", all_day=False)

        # Process Currently Streaming
        for day, shows in new_data["sections"]["Currently Streaming SimulDubbed Anime"].items():
            next_date = get_next_day_date(day)
            for show in shows:
                title = show["title"]
                ep_current = show["current_episode"]
                ep_total = show["total_episodes"] or (24 if ep_current < 20 else ep_current + 8)
                season = "S01" if not re.search(r"Season \d+", title) else f"S{re.search(r'Season (\d+)', title).group(1):02d}"
                streaming = normalize_provider(manual_overrides.get(show["mal_id"], {}).get("streaming", "HIDIVE"))  # Default to HIDIVE
                emoji = STREAMING_EMOJIS.get(streaming, "⛔")
                color = COLORS.get(streaming, "Lavender")  # Default for Crunchyroll or others

                if show["suspended"]:
                    event_title = f"{emoji} {title} (Suspended) [Latest E{ep_current:02d}/{ep_total or '?'}]"
                    create_event(service, event_title, next_date, color="Flamingo", recurring=True)
                else:
                    for ep in range(ep_current + 1, (int(ep_total) if ep_total else ep_current + 8) + 1):
                        event_title = f"{emoji} {title} {season}E{ep:02d}/{ep_total or '?'}"
                        create_event(service, event_title, next_date + timedelta(weeks=ep - ep_current - 1), color=color)

        # Process Upcoming
        for section in ["Upcoming SimulDubbed Anime for Winter 2025", "Upcoming SimulDubbed Anime for Spring 2025", "Upcoming Dubbed Anime"]:
            for show in new_data["sections"][section]:
                date = datetime.strptime(show["date"], "%B %d, %Y")
                title = f"🎟 {show['title']} [Theatrical Release]" if "*" in show["title"] else show["title"]
                create_event(service, title, date, all_day=True)

        save_cached_data(new_data)

if __name__ == "__main__":
    update_calendar()