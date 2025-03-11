import yaml
import schedule
import time
from scraper import scrape_forum_post, load_cached_data, save_cached_data, needs_update
from web_interface import run_web_app
import threading
import os
import subprocess

REPO_URL = "https://github.com/LostOnTheLine/anime-dub-calendar.git"
REPO_DIR = "/app/repo"

def git_setup():
    if not os.path.exists(REPO_DIR):
        subprocess.run(["git", "clone", REPO_URL, REPO_DIR], check=True)
    os.chdir(REPO_DIR)
    subprocess.run(["git", "config", "user.name", "Docker Container"], check=True)
    subprocess.run(["git", "config", "user.email", "docker@local"], check=True)
    token = os.getenv("GITHUB_TOKEN")
    if token:
        subprocess.run(["git", "remote", "set-url", "origin", f"https://{token}@github.com/LostOnTheLine/anime-dub-calendar.git"], check=True)

def git_pull():
    os.chdir(REPO_DIR)
    subprocess.run(["git", "pull", "origin", "Grok"], check=True)
    # Copy updated files to /data
    subprocess.run(["cp", "data/manual_overrides.yaml", "/data/"], check=False)
    subprocess.run(["cp", "data/parsed_data.yaml", "/data/"], check=False)

def git_push():
    os.chdir(REPO_DIR)
    subprocess.run(["cp", "/data/metadata.yaml", "data/"], check=True)
    subprocess.run(["cp", "/data/parsed_data.yaml", "data/"], check=True)
    subprocess.run(["cp", "/data/manual_overrides.yaml", "data/"], check=True)
    subprocess.run(["git", "add", "data/"], check=True)
    subprocess.run(["git", "commit", "-m", "Update metadata from container"], check=False)  # check=False to skip if no changes
    subprocess.run(["git", "push", "origin", "Grok"], check=True)

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
    git_pull()  # Pull latest before updating
    data = scrape_forum_post()
    if not data:
        print("Failed to scrape forum post")
        return

    cached_data = load_cached_data()
    if not needs_update(cached_data, data):
        print("No update needed")
        return

    metadata = {}
    manual_file = "/data/manual_overrides.yaml"
    manual = {}
    if os.path.exists(manual_file):
        with open(manual_file, "r") as f:
            manual = yaml.safe_load(f) or {}
    else:
        print("Manual overrides file not found, proceeding without it")

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
    git_push()  # Push updates after processing
    print("Metadata updated and pushed to GitHub")

def run_scheduler():
    git_setup()  # Initial setup
    schedule.every(1).hours.do(update_metadata)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    run_web_app()