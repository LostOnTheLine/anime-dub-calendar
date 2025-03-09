import requests
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta, date
import re
import os
import json
import hashlib
import sqlite3
import aiosqlite

# Manual mapping for streaming providers (override or add when MAL data is missing/inaccurate)
MANUAL_STREAMING = {
    "Yu-Gi-Oh: Go Rush": {"provider": "DisneyNow", "emoji": "🐭", "dub": "DisneyNow"},
}

# Streaming provider emojis and USA prioritization (order defines priority)
STREAMING_PROVIDERS = {
    "HiDive": "🐵",
    "Crunchyroll": "🍥",
    "Disney+": "🏰",
    "Netflix": "🅽",
    "Amazon Prime Video": "ⓐ",
    "Hulu": "ⓗ",
    "Tubi": "🇹",
    "Fubo": "🇫",
    "Max": "Ⓜ️",
    "RetroCrush": "📼",
    "Ani-One Asia": None,
    "Bahamut Anime Crazy": None,
    "Bilibili Global": None,
    "Anime Digital Network": None,
    "Anime Generation": None,
    "CatchPlay": None,
    "Laftel": None,
    "MeWatch": None,
    "Muse Asia": None
}

# Cache for MAL data to avoid duplicate requests
MAL_CACHE = {}

# Scrape the forum post (for weekly update)
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

# Parse ongoing schedule from forum (for weekly update)
def parse_ongoing_schedule():
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
                    total_ep = 24 if current_ep < 20 else 56
                else:
                    total_ep = int(total_ep) if total_ep and total_ep != "?" else None
                mal_link_match = re.search(r'<a href="https?://myanimelist\.net/anime/(\d+)/[^"]+"[^>]*>([^<]+)</a>', line)
                mal_link = mal_link_match.group(0) if mal_link_match else None
                schedule[current_day].append({
                    "name": name.strip(),
                    "current": current_ep,
                    "total": total_ep,
                    "suspended": suspended == "**",
                    "mal_link": mal_link
                })
    return schedule

# Parse upcoming sections from forum (for weekly update)
def parse_upcoming_events():
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
            mal_link_match = re.search(r'<a href="https?://myanimelist\.net/anime/(\d+)/[^"]+"[^>]*>([^<]+)</a>', line)
            name = mal_link_match.group(2) if mal_link_match else line.split(" - ")[0].strip() if " - " in line else line.rstrip("*").strip()
            mal_link = mal_link_match.group(0) if mal_link_match else None
            date_str = match.group(1) if match else None
            upcoming.append({
                "name": name,
                "date": date_str,
                "theatrical": is_theatrical,
                "section": current_section,
                "mal_link": mal_link
            })
    return upcoming

# Scrape MAL for streaming platforms and additional data (async)
async def fetch_mal_page(session, url):
    async with session.get(url, headers=headers) as response:
        return await response.text()

