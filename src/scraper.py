import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import yaml

FORUM_URL = "https://myanimelist.net/forum/?topicid=1692966"

def scrape_forum_post():
    response = requests.get(FORUM_URL)
    soup = BeautifulSoup(response.text, 'html.parser')
    post = soup.find("div", {"id": "msg53221626"})
    if not post:
        return None

    # Extract last modified time
    mod_time_elem = post.find("span", {"class": "modtime"})
    mod_time = mod_time_elem.text if mod_time_elem else "Unknown"

    # Extract last updated date with fallback
    last_updated_elem = post.find("b", text=re.compile("Last Updated:"))
    last_updated = last_updated_elem.next_sibling.strip() if last_updated_elem and last_updated_elem.next_sibling else "Unknown"

    # Parse anime lists
    content = post.find("td").text
    sections = {
        "Currently Streaming SimulDubbed Anime": {},
        "Upcoming SimulDubbed Anime for Winter 2025": [],
        "Upcoming SimulDubbed Anime for Spring 2025": [],
        "Upcoming Dubbed Anime": [],
        "Released Dubbed Anime Awaiting Streaming": [],
        "Announced Dubbed Anime": [],
        "Released Dubbed Anime": [],
        "Finished SimulDubbed Anime": []
    }

    current_day = None
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("Monday") or line.startswith("Tuesday") or line.startswith("Wednesday") or \
           line.startswith("Thursday") or line.startswith("Friday") or line.startswith("Saturday") or \
           line.startswith("Sunday"):
            current_day = line.split()[0]
            sections["Currently Streaming SimulDubbed Anime"][current_day] = []
        elif line.startswith("<li>") and current_day:
            match = re.search(r'<a href="(https://myanimelist.net/anime/\d+/[^"]+)" rel="nofollow">([^<]+)</a> \(Episodes: (\d+)(?:/(\d+|\?+|\w+))?\)', line)
            if match:
                url, title, ep_current, ep_total = match.groups()
                sections["Currently Streaming SimulDubbed Anime"][current_day].append({
                    "title": title,
                    "url": url,
                    "mal_id": url.split("/")[4],
                    "current_episode": int(ep_current),
                    "total_episodes": ep_total if ep_total and ep_total.isdigit() else None,
                    "suspended": "**" in line
                })
        elif any(section in line for section in sections) and "Currently Streaming" not in line:
            current_section = next(s for s in sections if s in line)
        elif line.startswith("<li>") and current_section != "Currently Streaming SimulDubbed Anime":
            match = re.search(r'([^<]+) - (\w+ \d+, \d+)(?:\*)?', line)
            if match:
                title, date = match.groups()
                sections[current_section].append({"title": title.strip(), "date": date})

    return {
        "mod_time": mod_time,
        "last_updated": last_updated,
        "sections": sections
    }

def load_cached_data():
    try:
        with open("/data/parsed_data.yaml", "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

def save_cached_data(data):
    with open("/data/parsed_data.yaml", "w") as f:
        yaml.safe_dump(data, f)

def needs_update(cached, new):
    return cached.get("mod_time") != new["mod_time"] or cached.get("last_updated") != new["last_updated"]