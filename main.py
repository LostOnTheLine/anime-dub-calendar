import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
import re
import os
import json

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

# Parse the text
schedule = {}
current_day = None
day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}

for line in lines:
    line = line.strip()
    if line in day_map:
        current_day = line
        schedule[current_day] = []
    elif line and current_day and "Episodes:" in line:
        match = re.match(r"(.+?)\s*\(Episodes:\s*(\d+)(?:/(\d+|\?))?\)\s*(\*\*)?", line)
        if match:
            name, current_ep, total_ep, suspended = match.groups()
            total_ep = int(total_ep) if total_ep and total_ep != "?" else None
            schedule[current_day].append({
                "name": name.strip(),
                "current": int(current_ep),
                "total": total_ep,
                "suspended": suspended == "**"
            })

# Google Calendar setup
SCOPES = ["https://www.googleapis.com/auth/calendar"]
credentials_json = os.getenv("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
creds = service_account.Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
service = build("calendar", "v3", credentials=creds)
calendar_id = os.getenv("CALENDAR_ID")
print(f"Calendar ID: {calendar_id}")

# Clear existing events
page_token = None
while True:
    events = service.events().list(calendarId=calendar_id, pageToken=page_token).execute()
    for event in events["items"]:
        service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
    page_token = events.get("nextPageToken")
    if not page_token:
        break

# Add events
def next_weekday(start_date, weekday):
    days_ahead = weekday - start_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return start_date + timedelta(days=days_ahead)

current_date = datetime.now()
for day, shows in schedule.items():
    day_index = day_map[day]
    for show in shows:
        latest_episode = show["current"]
        total_ep = show["total"] or 999
        base_date = next_weekday(current_date, day_index)
        
        for ep in range(latest_episode + 1, min(total_ep + 1, latest_episode + 5)):
            ep_date = next_weekday(current_date, day_index) + timedelta(weeks=(ep - latest_episode - 1))
            start_time = ep_date.replace(hour=12, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=1)
            event = {
                "summary": f"{show['name']} S{(latest_episode // 100) + 1:02d}E{ep:02d} (Expected)",
                "start": {"dateTime": start_time.isoformat() + "Z", "timeZone": "UTC"},
                "end": {"dateTime": end_time.isoformat() + "Z", "timeZone": "UTC"},
                "colorId": "10"
            }
            if show["suspended"]:
                event["summary"] = f"{show['name']} (Suspended) [Latest Episode {latest_episode}/{total_ep or '?'}]"
                event["description"] = "** = Dub production suspended until further notice."
                event["colorId"] = "8"
            print(f"Inserting event: {json.dumps(event, indent=2)}")
            service.events().insert(calendarId=calendar_id, body=event).execute()

print("Calendar updated successfully!")