async def get_mal_info(mal_link=None, name=None):
    if mal_link:
        mal_url = re.search(r'href="([^"]+)"', mal_link).group(1)
        cache_key = mal_url
    elif name:
        search_url = f"https://myanimelist.net/anime.php?q={requests.utils.quote(name)}&cat=anime"
        async with aiohttp.ClientSession() as session:
            search_response = await fetch_mal_page(session, search_url)
        search_soup = BeautifulSoup(search_response, "html.parser")
        anime_link = search_soup.select_one(".hoverinfo_trigger")
        if anime_link:
            mal_id = anime_link["id"].replace("sarea", "")
            mal_url = f"https://myanimelist.net/anime/{mal_id}/{requests.utils.quote(name.replace(' ', '_'))}"
            cache_key = mal_url
        else:
            print(f"No MAL entry found for {name}")
            return {"streaming": [], "broadcast": "", "producers": [], "studios": [], "source": "", "genres": [], "theme": [], "demographic": "", "duration": "", "rating": ""}
    else:
        return {"streaming": [], "broadcast": "", "producers": [], "studios": [], "source": [], "genres": [], "theme": [], "demographic": "", "duration": "", "rating": ""}

    if cache_key in MAL_CACHE:
        print(f"Cache hit for {cache_key}")
        return MAL_CACHE[cache_key]

    print(f"Fetching MAL page: {mal_url}")
    async with aiohttp.ClientSession() as session:
        mal_response = await fetch_mal_page(session, mal_url)
    mal_soup = BeautifulSoup(mal_response, "html.parser")
    
    streaming_div = mal_soup.select_one(".broadcasts")
    streaming_list = []
    if streaming_div:
        for item in streaming_div.select(".broadcast-item .caption"):
            streaming_list.append(item.text.strip())
    print(f"Streaming providers: {streaming_list}")

    broadcast = mal_soup.select_one(".spaceit_pad:contains('Broadcast:')")
    broadcast = broadcast.text.strip().replace("Broadcast:", "").strip() if broadcast else ""
    producers = [a.text for a in mal_soup.select(".spaceit_pad:contains('Producers:') a")] if mal_soup.select_one(".spaceit_pad:contains('Producers:')") else []
    studios = [a.text for a in mal_soup.select(".spaceit_pad:contains('Studios:') a")] if mal_soup.select_one(".spaceit_pad:contains('Studios:')") else []
    source = mal_soup.select_one(".spaceit_pad:contains('Source:') a")
    source = source.text.strip() if source else mal_soup.select_one(".spaceit_pad:contains('Source:')").text.strip().replace("Source:", "").strip() if mal_soup.select_one(".spaceit_pad:contains('Source:')") else ""
    genres = [a.text for a in mal_soup.select(".spaceit_pad:contains('Genres:') a")] if mal_soup.select_one(".spaceit_pad:contains('Genres:')") else []
    theme = [a.text for a in mal_soup.select(".spaceit_pad:contains('Theme:') a")] if mal_soup.select_one(".spaceit_pad:contains('Theme:')") else []
    demographic = mal_soup.select_one(".spaceit_pad:contains('Demographic:') a")
    demographic = demographic.text if demographic else mal_soup.select_one(".spaceit_pad:contains('Demographic:')").text.strip().replace("Demographic:", "").strip() if mal_soup.select_one(".spaceit_pad:contains('Demographic:')") else ""
    duration = mal_soup.select_one(".spaceit_pad:contains('Duration:')")
    duration = duration.text.strip().replace("Duration:", "").strip() if duration else ""
    rating = mal_soup.select_one(".spaceit_pad:contains('Rating:')")
    rating = rating.text.strip().replace("Rating:", "").strip() if rating else "Not Listed"

    result = {
        "streaming": streaming_list,
        "broadcast": broadcast,
        "producers": producers,
        "studios": studios,
        "source": source,
        "genres": genres,
        "theme": theme,
        "demographic": demographic,
        "duration": duration,
        "rating": rating
    }
    MAL_CACHE[cache_key] = result
    return result

# Google Calendar setup
SCOPES = ["https://www.googleapis.com/auth/calendar"]
credentials_json = os.getenv("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
creds = service_account.Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
service = build("calendar", "v3", credentials=creds)
calendar_id = os.getenv("CALENDAR_ID")
print(f"Calendar ID: {calendar_id}")

# Color assignment
available_colors = ["1", "2", "3", "5", "6", "7", "9", "10"]
suspended_color = "4"
upcoming_color = "11"

def get_color_id(show_name, day_shows, used_colors):
    hash_value = int(hashlib.md5(show_name.encode()).hexdigest(), 16)
    color_index = hash_value % len(available_colors)
    base_color = available_colors[color_index]
    if base_color in used_colors and len(used_colors) < len(available_colors):
        for color in available_colors:
            if color not in used_colors:
                return color
    return base_color

# Batch calendar updates
def batch_insert_events(events):
    batch = service.new_batch_http_request()
    for event in events:
        batch.add(service.events().insert(calendarId=calendar_id, body=event))
    batch.execute()

# Clear future events only
current_date = datetime.now()
today = current_date.date()
page_token = None
while True:
    events = service.events().list(calendarId=calendar_id, pageToken=page_token).execute()
    for event in events["items"]:
        start = event["start"].get("date") or event["start"].get("dateTime")
        if start:
            event_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
            if event_date > today:  # Preserve today and past events
                service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
    page_token = events.get("nextPageToken")
    if not page_token:
        break

# Add all-day events for ongoing schedule
def next_weekday(start_date, weekday):
    days_ahead = weekday - start_date.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return start_date + timedelta(days=days_ahead)

# Process all MAL info requests asynchronously
async def process_mal_info(shows):
    tasks = []
    for show in shows:
        mal_link = show.get("mal_link")
        name = show.get("name", show.get("title", "Unknown Show"))
        tasks.append(get_mal_info(mal_link, name))
    return await asyncio.gather(*tasks)

# Load ongoing shows from SQLite
async def load_ongoing_shows():
    async with aiosqlite.connect("shows.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ongoing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT,
                name TEXT,
                current INTEGER,
                total INTEGER,
                suspended INTEGER,
                mal_link TEXT
            )
        """)
        await db.commit()
        cursor = await db.execute("SELECT day, name, current, total, suspended, mal_link FROM ongoing")
        rows = await cursor.fetchall()
        schedule = {}
        for row in rows:
            day, name, current, total, suspended, mal_link = row
            if day not in schedule:
                schedule[day] = []
            schedule[day].append({
                "name": name,
                "current": current,
                "total": total,
                "suspended": bool(suspended),
                "mal_link": mal_link
            })
        return schedule

# Load upcoming events from SQLite
async def load_upcoming_events():
    async with aiosqlite.connect("shows.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS upcoming (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                date TEXT,
                theatrical INTEGER,
                section TEXT,
                mal_link TEXT
            )
        """)
        await db.commit()
        cursor = await db.execute("SELECT name, date, theatrical, section, mal_link FROM upcoming")
        rows = await cursor.fetchall()
        return [{"name": row[0], "date": row[1], "theatrical": bool(row[2]), "section": row[3], "mal_link": row[4]} for row in rows]

