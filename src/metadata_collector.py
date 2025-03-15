import requests
from bs4 import BeautifulSoup, NavigableString
import re
import json
import os
import logging
from datetime import datetime
import hashlib

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

FORUM_URL = "https://myanimelist.net/forum/?topicid=1692966"
DATA_DIR = "/data"
OUTPUT_FILE = os.path.join(DATA_DIR, "metadata.json")
MANUAL_FILE = os.path.join(DATA_DIR, "manual_overrides.json")

def get_season_quarter(date_str):
    """Convert aired date to season quarter (e.g., 'Oct 4, 2024' -> '2024-Q4')."""
    try:
        start_date = datetime.strptime(date_str.split(" to ")[0], "%b %d, %Y")
        month = start_date.month
        year = start_date.year
        if month in [1, 2, 3]:
            return f"{year}-Q1"  # Winter
        elif month in [4, 5, 6]:
            return f"{year}-Q2"  # Spring
        elif month in [7, 8, 9]:
            return f"{year}-Q3"  # Summer
        elif month in [10, 11, 12]:
            return f"{year}-Q4"  # Fall
    except Exception as e:
        logger.error(f"Failed to parse season quarter from {date_str}: {e}")
        return ""

def compute_hash(identifier):
    """Generate a hash for color assignment."""
    return hashlib.md5(identifier.encode()).hexdigest()

