import yaml
import schedule
import time
from scraper import scrape_forum_post, load_cached_data, save_cached_data, needs_update
from web_interface import run_web_app
import threading

def parse_show_page(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    data = {}
    info = soup.find("div", {"class": "leftside"})
    if info:
        for span in info.find_all("span", {"class": "dark_text"}):
            key = span.text.strip(":")
            value = span.next_sibling.strip() if span.next_sibling else "Not Listed"
            if key == "Studios":
                data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
            elif key == "Genres":
                data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
            elif key == "Streaming Platforms":
                data["Streaming"] = "|".join(a.find("div", {"class": "caption"}).text for a in soup.find_all("a", {"class": "broadcast-item"})) or "Not Listed"
            else:
                data[key] = value
    return data

def update_metadata():
    data = scrape_forum_post()
    if not data:
        print("Failed to scrape forum post")
        return

    cached_data = load_cached_data()
    if not needs_update(cached_data, data):
        print("No update needed")
        return

    metadata = {}
    manual = yaml.safe_load(open("/data/manual_overrides.yaml", "r")) or {}

    for day, shows in data["sections"]["Currently Streaming SimulDubbed Anime"].items():
        for show in shows:
            mal_id = show["mal_id"]
            metadata[mal_id] = parse_show_page(show["url"]) or {"ShowName": show["title"]}
            metadata[mal_id].update({
                "ShowName": show["title"],
                "LatestEpisode": show["current_episode"],
                "TotalEpisodes": show["total_episodes"],
                "AirDay": day,
                "MAL_ID": mal_id
            })
            if mal_id in manual:
                metadata[mal_id].update(manual[mal_id])

    with open("/data/metadata.yaml", "w") as f:
        yaml.safe_dump(metadata, f)
    save_cached_data(data)
    print("Metadata updated")

def run_scheduler():
    schedule.every().day.at("08:00").do(update_metadata)  # Runs daily at 8:00 UTC
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # Run scheduler in a separate thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    # Run web app in the main thread
    run_web_app()