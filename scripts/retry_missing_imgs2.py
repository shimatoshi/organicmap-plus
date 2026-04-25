#!/usr/bin/env python3
"""Retry with proper Wikimedia API usage - use Special:FilePath instead of direct URLs."""

import json, os, time, urllib.parse, urllib.request, hashlib
from pathlib import Path
from io import BytesIO
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "spots"
DATA_FILE = BASE_DIR / "spots_data.json"
IMG_DIR = BASE_DIR / "img"
WEBP_QUALITY = 60
IMG_MAX_WIDTH = 800

UA = "OrganicMapPlusBot/1.0 (https://github.com/organicmap-plus; organic.map.plus@gmail.com) python-urllib"

def search_wikimedia_image(query):
    search_url = (
        "https://commons.wikimedia.org/w/api.php?"
        "action=query&list=search&srnamespace=6&srlimit=5&format=json&"
        f"srsearch={urllib.parse.quote(query)}"
    )
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": UA})
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


def get_thumb_url_via_md5(filename):
    """Construct Wikimedia Commons thumbnail URL directly using MD5 hash."""
    # Remove "File:" prefix
    name = filename.replace("File:", "").replace(" ", "_")
    md5 = hashlib.md5(name.encode("utf-8")).hexdigest()

    # For thumbnails, use the API approach
    api_url = (
        "https://commons.wikimedia.org/w/api.php?"
        f"action=query&titles={urllib.parse.quote(filename)}"
        "&prop=imageinfo&iiprop=url|size&iiurlwidth=800&format=json"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                thumb = info.get("thumburl")
                orig = info.get("url")
                return thumb or orig
    except Exception as e:
        print(f"  API failed: {e}")
    return None


def download_and_convert_webp(url, output_path):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "image/*",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
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
                img_rel = spot.get("img", "")
                if not img_rel or not (BASE_DIR / img_rel).exists():
                    md_path = spot["md"]
                    img_rel_expected = md_path.replace("md/", "img/").replace(".md", ".webp")
                    missing.append((pref_name, city["name"], spot, img_rel_expected))

    print(f"Missing images: {len(missing)}")

    success = 0
    for i, (pref_name, city_name, spot, img_rel) in enumerate(missing):
        print(f"\n[{i+1}/{len(missing)}] {city_name} - {spot['name']}")
        img_path = BASE_DIR / img_rel

        queries = [
            spot["name"],
            f"{city_name} {spot['name']}",
            f"{spot['name']} {pref_name}",
        ]

        done = False
        for query in queries:
            print(f"  Searching: {query}")
            time.sleep(5)
            file_title = search_wikimedia_image(query)
            if not file_title:
                continue

            print(f"  Found: {file_title}")
            time.sleep(3)
            img_url = get_thumb_url_via_md5(file_title)
            if not img_url:
                continue

            print(f"  URL: {img_url[:80]}...")
            time.sleep(5)
            size = download_and_convert_webp(img_url, str(img_path))
            if size:
                spot["img"] = img_rel
                print(f"  OK: {size/1024:.1f} KB")
                success += 1
                done = True
                break
            else:
                print(f"  FAILED")

        if not done:
            print(f"  SKIPPED (no image found)")

    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone: {success}/{len(missing)} recovered")

if __name__ == "__main__":
    main()