# Process ongoing shows
def process_ongoing_events(ongoing_data):
    ongoing_events = []
    for day, shows in ongoing_data.items():
        day_index = day_map[day]
        used_colors = set()
        
        loop = asyncio.get_event_loop()
        mal_infos = loop.run_until_complete(process_mal_info(shows))
        
        for show, mal_info in zip(shows, mal_infos):
            latest_episode = show["current"]
            total_ep = show["total"] or 10
            base_date = next_weekday(current_date, day_index)
            streaming = mal_info["streaming"]
            manual = MANUAL_STREAMING.get(show["name"])
            if manual:
                main_provider = manual["provider"]
                emoji = manual["emoji"]
                description_part = f"[Dub: {manual['dub']}]" if manual.get("dub") else ""
            else:
                main_provider = None
                for provider in STREAMING_PROVIDERS.keys():
                    if any(provider.lower() == s.lower() for s in streaming):
                        main_provider = provider
                        break
                emoji = STREAMING_PROVIDERS.get(main_provider, "⛔") if main_provider else "⛔"
                description_part = ""
            print(f"Show: {show['name']}, Main Provider: {main_provider}, Emoji: {emoji}")
            
            color_id = suspended_color if show["suspended"] else get_color_id(show["name"], shows, used_colors)
            if not show["suspended"]:
                used_colors.add(color_id)

            if show["suspended"]:
                if base_date.date() >= today:
                    description_lines = [f"Rating: {mal_info['rating']}"]
                    if streaming:
                        description_lines.append(f"Streaming: {', '.join(streaming)}")
                    if mal_info["broadcast"]:
                        description_lines.append(f"Broadcast: {mal_info['broadcast']}")
                    if mal_info["genres"]:
                        description_lines.append(f"Genres: {', '.join(mal_info['genres'])}")
                    if mal_info["theme"]:
                        description_lines.append(f"Theme: {', '.join(mal_info['theme'])}")
                    if mal_info["studios"]:
                        description_lines.append(f"Studios: {', '.join(mal_info['studios'])}")
                    if mal_info["producers"]:
                        description_lines.append(f"Producers: {', '.join(mal_info['producers'])}")
                    if mal_info["source"]:
                        description_lines.append(f"Source: {mal_info['source']}")
                    if mal_info["demographic"]:
                        description_lines.append(f"Demographic: {mal_info['demographic']}")
                    if mal_info["duration"]:
                        description_lines.append(f"Duration: {mal_info['duration']}")
                    description = f"{description_part}\n** = Dub production suspended until further notice.\n" + "\n".join(description_lines)

                    event = {
                        "summary": f"{emoji}{show['name']} (Suspended) [Latest Episode {latest_episode}/{total_ep or '?'}]",
                        "description": description,
                        "start": {"date": base_date.strftime("%Y-%m-%d")},
                        "end": {"date": base_date.strftime("%Y-%m-%d")},
                        "recurrence": ["RRULE:FREQ=WEEKLY"],
                        "colorId": color_id
                    }
                    ongoing_events.append(event)
            else:
                for ep in range(latest_episode + 1, min(total_ep + 1, latest_episode + 11)):
                    ep_date = base_date + timedelta(weeks=(ep - latest_episode - 1))
                    if ep_date.date() >= today:
                        description_lines = [f"Rating: {mal_info['rating']}"]
                        if streaming:
                            description_lines.append(f"Streaming: {', '.join(streaming)}")
                        if mal_info["broadcast"]:
                            description_lines.append(f"Broadcast: {mal_info['broadcast']}")
                        if mal_info["genres"]:
                            description_lines.append(f"Genres: {', '.join(mal_info['genres'])}")
                        if mal_info["theme"]:
                            description_lines.append(f"Theme: {', '.join(mal_info['theme'])}")
                        if mal_info["studios"]:
                            description_lines.append(f"Studios: {', '.join(mal_info['studios'])}")
                        if mal_info["producers"]:
                            description_lines.append(f"Producers: {', '.join(mal_info['producers'])}")
                        if mal_info["source"]:
                            description_lines.append(f"Source: {mal_info['source']}")
                        if mal_info["demographic"]:
                            description_lines.append(f"Demographic: {mal_info['demographic']}")
                        if mal_info["duration"]:
                            description_lines.append(f"Duration: {mal_info['duration']}")
                        description = f"{description_part}\n" + "\n".join(description_lines) if description_lines else description_part

                        event = {
                            "summary": f"{emoji}{show['name']} S{(latest_episode // 100) + 1:02d}E{ep:02d} (Expected)",
                            "description": description,
                            "start": {"date": ep_date.strftime("%Y-%m-%d")},
                            "end": {"date": ep_date.strftime("%Y-%m-%d")},
                            "colorId": color_id
                        }
                        ongoing_events.append(event)
    return ongoing_events

