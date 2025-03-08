import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta, date
import re
import os
import json
import hashlib

# Manual mapping for streaming providers (override or add when MAL data is missing/inaccurate)
MANUAL_STREAMING = {
    "Yu-Gi-Oh: Go Rush": {"provider": "DisneyNow", "emoji": "📺", "dub": "DisneyNow"},  # Example for DisneyNow
    # Add more mappings as needed: {"show_name": {"provider": "Provider", "emoji": "Emoji", "dub": "DubProvider"}}
}

# Streaming provider emojis and USA prioritization (order defines priority)
STREAMING_PROVIDERS = {
    "HiDive": "🌀",           # USA priority, spiral for HiDive logo
    "Crunchyroll": "🍥",      # USA priority, fishcake resembles logo
    "Disney+": "🇩",          # USA priority, flag D for Disney+
    "Netflix": "🅽",          # USA priority, boxed N
    "Amazon Prime Video": "ⓐ", # USA priority, circled a
    "Hulu": "ⓗ",             # USA priority, circled h
    "Tubi": "📺",             # USA priority, TV icon
    "Fubo": "🎥",             # USA priority, movie camera
    "Max": "🌟",              # USA priority, star for HBO Max
    "RetroCrush": "🎞️",      # USA priority, film strip
    "Ani-One Asia": None,
    "Bahamut Anime Crazy": None,
    "Bilibili Global": None,
    "Anime Digital Network": None,  # Example unlisted provider
    "Anime Generation": None,
    "CatchPlay": None,
    "Laftel": None,
    "MeWatch": None,
    "Muse Asia": None
}

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
            # Extract MAL link if present
            mal_link_match = re.search(r'<a href="https?://myanimelist\.net/anime/(\d+)/[^"]+"[^>]*>([^<]+)</a>', line)
            mal_link = mal_link_match.group(0) if mal_link_match else None
            schedule[current_day].append({
                "name": name.strip(),
                "current": current_ep,
                "total": total_ep,
                "suspended": suspended == "**",
                "mal_link": mal_link
            })

# Parse upcoming sections and extract MAL links
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
        # Extract MAL link if present
        mal_link_match = re.search(r'<a href="https?://myanimelist\.net/anime/(\d+)/[^"]+"[^>]*>([^<]+)</a>', line)
        title = mal_link_match.group(2) if mal_link_match else line.split(" - ")[0].strip() if " - " in line else line.rstrip("*").strip()
        mal_link = mal_link_match.group(0) if mal_link_match else None
        date_str = match.group(1) if match else None
        upcoming.append({
            "title": title,
            "date": date_str,
            "theatrical": is_theatrical,
            "section": current_section,
            "mal_link": mal_link
        })

# Scrape MAL for streaming platforms and additional data
def get_mal_info(mal_link=None, title=None):
    if mal_link:
        mal_url = re.search(r'href="([^"]+)"', mal_link).group(1)
        print(f"Using MAL link: {mal_url}")
    elif title:
        search_url = f"https://myanimelist.net/anime.php?q={requests.utils.quote(title)}&cat=anime"
        search_response = requests.get(search_url, headers=headers)
        search_soup = BeautifulSoup(search_response.content, "html.parser")
        anime_link = search_soup.select_one(".hoverinfo_trigger")
        if anime_link:
            mal_id = anime_link["id"].replace("sarea", "")
            mal_url = f"https://myanimelist.net/anime/{mal_id}/{requests.utils.quote(title.replace(' ', '_'))}"
        else:
            print(f"No MAL entry found for {title}")
            return {"streaming": [], "broadcast": "", "producers": [], "studios": [], "source": "", "genres": [], "demographic": "", "duration": "", "rating": ""}
    else:
        return {"streaming": [], "broadcast": "", "producers": [], "studios": [], "source": "", "genres": [], "demographic": "", "duration": "", "rating": ""}

    mal_response = requests.get(mal_url, headers=headers)
    mal_soup = BeautifulSoup(mal_response.content, "html.parser")
    
    # Streaming platforms (preserve MAL order)
    streaming_div = mal_soup.select_one(".broadcasts")
    streaming_list = []
    if streaming_div:
        for item in streaming_div.select(".broadcast-item .caption"):
            streaming_list.append(item.text.strip())
    print(f"Streaming providers: {streaming_list}")

    # Additional MAL data
    broadcast = mal_soup.select_one(".spaceit_pad:contains('Broadcast:')")
    broadcast = broadcast.text.strip().replace("Broadcast:", "").strip() if broadcast else ""
    
    producers = [a.text for a in mal_soup.select(".spaceit_pad:contains('Producers:') a")] if mal_soup.select_one(".spaceit_pad:contains('Producers:')") else []
    studios = [a.text for a in mal_soup.select(".spaceit_pad:contains('Studios:') a")] if mal_soup.select_one(".spaceit_pad:contains('Studios:')") else []
    source = mal_soup.select_one(".spaceit_pad:contains('Source:') a")
    source = source.text.strip() if source else mal_soup.select_one(".spaceit_pad:contains('Source:')").text.strip().replace("Source:", "").strip() if mal_soup.select_one(".spaceit_pad:contains('Source:')") else ""
    genres = [a.text for a in mal_soup.select(".spaceit_pad:contains('Genres:') a")] if mal_soup.select_one(".spaceit_pad:contains('Genres:')") else []
    demographic = mal_soup.select_one(".spaceit_pad:contains('Demographic:') a")
    demographic = demographic.text if demographic else mal_soup.select_one(".spaceit_pad:contains('Demographic:')").text.strip().replace("Demographic:", "").strip() if mal_soup.select_one(".spaceit_pad:contains('Demographic:')") else ""
    duration = mal_soup.select_one(".spaceit_pad:contains('Duration:')")
    duration = duration.text.strip().replace("Duration:", "").strip() if duration else ""
    rating = mal_soup.select_one(".spaceit_pad:contains('Rating:')")
    rating = rating.text.strip().replace("Rating:", "").strip() if rating else ""

    return {
        "streaming": streaming_list,
        "broadcast": broadcast,
        "producers": producers,
        "studios": studios,
        "source": source,
        "genres": genres,
        "demographic": demographic,
        "duration": duration,
        "rating": rating
    }

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
    if days_ahead < 0:  # If the target day is earlier in the week, add 7 days
        days_ahead += 7
    return start_date + timedelta(days=days_ahead)

