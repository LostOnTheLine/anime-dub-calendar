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
MAL_SEARCH_URL = "https://myanimelist.net/anime.php?q={}&cat=anime"
DATA_DIR = "/data"
OUTPUT_FILE = os.path.join(DATA_DIR, "metadata.json")
MANUAL_FILE = os.path.join(DATA_DIR, "manual_overrides.yaml")

def get_cour_from_premiered(premiered_text):
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
        return ""
    except Exception as e:
        logger.error(f"Failed to parse cour from {premiered_text}: {e}")
        return ""

def get_cour_from_date(date_str):
    try:
        date_str = date_str.rstrip("*").strip()
        dt = datetime.strptime(date_str, "%B %d, %Y")
        month = dt.month
        year = dt.year
        if month in [1, 2, 3]:
            return f"{year}-Q1"
        elif month in [4, 5, 6]:
            return f"{year}-Q2"
        elif month in [7, 8, 9]:
            return f"{year}-Q3"
        elif month in [10, 11, 12]:
            return f"{year}-Q4"
    except Exception as e:
        logger.debug(f"Could not parse date: {date_str} - {e}")
        return ""

def compute_hash(identifier):
    return hashlib.md5(identifier.encode()).hexdigest()

def search_mal_for_show(show_name):
    try:
        # Special handling for episode batches like "One Piece (Episodes: 1109-1122)"
        if "(Episodes:" in show_name:
            base_name = show_name.split(" (Episodes:")[0].strip()
            search_term = base_name.replace(" ", "%20")
        else:
            search_term = show_name.replace(" ", "%20")
        
        response = requests.get(MAL_SEARCH_URL.format(search_term))
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html5lib')
        first_result = soup.find("a", {"class": "hoverinfo_trigger"})
        if first_result and "myanimelist.net/anime/" in first_result["href"]:
            mal_id = first_result["href"].split("/")[4]
            return mal_id, first_result["href"]
        logger.debug(f"No MAL match found for {show_name}")
        return None, None
    except Exception as e:
        logger.error(f"MAL search failed for {show_name}: {e}")
        return None, None