# Process upcoming events
def process_upcoming_events(upcoming_data):
    upcoming_events = []
    loop = asyncio.get_event_loop()
    upcoming_mal_infos = loop.run_until_complete(process_mal_info(upcoming_data))

    for item, mal_info in zip(upcoming_data, upcoming_mal_infos):
        if item["date"]:
            event_date = datetime.strptime(item["date"], "%B %d, %Y").date()
            if event_date >= today:
                streaming = mal_info["streaming"]
                manual = MANUAL_STREAMING.get(item["name"])
                if manual:
                    main_provider = manual["provider"]
                    emoji = manual["emoji"]
                    description_part = f"[Dub: {manual['dub']}]" if manual.get("dub") else ""
                else:
                    main_provider = None
                    for provider in STREAMING_PROVIDERS.keys():
                        if any(provider.lower() == s.lower() for s in streaming):
                            main_provider = provider
                            break
                    emoji = STREAMING_PROVIDERS.get(main_provider, "⛔") if main_provider else "⛔"
                    description_part = ""
                print(f"Upcoming: {item['name']}, Main Provider: {main_provider}, Emoji: {emoji}")
                summary = f"🎟️{item['name']}" if item["theatrical"] else f"{emoji}{item['name']}"
                description_lines = [f"Rating: {mal_info['rating']}"]
                if streaming:
                    description_lines.append(f"Streaming: {', '.join(streaming)}")
                if mal_info["broadcast"]:
                    description_lines.append(f"Broadcast: {mal_info['broadcast']}")
                if mal_info["genres"]:
                    description_lines.append(f"Genres: {', '.join(mal_info['genres'])}")
                if mal_info["theme"]:
                    description_lines.append(f"Theme: {', '.join(mal_info['theme'])}")
                if mal_info["studios"]:
                    description_lines.append(f"Studios: {', '.join(mal_info['studios'])}")
                if mal_info["producers"]:
                    description_lines.append(f"Producers: {', '.join(mal_info['producers'])}")
                if mal_info["source"]:
                    description_lines.append(f"Source: {mal_info['source']}")
                if mal_info["demographic"]:
                    description_lines.append(f"Demographic: {mal_info['demographic']}")
                if mal_info["duration"]:
                    description_lines.append(f"Duration: {mal_info['duration']}")
                description = f"{description_part}\n{'🎟️ * = These are theatrical releases and not home/digital releases.' if item['theatrical'] else ''}\n" + "\n".join(description_lines)

                event = {
                    "summary": summary,
                    "description": description,
                    "start": {"date": event_date.strftime("%Y-%m-%d")},
                    "end": {"date": event_date.strftime("%Y-%m-%d")},
                    "colorId": upcoming_color
                }
                upcoming_events.append(event)
    return upcoming_events

try:
    # Load show data from SQLite
    loop = asyncio.get_event_loop()
    ongoing_data = loop.run_until_complete(load_ongoing_shows())
    upcoming_data = loop.run_until_complete(load_upcoming_events())

    ongoing_events = process_ongoing_events(ongoing_data)
    if ongoing_events:
        print(f"Inserting {len(ongoing_events)} ongoing events")
        batch_insert_events(ongoing_events)

    upcoming_events = process_upcoming_events(upcoming_data)
    if upcoming_events:
        print(f"Inserting {len(upcoming_events)} upcoming events")
        batch_insert_events(upcoming_events)

    print("Calendar updated successfully!")
except Exception as e:
    print(f"Error during execution: {e}")
    raise