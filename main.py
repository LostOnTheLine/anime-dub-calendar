import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta, date
import re
import os
import json
import hashlib

# Scrape the forum post
url = "https://myanimelist.net/forum/?topicid=1692966"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
response = requests.get(url, headers=headers)
print(f"Status Code: {response.status_code}")
soup = BeautifulSoup(response.content, "html.parser")
first_comment = soup.select_one(".forum-topic-message .content")

if first_comment is None:
    print("Error: Could not find '.forum-topic-message .content' in the page")
    print(f"Page snippet: {response.text[:500]}")
    exit(1)

print(f"First comment snippet: {first_comment.text[:200]}")
lines = first_comment.text.strip().split("\n")

# Parse ongoing schedule
schedule = {}
current_day = None
day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}

for line in lines:
    line = line.strip()
    if line in day_map:
        current_day = line
        schedule[current_day] = []
    elif line and current_day and "Episodes:" in line:
        match = re.match(r"(.+?)\s*\(Episodes:\s*(\d+)(?:/(\d+|\?{3}))?\)\s*(\*\*)?", line)
        if match:
            name, current_ep, total_ep, suspended = match.groups()
            current_ep = int(current_ep)
            if total_ep == "???":
                total_ep = 24 if current_ep < 20 else 56  # Estimate based on current episode
            else:
                total_ep = int(total_ep) if total_ep and total_ep != "?" else None
            schedule[current_day].append({
                "name": name.strip(),
                "current": current_ep,
                "total": total_ep,
                "suspended": suspended == "**"
            })

# Parse upcoming sections
upcoming = []
current_section = None
date_pattern = re.compile(r"(\w+ \d{1,2}, \d{4})")

for line in lines:
    line = line.strip()
    if "Upcoming SimulDubbed Anime for Winter 2025" in line or "Upcoming SimulDubbed Anime for Spring 2025" in line or "Upcoming Dubbed Anime" in line:
        current_section = line
    elif line and current_section and not line.startswith("* -"):
        match = date_pattern.search(line)
        is_theatrical = line.endswith("*")
        title = line.split(" - ")[0].strip() if " - " in line else line.rstrip("*").strip()
        date_str = match.group(1) if match else None
        upcoming.append({
            "title": title,
            "date": date_str,
            "theatrical": is_theatrical,
            "section": current_section
        })

# Google Calendar setup
SCOPES = ["https://www.googleapis.com/auth/calendar"]
credentials_json = os.getenv("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
creds = service_account.Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
service = build("calendar", "v3", credentials=creds)
calendar_id = os.getenv("CALENDAR_ID")
print(f"Calendar ID: {calendar_id}")

# Color assignment
available_colors = ["1", "2", "3", "5", "6", "7", "9", "10"]  # Exclude Flamingo (4) and Tomato (11)
suspended_color = "4"  # Flamingo for suspended shows
upcoming_color = "11"  # Tomato for upcoming events

def get_color_id(show_name, day_shows, used_colors):
    hash_value = int(hashlib.md5(show_name.encode()).hexdigest(), 16)
    color_index = hash_value % len(available_colors)
    base_color = available_colors[color_index]
    if base_color in used_colors and len(used_colors) < len(available_colors):
        for color in available_colors:
            if color not in used_colors:
                return color
    return base_color

# Clear only future events
current_date = datetime.now()
today = current_date.date()
page_token = None
while True:
    events = service.events().list(calendarId=calendar_id, pageToken=page_token).execute()
    for event in events["items"]:
        start = event["start"].get("date") or event["start"].get("dateTime")
        if start:
            event_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
            if event_date >= today:
                service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
    page_token = events.get("nextPageToken")
    if not page_token:
        break

# Add all-day events for ongoing schedule
def next_weekday(start_date, weekday):
    days_ahead = weekday - start_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return start_date + timedelta(days=days_ahead)

for day, shows in schedule.items():
    day_index = day_map[day]
    used_colors = set()
    
    for show in shows:
        latest_episode = show["current"]
        total_ep = show["total"] or 10  # Fallback still applies if parsing fails
        base_date = next_weekday(current_date, day_index)
        
        color_id = suspended_color if show["suspended"] else get_color_id(show["name"], shows, used_colors)
        if not show["suspended"]:
            used_colors.add(color_id)

        if show["suspended"]:
            if base_date.date() >= today:
                event = {
                    "summary": f"{show['name']} (Suspended) [Latest Episode {latest_episode}/{total_ep or '?'}]",
                    "description": "** = Dub production suspended until further notice.",
                    "start": {"date": base_date.strftime("%Y-%m-%d")},
                    "end": {"date": base_date.strftime("%Y-%m-%d")},
                    "recurrence": ["RRULE:FREQ=WEEKLY"],
                    "colorId": color_id
                }
                print(f"Inserting event: {json.dumps(event, indent=2)}")
                service.events().insert(calendarId=calendar_id, body=event).execute()
        else:
            for ep in range(latest_episode + 1, min(total_ep + 1, latest_episode + 11)):
                ep_date = base_date + timedelta(weeks=(ep - latest_episode - 1))
                if ep_date.date() >= today:
                    event = {
                        "summary": f"{show['name']} S{(latest_episode // 100) + 1:02d}E{ep:02d} (Expected)",
                        "start": {"date": ep_date.strftime("%Y-%m-%d")},
                        "end": {"date": ep_date.strftime("%Y-%m-%d")},
                        "colorId": color_id
                    }
                    print(f"Inserting event: {json.dumps(event, indent=2)}")
                    service.events().insert(calendarId=calendar_id, body=event).execute()

# Add upcoming events
for item in upcoming:
    if item["date"]:
        event_date = datetime.strptime(item["date"], "%B %d, %Y").date()
        if event_date >= today:
            summary = f"🎟️{item['title']}" if item["theatrical"] else item["title"]
            event = {
                "summary": summary,
                "description": "* = These are theatrical releases and not home/digital releases." if item["theatrical"] else None,
                "start": {"date": event_date.strftime("%Y-%m-%d")},
                "end": {"date": event_date.strftime("%Y-%m-%d")},
                "colorId": upcoming_color
            }
            print(f"Inserting event: {json.dumps(event, indent=2)}")
            service.events().insert(calendarId=calendar_id, body=event).execute()

print("Calendar updated successfully!")