def scrape_forum_post():
    try:
        response = requests.get(FORUM_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html5lib')
        post = soup.find("div", {"id": "msg53221626"})
        if not post:
            logger.error("Forum post not found")
            return {}, None, None, {"UpcomingShows": {"UpcomingSimulDubbed": {}, "UpcomingDubbed": {}}}

        modified_div = post.find("div", {"class": "modified"})
        upcoming_dub_modified = modified_div.find("span", {"class": "modtime"}).text.strip() if modified_div else None
        upcoming_dub_modified_by = modified_div.find("span", {"class": "moduser"}).text.strip() if modified_div else None

        metadata = {}
        upcoming_shows = {"UpcomingShows": {"UpcomingSimulDubbed": {}, "UpcomingDubbed": {}}}
        td = post.find("td")
        if not td:
            logger.error("No <td> found in forum post")
            return {}, upcoming_dub_modified, upcoming_dub_modified_by, upcoming_shows

        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        outer_ul = td.find("ul")
        if not outer_ul:
            logger.error("No outer <ul> found in forum post")
            return {}, upcoming_dub_modified, upcoming_dub_modified_by, upcoming_shows

        # Parse currently streaming shows
        for li in outer_ul.find_all("li", recursive=False):
            li_text = li.text.strip()
            current_day = next((day for day in days if day in li_text), None)
            if current_day:
                nested_ul = li.find("ul")
                if nested_ul:
                    for show_li in nested_ul.find_all("li", recursive=False):
                        a_tag = show_li.find("a", href=True)
                        if a_tag and "myanimelist.net/anime/" in a_tag["href"]:
                            title = a_tag.text.strip()
                            url = a_tag["href"]
                            mal_id = url.split("/")[4]
                            episode_text = show_li.text.replace(title, "").strip()
                            match = re.search(r'\(Episodes: (\d+)(?:/(\d+|\?+|\w+))?\)(?:\s*\*\*)?', episode_text)
                            if match:
                                ep_current, ep_total = match.groups()
                                notes = "Dub production suspended until further notice" if "**" in episode_text else ""
                                metadata[mal_id] = {
                                    "ShowName": title,
                                    "ShowLink": url,
                                    "LatestEpisode": int(ep_current),
                                    "TotalEpisodes": int(ep_total) if ep_total and ep_total.isdigit() else None,
                                    "AirDay": current_day,
                                    "MAL_ID": mal_id,
                                    "Notes": notes
                                }

        # Parse upcoming shows
        upcoming_sections = td.find_all("b", string=re.compile(r"Upcoming SimulDubbed Anime|Upcoming Dubbed Anime"))
        for section in upcoming_sections:
            section_title = section.text.strip()
            ul = section.find_next("ul")
            if not ul:
                continue

            is_simuldub = "SimulDubbed" in section_title
            section_key = "UpcomingSimulDubbed" if is_simuldub else "UpcomingDubbed"
            for li in ul.find_all("li", recursive=False):
                text = li.text.strip()
                if text == "None" or "* -" in text:
                    continue
                date_match = re.search(r" - (.*?)$", text)
                release_date = date_match.group(1) if date_match else ""
                show_name = text.replace(f" - {release_date}", "").strip()
                notes = "Not confirmed" if "*" in text and "theatrical" not in text.lower() else ""
                release_type = "Theatrical" if "theatrical releases" in text.lower() else ("SimulDub" if is_simuldub else "Dubbed")
                if "theatrical releases" in text.lower():
                    notes = "These are theatrical releases and not home/digital releases"

                show_data = {
                    "ShowName": show_name,
                    "ReleaseDate": release_date,
                    "Notes": notes,
                    "ReleaseType": release_type,
                    "Hash": compute_hash(show_name)
                }
                mal_id_match, detected_match = search_mal_for_show(show_name)
                if mal_id_match:
                    show_data["MAL_ID_Match"] = mal_id_match
                    show_data["Detected_Match"] = detected_match

                if release_date:
                    cour = get_cour_from_date(release_date)
                    if cour:
                        if cour not in upcoming_shows["UpcomingShows"][section_key]:
                            upcoming_shows["UpcomingShows"][section_key][cour] = []
                        upcoming_shows["UpcomingShows"][section_key][cour].append(show_data)
                    else:
                        upcoming_shows["UpcomingShows"][section_key].setdefault("NoDate", []).append(show_data)
                else:
                    upcoming_shows["UpcomingShows"][section_key].setdefault("NoDate", []).append(show_data)

        return metadata, upcoming_dub_modified, upcoming_dub_modified_by, upcoming_shows
    except Exception as e:
        logger.error(f"Forum scraping failed: {e}")
        return {}, None, None, {"UpcomingShows": {"UpcomingSimulDubbed": {}, "UpcomingDubbed": {}}}

def scrape_show_page(url, mal_id, base_data):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        info = soup.find("div", {"class": "leftside"})
        if not info:
            logger.error(f"No leftside div found for {url}")
            return base_data

        data = base_data.copy()
        data["LastChecked"] = datetime.utcnow().isoformat()
        title = soup.find("h1", {"class": "title-name"})
        if title:
            data["ShowTitle"] = title.text.strip()

        for span in info.find_all("span", {"class": "dark_text"}):
            key = span.text.strip(":")
            next_elem = span.next_sibling
            value = next_elem.strip() if isinstance(next_elem, NavigableString) else ""
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
                data[key] = value if value else ""
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
        data["Hash"] = compute_hash(data["ShowName"])  # Use ShowName for consistency
        return data
    except Exception as e:
        logger.error(f"Show page scraping failed for {url}: {e}")
        data = base_data.copy()
        data["LastChecked"] = datetime.utcnow().isoformat()
        return data

def load_existing_metadata():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            return json.load(f) or {}
    return {}

def load_manual_overrides():
    if os.path.exists(MANUAL_FILE):
        with open(MANUAL_FILE, "r") as f:
            data = yaml.safe_load(f) or {}
            return {str(k): v for k, v in data.items()}
    return {}

def save_metadata(metadata):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved metadata to {OUTPUT_FILE}")

def compare_data(old_data, new_data):
    mal_fields = ["ShowLink", "Aired", "Broadcast", "Studios", "Source", "Genres", 
                  "Theme", "Duration", "Rating", "Streaming", "Demographic"]
    old_copy = {k: old_data.get(k, "") for k in mal_fields}
    new_copy = {k: new_data.get(k, "") for k in mal_fields}
    return old_copy == new_copy

def get_dub_season(existing_data, new_data, current_time):
    if "DubSeason" in existing_data:
        return existing_data["DubSeason"]
    if "LatestEpisode" in new_data and new_data["LatestEpisode"] == 1:
        return get_cour_from_date(current_time.split("T")[0])
    if "ReleaseDate" in new_data and new_data["ReleaseDate"]:
        return get_cour_from_date(new_data["ReleaseDate"])
    return ""

def collect_metadata():
    forum_data, upcoming_dub_modified, upcoming_dub_modified_by, upcoming_shows = scrape_forum_post()
    now = datetime.utcnow().isoformat()

    existing_metadata = load_existing_metadata()
    manual_overrides = load_manual_overrides()
    metadata = {
        "UpcomingDubbedAnime": {
            "UpcomingDubChecked": now,
            "UpcomingDubModified": upcoming_dub_modified or "Unknown",
            "UpcomingDubModifiedBy": upcoming_dub_modified_by or "Unknown",
            "CurrentlyStreaming": {
                "SimulDubbed": {
                    "Total": len(forum_data)
                }
            },
            "UpcomingShows": upcoming_shows["UpcomingShows"]
        }
    }

    # Process currently streaming shows
    for mal_id, base_data in forum_data.items():
        show_data = scrape_show_page(base_data["ShowLink"], mal_id, base_data)
        old_data = existing_metadata.get(mal_id, {})
        show_data["DateAdded"] = old_data.get("DateAdded", show_data["LastChecked"])
        show_data["DubSeason"] = get_dub_season(old_data, base_data, now)
        if show_data.get("LastModified") is None:
            if not old_data:
                show_data["LastModified"] = f"Before {show_data['DateAdded']}"
            elif compare_data(old_data, show_data):
                show_data["LastModified"] = old_data["LastModified"]
            else:
                show_data["LastModified"] = f"Between {old_data['LastChecked']} and {show_data['LastChecked']}"
        if mal_id in manual_overrides:
            override = manual_overrides[mal_id]
            if "streaming" in override:
                show_data["DubStreaming"] = override["streaming"]
            show_data.update({k: v for k, v in override.items() if k != "streaming"})
        metadata[mal_id] = show_data

    # Process upcoming shows
    all_upcoming_mal_ids = set()
    for section in ["UpcomingSimulDubbed", "UpcomingDubbed"]:
        for cour, shows in upcoming_shows["UpcomingShows"][section].items():
            show_list = shows
            for base_data in show_list:
                show_name = base_data["ShowName"]
                override = next((val for key, val in manual_overrides.items() if key == show_name or ("ShowName" in val and val["ShowName"] == show_name)), None)

                if override and "MAL_ID" in override:
                    mal_id = override["MAL_ID"]
                    show_link = f"https://myanimelist.net/anime/{mal_id}"
                    base_data["MAL_ID"] = mal_id  # Sync override in UpcomingShows
                elif "MAL_ID_Match" in base_data:
                    mal_id = base_data["MAL_ID_Match"]
                    show_link = base_data["Detected_Match"]
                    base_data["MAL_ID"] = mal_id
                else:
                    logger.warning(f"No valid MAL_ID for {show_name}, skipping")
                    continue

                all_upcoming_mal_ids.add(mal_id)
                base_data["ShowLink"] = show_link
                base_data["LatestEpisode"] = 0
                base_data["TotalEpisodes"] = None
                base_data["AirDay"] = "Upcoming"

                if override:
                    if "streaming" in override:
                        base_data["DubStreaming"] = override["streaming"]
                    base_data.update({k: v for k, v in override.items() if k not in ["MAL_ID", "streaming"]})

                show_data = scrape_show_page(show_link, mal_id, base_data)
                old_data = existing_metadata.get(mal_id, {})
                show_data["DateAdded"] = old_data.get("DateAdded", show_data["LastChecked"])
                show_data["DubSeason"] = get_dub_season(old_data, base_data, now)
                if show_data.get("LastModified") is None:
                    if not old_data:
                        show_data["LastModified"] = f"Before {show_data['DateAdded']}"
                    elif compare_data(old_data, show_data):
                        show_data["LastModified"] = old_data["LastModified"]
                    else:
                        show_data["LastModified"] = f"Between {old_data['LastChecked']} and {show_data['LastChecked']}"
                metadata[mal_id] = show_data

    # Handle existing streaming shows not in forum
    not_on_list_fields = ["ShowName", "ShowLink", "LatestEpisode", "TotalEpisodes", "AirDay"]
    for mal_id, old_data in existing_metadata.items():
        if mal_id != "UpcomingDubbedAnime" and mal_id not in forum_data and mal_id not in all_upcoming_mal_ids:
            if "AirDay" in old_data and old_data["AirDay"] != "Upcoming":  # Only streaming shows
                show_data = old_data.copy()
                for field in not_on_list_fields:
                    show_data[field] = "NOT ON UPCOMING DUB LIST"
                show_data["LastChecked"] = now
                metadata[mal_id] = show_data

    save_metadata(metadata)
    return metadata

if __name__ == "__main__":
    collect_metadata()