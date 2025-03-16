import requests
from bs4 import BeautifulSoup, NavigableString
import re
import json
import os
import logging
from datetime import datetime
import hashlib
import yaml

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

FORUM_URL = "https://myanimelist.net/forum/?topicid=1692966"
DATA_DIR = "/data"
OUTPUT_FILE = os.path.join(DATA_DIR, "metadata.json")
MANUAL_FILE = os.path.join(DATA_DIR, "manual_overrides.yaml")

def get_cour_from_premiered(premiered_text):
    """Convert premiered text (e.g., 'Fall 2024') to cour format (e.g., '2024-Q4')."""
    try:
        season, year = premiered_text.split()
        year = int(year)
        if season.lower() == "winter":
            return f"{year}-Q1"
        elif season.lower() == "spring":
            return f"{year}-Q2"
        elif season.lower() == "summer":
            return f"{year}-Q3"
        elif season.lower() == "fall":
            return f"{year}-Q4"
        else:
            logger.error(f"Unknown season in premiered text: {season}")
            return ""
    except Exception as e:
        logger.error(f"Failed to parse cour from {premiered_text}: {e}")
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
        data["LastChecked"] = now

        for span in info.find_all("span", {"class": "dark_text"}):
            key = span.text.strip(":")
            next_elem = span.next_sibling
            value = next_elem.strip() if isinstance(next_elem, NavigableString) else ""
            logger.debug(f"Parsing {key}: next_elem={next_elem}, value={value}")
            if key == "Studios":
                data[key] = "|".join(sorted(a.text for a in span.find_next_siblings("a")))
            elif key == "Genres":
                data[key] = "|".join(sorted(a.text for a in span.find_next_siblings("a")))
            elif key == "Aired":
                data[key] = value
            elif key == "Premiered":
                next_a = span.find_next("a")
                premiered_text = next_a.text.strip() if next_a else ""
                data["Premiered"] = premiered_text
                data["Cour"] = get_cour_from_premiered(premiered_text) if premiered_text else ""
            elif key == "Broadcast":
                data[key] = value.split(" (")[0]
            elif key == "Source":
                next_a = span.find_next("a")
                if next_a:
                    data[key] = next_a.text.strip()
                elif isinstance(next_elem, NavigableString) and value:
                    data[key] = value
                else:
                    data[key] = ""
            elif key == "Theme":
                data[key] = "|".join(sorted(a.text for a in span.find_next_siblings("a")))
            elif key == "Duration":
                data[key] = value
            elif key == "Rating":
                data[key] = value
            elif key == "Demographic":
                data[key] = "|".join(sorted(a.text for a in span.find_next_siblings("a")))

        broadcasts = soup.find_all("a", {"class": "broadcast-item"})
        if broadcasts:
            data["Streaming"] = "|".join(sorted(
                b.find("div", {"class": "caption"}).text if b.find("div", {"class": "caption"}) else ""
                for b in broadcasts
            ))

        last_updated = soup.find("div", {"class": "updatesBar"})
        if last_updated and "Last Updated" in last_updated.text:
            data["LastModified"] = last_updated.text.split("Last Updated ")[1].strip()
        else:
            data["LastModified"] = None

        data.setdefault("Demographic", "")
        data["Hash"] = compute_hash(mal_id)
        return data
    except Exception as e:
        logger.error(f"Show page scraping failed for {url}: {e}")
        data = forum_data.copy()
        data["LastChecked"] = datetime.utcnow().isoformat()
        return data

def load_existing_metadata():
    """Load existing metadata to preserve DateAdded and LastChecked."""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            return json.load(f) or {}
    return {}

def load_manual_overrides():
    """Load manual overrides from YAML file."""
    if os.path.exists(MANUAL_FILE):
        with open(MANUAL_FILE, "r") as f:
            data = yaml.safe_load(f) or {}
            return {str(k): v for k, v in data.items()}
    return {}

def save_metadata(metadata):
    """Save metadata to JSON file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved metadata to {OUTPUT_FILE}")

def compare_data(old_data, new_data):
    """Compare only fields pulled from MAL page."""
    mal_fields = ["ShowLink", "Aired", "Broadcast", "Studios", "Source", "Genres", 
                  "Theme", "Duration", "Rating", "Streaming", "Demographic"]
    old_copy = {k: old_data.get(k, "") for k in mal_fields}
    new_copy = {k: new_data.get(k, "") for k in mal_fields}
    are_equal = old_copy == new_copy
    logger.debug(f"Comparing old_data and new_data: equal={are_equal}, old={old_copy}, new={new_copy}")
    return are_equal

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
        show_data["DateAdded"] = existing_metadata.get(mal_id, {}).get("DateAdded", show_data["LastChecked"])
        old_data = existing_metadata.get(mal_id, {})
        if show_data.get("LastModified") is None:
            if not old_data:
                show_data["LastModified"] = f"Before {show_data['DateAdded']}"
            elif compare_data(old_data, show_data):
                show_data["LastModified"] = old_data["LastModified"]
            else:
                show_data["LastModified"] = f"Between {old_data['LastChecked']} and {show_data['LastChecked']}"
        if mal_id in manual_overrides:
            show_data.update(manual_overrides[mal_id])
        metadata[mal_id] = show_data

    save_metadata(metadata)
    return metadata

if __name__ == "__main__":
    collect_metadata()