for day, shows in schedule.items():
    day_index = day_map[day]
    used_colors = set()
    
    for show in shows:
        latest_episode = show["current"]
        total_ep = show["total"] or 10  # Fallback if parsing fails
        base_date = next_weekday(current_date, day_index)
        mal_info = get_mal_info(show["mal_link"], show["name"])
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
                event = {
                    "summary": f"{emoji}{show['name']} (Suspended) [Latest Episode {latest_episode}/{total_ep or '?'}]",
                    "description": f"{description_part}\n** = Dub production suspended until further notice.\nRating: {mal_info['rating']}\nStreaming: {', '.join(streaming) if streaming else 'None'}\nBroadcast: {mal_info['broadcast']}\nGenres: {', '.join(mal_info['genres']) if mal_info['genres'] else 'None'}\nStudios: {', '.join(mal_info['studios']) if mal_info['studios'] else 'None'}\nProducers: {', '.join(mal_info['producers']) if mal_info['producers'] else 'None'}\nSource: {mal_info['source']}\nDemographic: {mal_info['demographic']}\nDuration: {mal_info['duration']}",
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
                        "summary": f"{emoji}{show['name']} S{(latest_episode // 100) + 1:02d}E{ep:02d} (Expected)",
                        "description": f"{description_part}\nRating: {mal_info['rating']}\nStreaming: {', '.join(streaming) if streaming else 'None'}\nBroadcast: {mal_info['broadcast']}\nGenres: {', '.join(mal_info['genres']) if mal_info['genres'] else 'None'}\nStudios: {', '.join(mal_info['studios']) if mal_info['studios'] else 'None'}\nProducers: {', '.join(mal_info['producers']) if mal_info['producers'] else 'None'}\nSource: {mal_info['source']}\nDemographic: {mal_info['demographic']}\nDuration: {mal_info['duration']}",
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
            mal_info = get_mal_info(item["mal_link"], item["title"])
            streaming = mal_info["streaming"]
            manual = MANUAL_STREAMING.get(item["title"])
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
            print(f"Upcoming: {item['title']}, Main Provider: {main_provider}, Emoji: {emoji}")
            summary = f"🎟️{item['title']}" if item["theatrical"] else f"{emoji}{item['title']}"
            event = {
                "summary": summary,
                "description": f"{description_part}\n🎟️ * = These are theatrical releases and not home/digital releases.\nRating: {mal_info['rating']}\nStreaming: {', '.join(streaming) if streaming else 'None'}\nBroadcast: {mal_info['broadcast']}\nGenres: {', '.join(mal_info['genres']) if mal_info['genres'] else 'None'}\nStudios: {', '.join(mal_info['studios']) if mal_info['studios'] else 'None'}\nProducers: {', '.join(mal_info['producers']) if mal_info['producers'] else 'None'}\nSource: {mal_info['source']}\nDemographic: {mal_info['demographic']}\nDuration: {mal_info['duration']}" if item["theatrical"] else f"{description_part}\nRating: {mal_info['rating']}\nStreaming: {', '.join(streaming) if streaming else 'None'}\nBroadcast: {mal_info['broadcast']}\nGenres: {', '.join(mal_info['genres']) if mal_info['genres'] else 'None'}\nStudios: {', '.join(mal_info['studios']) if mal_info['studios'] else 'None'}\nProducers: {', '.join(mal_info['producers']) if mal_info['producers'] else 'None'}\nSource: {mal_info['source']}\nDemographic: {mal_info['demographic']}\nDuration: {mal_info['duration']}",
                "start": {"date": event_date.strftime("%Y-%m-%d")},
                "end": {"date": event_date.strftime("%Y-%m-%d")},
                "colorId": upcoming_color
            }
            print(f"Inserting event: {json.dumps(event, indent=2)}")
            service.events().insert(calendarId=calendar_id, body=event).execute()

print("Calendar updated successfully!")