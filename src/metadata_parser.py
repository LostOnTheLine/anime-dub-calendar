import yaml
import schedule
import time
from scraper import scrape_forum_post, load_cached_data, save_cached_data, needs_update
from web_interface import run_web_app
import threading
import os
import subprocess
from datetime import datetime, timedelta
from utils import parse_show_page, save_parsed_entry, remove_parsed_entry, git_push
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/LostOnTheLine/anime-dub-calendar.git"
REPO_DIR = "/app/repo"

def git_setup():
    os.makedirs(REPO_DIR, exist_ok=True)
    repo_path = os.path.join(REPO_DIR, ".git")
    if not os.path.exists(repo_path):
        logger.info(f"No .git directory found at {REPO_DIR}, cloning repository...")
        try:
            subprocess.run(["git", "clone", REPO_URL, REPO_DIR], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to clone repository: {e}")
            return False
    else:
        logger.info(f"Found existing .git directory at {REPO_DIR}, verifying status...")
        try:
            # Check if it's a valid Git repo
            subprocess.run(["git", "status"], cwd=REPO_DIR, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Invalid Git repository at {REPO_DIR}: {e}")
            return False

    try:
        # Configure Git if not already set
        result = subprocess.run(["git", "config", "user.name"], cwd=REPO_DIR, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            subprocess.run(["git", "config", "user.name", "Docker Container"], cwd=REPO_DIR, check=True)
            logger.debug("Set Git user.name to 'Docker Container'")
        result = subprocess.run(["git", "config", "user.email"], cwd=REPO_DIR, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            subprocess.run(["git", "config", "user.email", "docker@local"], cwd=REPO_DIR, check=True)
            logger.debug("Set Git user.email to 'docker@local'")
        token = os.getenv("GITHUB_TOKEN")
        if token:
            subprocess.run(
                ["git", "remote", "set-url", "origin", f"https://{token}@github.com/LostOnTheLine/anime-dub-calendar.git"],
                cwd=REPO_DIR,
                check=True
            )
            logger.debug("Updated Git remote URL with GITHUB_TOKEN")
        else:
            logger.warning("GITHUB_TOKEN not set, Git operations may fail for authenticated actions")
        subprocess.run(["git", "fetch", "origin"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "checkout", "Grok"], cwd=REPO_DIR, check=True)
        logger.info("Git setup completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git setup failed: {e}")
        return False

def git_pull_if_needed():
    try:
        subprocess.run(["git", "fetch", "origin", "Grok"], cwd=REPO_DIR, check=True)
        local_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.strip()
        remote_commit = subprocess.run(["git", "rev-parse", "origin/Grok"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.strip()
        if local_commit != remote_commit:
            logger.info("New version detected, pulling changes")
            subprocess.run(["git", "pull", "origin", "Grok"], cwd=REPO_DIR, check=True)
        else:
            logger.info("No new version on GitHub")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to pull updates: {e}")

def update_metadata():
    git_pull_if_needed()
    data = scrape_forum_post()
    if not data:
        logger.error("Failed to scrape forum post")
        return

    cached_data = load_cached_data()
    if not needs_update(cached_data, data):
        logger.info("No update needed")
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
    
    now = datetime.now()
    updated = False
    for mal_id, entry in list(parsed.items()):
        added_date = datetime.fromisoformat(entry.get("added_date", now.isoformat()))
        days = entry.get("auto_remove_after_days", 180)
        if now > added_date + timedelta(days=days):
            del parsed[mal_id]
            updated = True
            logger.info(f"Auto-removed MAL_ID {mal_id} after {days} days.")

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
    logger.info("Metadata updated and pushed to GitHub")

def run_scheduler():
    if git_setup():
        sync_interval = int(os.getenv("SYNC_INTERVAL_HOURS", "1"))
        schedule.every(sync_interval).hours.do(update_metadata)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        logger.error("Scheduler not started due to Git setup failure")

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    run_web_app()