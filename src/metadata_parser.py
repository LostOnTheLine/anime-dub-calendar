import requests
from bs4 import BeautifulSoup
import yaml
from scraper import scrape_forum_post
import os

def parse_show_page(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    data = {}
    info = soup.find("div", {"class": "leftside"})
    for span in info.find_all("span", {"class": "dark_text"}):
        key = span.text.strip(":")
        value = span.next_sibling.strip()
        if key == "Studios":
            data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
        elif key == "Genres":
            data[key] = "|".join(a.text for a in span.find_next_siblings("a"))
        elif key == "Streaming Platforms":
            data["Streaming"] = "|".join(a.find("div", {"class": "caption"}).text for a in soup.find_all("a", {"class": "broadcast-item"}))
        else:
            data[key] = value
    return data

def update_metadata():
    data = scrape_forum_post()
    metadata = {}
    manual = yaml.safe_load(open("data/manual_overrides.yaml")) or {}

    for day, shows in data["sections"]["Currently Streaming SimulDubbed Anime"].items():
        for show in shows:
            mal_id = show["mal_id"]
            metadata[mal_id] = parse_show_page(show["url"])
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

if __name__ == "__main__":
    update_metadata()