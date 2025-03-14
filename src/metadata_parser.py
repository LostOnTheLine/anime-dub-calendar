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
from datetime import datetime, timedelta

REPO_URL = "https://github.com/LostOnTheLine/anime-dub-calendar.git"
REPO_DIR = "/app/repo"

def git_setup():
    os.makedirs(REPO_DIR, exist_ok=True)
    if not os.path.exists(os.path.join(REPO_DIR, ".git")):
        print(f"Cloning repository into {REPO_DIR}...")
        try:
            subprocess.run(["git", "clone", REPO_URL, REPO_DIR], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to clone repository: {e}")
            raise
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
        subprocess.run(["git", "fetch", "origin"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "checkout", "Grok"], cwd=REPO_DIR, check=True)
        print("Git setup completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Git setup failed: {e}")
        raise

def git_pull_if_needed():
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

def save_parsed_entry(mal_id, metadata):
    parsed_file = os.path.join(REPO_DIR, "parsed_data.yaml")
    parsed = {}
    if os.path.exists(parsed_file):
        with open(parsed_file, "r") as f:
            parsed = yaml.safe_load(f) or {}
    metadata["added_date"] = datetime.now().isoformat()
    metadata["auto_remove_after_days"] = metadata.get("auto_remove_after_days", 180)  # Default 6 months
    parsed[mal_id] = metadata
    with open(parsed_file, "w") as f:
        yaml.safe_dump(parsed, f)
    git_push()
    print(f"Parsed entry for MAL_ID {mal_id} saved and pushed.")

def remove_parsed_entry(mal_id):
    parsed_file = os.path.join(REPO_DIR, "parsed_data.yaml")
    if os.path.exists(parsed_file):
        with open(parsed_file, "r") as f:
            parsed = yaml.safe_load(f) or {}
        if mal_id in parsed:
            del parsed[mal_id]
            with open(parsed_file, "w") as f:
                yaml.safe_dump(parsed, f)
            git_push()
            print(f"Parsed entry for MAL_ID {mal_id} removed and pushed.")

def update_metadata():
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

    parsed_file = os.path.join(REPO_DIR, "parsed_data.yaml")
    parsed = {}
    if os.path.exists(parsed_file):
        with open(parsed_file, "r") as f:
            parsed = yaml.safe_load(f) or {}
    
    # Check for auto-removal
    now = datetime.now()
    updated = False
    for mal_id, entry in list(parsed.items()):
        added_date = datetime.fromisoformat(entry.get("added_date", now.isoformat()))
        days = entry.get("auto_remove_after_days", 180)
        if now > added_date + timedelta(days=days):
            del parsed[mal_id]
            updated = True
            print(f"Auto-removed MAL_ID {mal_id} after {days} days.")

    if updated:
        with open(parsed_file, "w") as f:
            yaml.safe_dump(parsed, f)
        git_push()

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
            if mal_id in parsed:
                metadata[mal_id].update(parsed[mal_id])

    with open(os.path.join(REPO_DIR, "metadata.yaml"), "w") as f:
        yaml.safe_dump(metadata, f)
    save_cached_data(data)
    git_push()
    print("Metadata updated and pushed to GitHub")

def run_scheduler():
    git_setup()
    sync_interval = int(os.getenv("SYNC_INTERVAL_HOURS", "1"))
    schedule.every(sync_interval).hours.do(update_metadata)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name_