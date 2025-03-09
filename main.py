import asyncio
import sqlite3
import re
from bs4 import BeautifulSoup
import requests
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def init_db():
    """Initialize the SQLite database and create the shows table if it doesn't exist."""
    conn = sqlite3.connect('shows.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS shows
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT NOT NULL,
                  mal_link TEXT,
                  episodes_total INTEGER,
                  episodes_watched INTEGER,
                  day_of_week TEXT,
                  status TEXT,
                  last_updated TEXT)''')
    conn.commit()
    conn.close()
    logger.info("Database initialized or already exists.")

async def fetch_forum_page():
    """Fetch the forum page content."""
    url = "https://myanimelist.net/forum/?topicid=1692966"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch forum page: {e}")
        return None

def parse_ongoing_schedule(html_content):
    """Parse the ongoing SimulDubbed anime schedule from the HTML content."""
    if not html_content:
        logger.error("No HTML content provided to parse_ongoing_schedule.")
        return []

    soup = BeautifulSoup(html_content, 'html.parser')
    ongoing_shows = []

    # Find the section for "Currently Streaming SimulDubbed Anime"
    streaming_section = soup.find(string=re.compile(r"Currently Streaming SimulDubbed Anime", re.IGNORECASE))
    if not streaming_section:
        logger.warning("Could not find 'Currently Streaming SimulDubbed Anime' section.")
        return []

    # Navigate to the parent <td> and find all <ul> elements within it
    td_parent = streaming_section.find_parent('td')
    if not td_parent:
        logger.warning("Could not find parent <td> for 'Currently Streaming SimulDubbed Anime'.")
        return []

    ul_elements = td_parent.find_all('ul', recursive=False)
    if not ul_elements:
        logger.warning("No <ul> elements found in the streaming section.")
        return []

    days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    current_day = None

    for ul in ul_elements:
        # Check if this <ul> contains a day of the week
        day_text = ul.find_previous(string=True, text=True).strip()
        if day_text in days_of_week:
            current_day = day_text

        # Find all <li> elements within the current <ul>
        for li in ul.find_all('li', recursive=False):
            show_info = li.get_text(strip=True)
            # Extract MAL link if present
            mal_link = li.find('a', href=re.compile(r"https://myanimelist.net/anime/"))
            mal_link = mal_link['href'] if mal_link else None

            # Extract title and episode info
            title_match = re.search(r'^(.+?)(?:\s*\(Episodes:\s*(\d+)/(\d+)\))?', show_info)
            if title_match:
                title = title_match.group(1).strip()
                episodes_watched = int(title_match.group(2)) if title_match.group(2) else 0
                episodes_total = int(title_match.group(3)) if title_match.group(3) else None

                show = {
                    'title': title,
                    'mal_link': mal_link,
                    'episodes_watched': episodes_watched,
                    'episodes_total': episodes_total,
                    'day_of_week': current_day,
                    'status': 'ongoing'
                }
                ongoing_shows.append(show)
            else:
                logger.warning(f"Could not parse show info from: {show_info}")

    logger.info(f"Parsed {len(ongoing_shows)} ongoing shows.")
    return ongoing_shows

async def update_shows():
    """Update the shows database with the latest information from the forum."""
    init_db()
    html_content = await fetch_forum_page()
    if not html_content:
        return

    ongoing_shows = parse_ongoing_schedule(html_content)

    conn = sqlite3.connect('shows.db')
    c = conn.cursor()

    # Clear existing ongoing shows
    c.execute("DELETE FROM shows WHERE status = 'ongoing'")
    conn.commit()

    # Insert new ongoing shows
    for show in ongoing_shows:
        c.execute('''INSERT INTO shows (title, mal_link, episodes_total, episodes_watched, day_of_week, status, last_updated)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (show['title'], show['mal_link'], show['episodes_total'], show['episodes_watched'],
                   show['day_of_week'], show['status'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    conn.commit()
    conn.close()
    logger.info("Database updated with ongoing shows.")

if __name__ == "__main__":
    asyncio.run(update_shows())