def scrape_forum_post():
    """Scrape the MAL forum post for simulcast anime."""
    try:
        response = requests.get(FORUM_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        post = soup.find("div", {"id": "msg53221626"})
        if not post:
            logger.error("Forum post not found")
            return {}

        metadata = {}
        content = post.find("td").text
        current_day = None
        for line in content.split("\n"):
            line = line.strip()
            if line in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
                current_day = line
            elif line.startswith("<li>") and current_day:
                match = re.search(r'<a href="(https://myanimelist.net/anime/\d+/[^"]+)" rel="nofollow">([^<]+)</a> \(Episodes: (\d+)(?:/(\d+|\?+|\w+))?\)', line)
                if match:
                    url, title, ep_current, ep_total = match.groups()
                    mal_id = url.split("/")[4]
                    metadata[mal_id] = {
                        "ShowName": title,
                        "ShowLink": url,
                        "LatestEpisode": int(ep_current),
                        "TotalEpisodes": int(ep_total) if ep_total and ep_total.isdigit() else None,
                        "AirDay": current_day,
                        "MAL_ID": mal_id
                    }
        logger.info(f"Scraped {len(metadata)} shows from forum")
        return metadata
    except Exception as e:
        logger.error(f"Forum scraping failed: {e}")
        return {}

def scrape_show_page(url, mal_id, forum_data):
    """Scrape additional metadata from a show's MAL page."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        info = soup.find("div", {"class": "leftside"})
        if not info:
            logger.error(f"No leftside div found for {url}")
            return forum_data

        data = forum_data.copy()
        now = datetime.utcnow().isoformat()
        data["LastChecked"] = now  # Set early to ensure it’s always present

        for span in info.find_all("span", {"class": "dark_text"}):
            key = span.text.strip(":")
            next_elem = span.next_sibling
            value = next_elem.strip() if isinstance(next_elem, NavigableString) else ""
            logger.debug(f"Parsing {key}: next_elem={next_elem}, value={value}")
            if key == "Studios":
                data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
            elif key == "Genres":
                data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
            elif key == "Aired":
                data[key] = value
                data["Premiered"] = get_season_quarter(value)
            elif key == "Broadcast":
                data[key] = value.split(" (")[0]  # Remove timezone
            elif key == "Source":
                if isinstance(next_elem, NavigableString):
                    data[key] = value
                elif next_elem and next_elem.find("a"):
                    data[key] = next_elem.find("a").text.strip()
                else:
                    data[key] = ""
            elif key == "Theme":  # Singular "Theme"
                data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
            elif key == "Duration":
                data[key] = value
            elif key == "Rating":
                data[key] = value
            elif key == "Demographic":
                data[key] = "|".join(a.text for a in span.find_next_siblings("a"))

        # Streaming platforms
        broadcasts = soup.find_all("a", {"class": "broadcast-item"})
        if broadcasts:
            data["Streaming"] = "|".join(b.find("div", {"class": "caption"}).text for b in broadcasts if b.find("div", {"class": "caption"}))

        # LastModified from MAL's "Last Updated"
        last_updated = soup.find("div", {"class": "updatesBar"})
        if last_updated and "Last Updated" in last_updated.text:
            data["LastModified"] = last_updated.text.split("Last Updated ")[1].strip()
        else:
            data["LastModified"] = data.get("LastModified", now)

        # Ensure Demographic is always present
        data.setdefault("Demographic", "")

        data["Hash"] = compute_hash(mal_id)
        return data
    except Exception as e:
        logger.error(f"Show page scraping failed for {url}: {e}")
        data = forum_data.copy()
        data["LastChecked"] = datetime.utcnow().isoformat()  # Ensure LastChecked on failure
        return data

def load_existing_metadata():
    """Load existing metadata to preserve DateAdded."""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            return json.load(f) or {}
    return {}

def load_manual_overrides():
    """Load manual overrides from file."""
    if os.path.exists(MANUAL_FILE):
        with open(MANUAL_FILE, "r") as f:
            return json.load(f) or {}
    return {}

def save_metadata(metadata):
    """Save metadata to JSON file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved metadata to {OUTPUT_FILE}")

def collect_metadata():
    """Collect and merge metadata from forum and show pages."""
    forum_data = scrape_forum_post()
    if not forum_data:
        return {}

    existing_metadata = load_existing_metadata()
    manual_overrides = load_manual_overrides()
    metadata = {}
    for mal_id, base_data in forum_data.items():
        show_data = scrape_show_page(base_data["ShowLink"], mal_id, base_data)
        # Preserve DateAdded from existing data
        show_data["DateAdded"] = existing_metadata.get(mal_id, {}).get("DateAdded", show_data["LastChecked"])
        # Update LastModified only if data differs
        old_data = existing_metadata.get(mal_id, {})
        if old_data and old_data != show_data:
            show_data["LastModified"] = show_data["LastChecked"]
        elif "LastModified" not in show_data:
            show_data["LastModified"] = show_data["LastChecked"]
        if mal_id in manual_overrides:
            show_data.update(manual_overrides[mal_id])
        metadata[mal_id] = show_data

    save_metadata(metadata)
    return metadata

if __name__ == "__main__":
    if os.getenv("TEST_MODE", "false").lower() == "true":
        # Test with known data
        test_forum_data = {
            "57891": {
                "ShowName": "Loner Life in Another World",
                "ShowLink": "https://myanimelist.net/anime/57891/Hitoribocchi_no_Isekai_Kouryaku",
                "LatestEpisode": 4,
                "TotalEpisodes": 12,
                "AirDay": "Wednesday",
                "MAL_ID": "57891"
            }
        }
        test_manual = {
            "57891": {
                "Emoji": "🐭",
                "DubStream": "DisneyNow",
                "EventColor": "Tangerine"
            }
        }
        with open(MANUAL_FILE, "w") as f:
            json.dump(test_manual, f)
        existing_metadata = load_existing_metadata()
        metadata = {}
        for mal_id, base_data in test_forum_data.items():
            show_data = scrape_show_page(base_data["ShowLink"], mal_id, base_data)
            show_data["DateAdded"] = existing_metadata.get(mal_id, {}).get("DateAdded", show_data["LastChecked"])
            old_data = existing_metadata.get(mal_id, {})
            if old_data and old_data != show_data:
                show_data["LastModified"] = show_data["LastChecked"]
            elif "LastModified" not in show_data:
                show_data["LastModified"] = show_data["LastChecked"]
            if mal_id in test_manual:
                show_data.update(test_manual[mal_id])
            metadata[mal_id] = show_data
        save_metadata(metadata)
    else:
        collect_metadata()