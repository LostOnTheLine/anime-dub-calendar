import yaml
import schedule
import time
from scraper import scrape_forum_post, load_cached_data, save_cached_data, needs_update
from web_interface import run_web_app
import threading
import os
import subprocess
import requests
from bs4 import BeautifulSoup

REPO_URL = "https://github.com/LostOnTheLine/anime-dub-calendar.git"
REPO_DIR = "/data"

def git_setup():
    """Set up the Git repository in /data."""
    # Ensure /data exists
    os.makedirs(REPO_DIR, exist_ok=True)

    # Check if /data is already a Git repository
    if not os.path.exists(os.path.join(REPO_DIR, ".git")):
        print(f"Cloning repository into {REPO_DIR}...")
        try:
            subprocess.run(["git", "clone", REPO_URL, REPO_DIR], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to clone repository: {e}")
            raise

    # Configure Git user and remote
    try:
        subprocess.run(["git", "config", "user.name", "Docker Container"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "config", "user.email", "docker@local"], cwd=REPO_DIR, check=True)
        token = os.getenv("GITHUB_TOKEN")
        if token:
            subprocess.run(
                ["git", "remote", "set-url", "origin", f"https://{token}@github.com/LostOnTheLine/anime-dub-calendar.git"],
                cwd=REPO_DIR,
                check=True
            )
        else:
            print("Warning: GITHUB_TOKEN not set, Git operations may fail")
        
        # Ensure Grok branch
        subprocess.run(["git", "fetch", "origin"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "checkout", "Grok"], cwd=REPO_DIR, check=True)
        print("Git setup completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Git setup failed: {e}")
        raise

def git_pull_if_needed():
    """Pull updates from GitHub if there are new changes."""
    try:
        subprocess.run(["git", "fetch", "origin", "Grok"], cwd=REPO_DIR, check=True)
        local_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.strip()
        remote_commit = subprocess.run(["git", "rev-parse", "origin/Grok"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.strip()
        
        if local_commit != remote_commit:
            print("New version detected, pulling changes")
            subprocess.run(["git", "pull", "origin", "Grok"], cwd=REPO_DIR, check=True)
        else:
            print("No new version on GitHub")
    except subprocess.CalledProcessError as e:
        print(f"Failed to pull updates: {e}")

def git_push():
    """Push changes to GitHub."""
    try:
        subprocess.run(["git", "add", "."], cwd=REPO_DIR, check=True)
        result = subprocess.run(["git", "commit", "-m", "Update metadata from container"], cwd=REPO_DIR, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            subprocess.run(["git", "push", "origin", "Grok"], cwd=REPO_DIR, check=True)
            print("Changes pushed to GitHub")
        else:
            print("No changes to commit")
    except subprocess.CalledProcessError as e:
        print(f"Failed to push changes: {e}")

def parse_show_page(url):
    """Parse a show's MAL page for metadata."""
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
    """Update metadata.yaml from forum data."""
    git_pull_if_needed()
    data = scrape_forum_post()
    if not data:
        print("Failed to scrape forum post")
        return

    cached_data = load_cached_data()
    if not needs_update(cached_data, data):
        print("No update needed")
        return

    metadata = {}
    manual_file = os.path.join(REPO_DIR, "manual_overrides.yaml")
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

    with open(os.path.join(REPO_DIR, "metadata.yaml"), "w") as f:
        yaml.safe_dump(metadata, f)
    save_cached_data(data)
    git_push()
    print("Metadata updated and pushed to GitHub")

def run_scheduler():
    """Run the scheduled metadata updates."""
    git_setup()  # Initial setup and pull on startup
    sync_interval = int(os.getenv("SYNC_INTERVAL_HOURS", "1"))  # Default to 1 hour
    schedule.every(sync_interval).hours.do(update_metadata)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    run_web_app()