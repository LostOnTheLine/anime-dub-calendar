import requests
from bs4 import BeautifulSoup
import yaml
import os
import subprocess
from datetime import datetime

REPO_DIR = "/app/repo"

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

def save_parsed_entry(mal_id, metadata):
    """Save a manual entry to parsed_data.yaml."""
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
    """Remove a manual entry from parsed_data.yaml."""
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