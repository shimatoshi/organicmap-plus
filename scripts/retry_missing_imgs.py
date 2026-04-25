#!/usr/bin/env python3
"""Retry downloading missing images with longer delays to avoid rate limiting."""

import json, os, time, urllib.parse, urllib.request
from pathlib import Path
from io import BytesIO
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "spots"
DATA_FILE = BASE_DIR / "spots_data.json"
IMG_DIR = BASE_DIR / "img"
WEBP_QUALITY = 60
IMG_MAX_WIDTH = 800

def search_wikimedia_image(query):
    search_url = (
        "https://commons.wikimedia.org/w/api.php?"
        "action=query&list=search&srnamespace=6&srlimit=5&format=json&"
        f"srsearch={urllib.parse.quote(query)}"
    )
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "OrganicMapPlus/1.0 (contact: organic@example.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("query", {}).get("search", [])
            for r in results:
                title = r["title"]
                if any(title.lower().endswith(ext) for ext in ['.svg', '.pdf', '.ogg', '.wav', '.mp3']):
                    continue
                return title
    except Exception as e:
        print(f"  Search failed: {e}")
    return None

def get_image_url(file_title):
    api_url = (
        "https://commons.wikimedia.org/w/api.php?"
        "action=query&prop=imageinfo&iiprop=url&iiurlwidth=800&format=json&"
        f"titles={urllib.parse.quote(file_title)}"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "OrganicMapPlus/1.0 (contact: organic@example.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                return info.get("thumburl") or info.get("url")
    except Exception as e:
        print(f"  URL fetch failed: {e}")
    return None

def download_and_convert_webp(url, output_path):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OrganicMapPlus/1.0 (contact: organic@example.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            img_data = resp.read()
        img = Image.open(BytesIO(img_data))
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (30, 30, 46))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        if img.width > IMG_MAX_WIDTH:
            ratio = IMG_MAX_WIDTH / img.width
            img = img.resize((IMG_MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)
        img.save(output_path, 'WEBP', quality=WEBP_QUALITY)
        return os.path.getsize(output_path)
    except Exception as e:
        print(f"  Download failed: {e}")
        return 0

def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    missing = []

    for pref_name, pref in data["prefectures"].items():
        for cid, city in pref["cities"].items():
            for spot in city["spots"]:
                if not spot["img"]:
                    missing.append((pref_name, city["name"], spot))
                elif not (BASE_DIR / spot["img"]).exists():
                    missing.append((pref_name, city["name"], spot))

    print(f"Missing images: {len(missing)}")

    for i, (pref_name, city_name, spot) in enumerate(missing):
        print(f"\n[{i+1}/{len(missing)}] {city_name} - {spot['name']}")

        # Derive expected file path from md path
        md_path = spot["md"]
        img_rel = md_path.replace("md/", "img/").replace(".md", ".webp")
        img_path = BASE_DIR / img_rel

        # Search
        query = spot["name"]
        print(f"  Searching: {query}")
        time.sleep(3)  # Longer delay
        file_title = search_wikimedia_image(query)
        if not file_title:
            # Try with city name
            query2 = f"{city_name} {spot['name']}"
            print(f"  Trying: {query2}")
            time.sleep(3)
            file_title = search_wikimedia_image(query2)

        if file_title:
            print(f"  Found: {file_title}")
            time.sleep(2)
            img_url = get_image_url(file_title)
            if img_url:
                time.sleep(3)
                size = download_and_convert_webp(img_url, str(img_path))
                if size:
                    spot["img"] = img_rel
                    print(f"  Saved: {size/1024:.1f} KB")
                else:
                    print(f"  FAILED to download")
            else:
                print(f"  No URL")
        else:
            print(f"  No results")

    # Save updated data
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nUpdated {DATA_FILE}")

if __name__ == "__main__":
    main()
