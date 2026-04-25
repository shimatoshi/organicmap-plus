#!/usr/bin/env python3
"""
名所ガイド データ収集スクリプト
- Gemini API で市区町村ごとの名所3つ + 説明を取得
- Wikimedia Commons から画像を取得 → WebP q60 変換
- spots_data.json / .md / .webp を生成
"""

import json, os, sys, time, re, urllib.parse, urllib.request
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow required. pip install Pillow")
    sys.exit(1)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDhnv07MSx5Ao0RNvthOTSu9Y6JhsBFDYk")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "spots"
MD_DIR = BASE_DIR / "md"
IMG_DIR = BASE_DIR / "img"
DATA_FILE = BASE_DIR / "spots_data.json"

WEBP_QUALITY = 60
IMG_MAX_WIDTH = 800

# Prefecture codes and areas
PREFECTURES = {
    "北海道": {"code": "01", "area": "北海道"},
    "青森県": {"code": "02", "area": "東北"},
    "岩手県": {"code": "03", "area": "東北"},
    "宮城県": {"code": "04", "area": "東北"},
    "秋田県": {"code": "05", "area": "東北"},
    "山形県": {"code": "06", "area": "東北"},
    "福島県": {"code": "07", "area": "東北"},
    "茨城県": {"code": "08", "area": "関東"},
    "栃木県": {"code": "09", "area": "関東"},
    "群馬県": {"code": "10", "area": "関東"},
    "埼玉県": {"code": "11", "area": "関東"},
    "千葉県": {"code": "12", "area": "関東"},
    "東京都": {"code": "13", "area": "関東"},
    "神奈川県": {"code": "14", "area": "関東"},
    "新潟県": {"code": "15", "area": "中部"},
    "富山県": {"code": "16", "area": "中部"},
    "石川県": {"code": "17", "area": "中部"},
    "福井県": {"code": "18", "area": "中部"},
    "山梨県": {"code": "19", "area": "中部"},
    "長野県": {"code": "20", "area": "中部"},
    "岐阜県": {"code": "21", "area": "中部"},
    "静岡県": {"code": "22", "area": "中部"},
    "愛知県": {"code": "23", "area": "中部"},
    "三重県": {"code": "24", "area": "近畿"},
    "滋賀県": {"code": "25", "area": "近畿"},
    "京都府": {"code": "26", "area": "近畿"},
    "大阪府": {"code": "27", "area": "近畿"},
    "兵庫県": {"code": "28", "area": "近畿"},
    "奈良県": {"code": "29", "area": "近畿"},
    "和歌山県": {"code": "30", "area": "近畿"},
    "鳥取県": {"code": "31", "area": "中国"},
    "島根県": {"code": "32", "area": "中国"},
    "岡山県": {"code": "33", "area": "中国"},
    "広島県": {"code": "34", "area": "中国"},
    "山口県": {"code": "35", "area": "中国"},
    "徳島県": {"code": "36", "area": "四国"},
    "香川県": {"code": "37", "area": "四国"},
    "愛媛県": {"code": "38", "area": "四国"},
    "高知県": {"code": "39", "area": "四国"},
    "福岡県": {"code": "40", "area": "九州"},
    "佐賀県": {"code": "41", "area": "九州"},
    "長崎県": {"code": "42", "area": "九州"},
    "熊本県": {"code": "43", "area": "九州"},
    "大分県": {"code": "44", "area": "九州"},
    "宮崎県": {"code": "45", "area": "九州"},
    "鹿児島県": {"code": "46", "area": "九州"},
    "沖縄県": {"code": "47", "area": "沖縄"},
}


def gemini_request(prompt, retries=3):
    """Call Gemini API with retry."""
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        GEMINI_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                # Strip markdown code fences if present
                text = re.sub(r'^```json\s*', '', text.strip())
                text = re.sub(r'\s*```$', '', text.strip())
                return json.loads(text)
        except Exception as e:
            print(f"  Gemini attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    return None


def get_spots_for_prefecture(pref_name):
    """Get municipalities and their 3 famous spots using Gemini."""
    prompt = f"""日本の{pref_name}にある主要な市区町村とその名所を教えてください。

以下のJSON形式で返してください:
{{
  "cities": [
    {{
      "id": "romaji_id",
      "name": "日本語の市区町村名",
      "spots": [
        {{
          "name": "名所の名前",
          "summary": "20文字以内の一行説明",
          "description": "150-250文字の詳しい説明。歴史的背景、見どころ、アクセス情報を含めてください。",
          "search_query": "Wikimedia Commonsで画像を検索するための英語キーワード（例: 'Sapporo Clock Tower'）"
        }}
      ]
    }}
  ]
}}

ルール:
- 市区町村は人口の多い順に最大15個まで
- 各市区町村につき名所は3つ
- idはローマ字（例: sapporo, hakodate）
- 有名で画像が見つかりやすい名所を優先
- search_queryは英語で、固有名詞を含めること
- descriptionは日本語で書くこと"""

    return gemini_request(prompt)


def search_wikimedia_image(query):
    """Search Wikimedia Commons for a free image."""
    search_url = (
        "https://commons.wikimedia.org/w/api.php?"
        "action=query&list=search&srnamespace=6&srlimit=5&format=json&"
        f"srsearch={urllib.parse.quote(query)}"
    )
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "OrganicMapPlus/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("query", {}).get("search", [])
            for r in results:
                title = r["title"]
                # Skip SVG, PDF, audio
                if any(title.lower().endswith(ext) for ext in ['.svg', '.pdf', '.ogg', '.wav', '.mp3']):
                    continue
                return title
    except Exception as e:
        print(f"    Wikimedia search failed for '{query}': {e}")
    return None


def get_image_url(file_title):
    """Get direct image URL from Wikimedia Commons file title."""
    api_url = (
        "https://commons.wikimedia.org/w/api.php?"
        "action=query&prop=imageinfo&iiprop=url&iiurlwidth=800&format=json&"
        f"titles={urllib.parse.quote(file_title)}"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "OrganicMapPlus/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                # Prefer thumbnail (already resized)
                return info.get("thumburl") or info.get("url")
    except Exception as e:
        print(f"    Failed to get URL for {file_title}: {e}")
    return None


def download_and_convert_webp(url, output_path):
    """Download image and convert to WebP."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OrganicMapPlus/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            img_data = resp.read()

        img = Image.open(BytesIO(img_data))

        # Convert to RGB if needed (RGBA/P etc)
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (30, 30, 46))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize if too wide
        if img.width > IMG_MAX_WIDTH:
            ratio = IMG_MAX_WIDTH / img.width
            img = img.resize((IMG_MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)

        img.save(output_path, 'WEBP', quality=WEBP_QUALITY)
        return os.path.getsize(output_path)
    except Exception as e:
        print(f"    Download/convert failed: {e}")
        return 0


def build_prefecture(pref_name, existing_data=None):
    """Build data for one prefecture."""
    code = PREFECTURES[pref_name]["code"]
    area = PREFECTURES[pref_name]["area"]
    prefix = code

    print(f"\n{'='*60}")
    print(f"Processing: {pref_name} ({code})")
    print(f"{'='*60}")

    # Get spots from Gemini
    print("  Querying Gemini for spots...")
    result = get_spots_for_prefecture(pref_name)
    if not result or "cities" not in result:
        print(f"  FAILED: No data from Gemini for {pref_name}")
        return None

    pref_data = {
        "area": area,
        "cities": {}
    }

    for city in result["cities"]:
        cid = city["id"]
        city_name = city["name"]
        print(f"\n  {city_name} ({cid}):")

        city_data = {
            "name": city_name,
            "spots": []
        }

        for i, spot in enumerate(city["spots"][:3]):
            spot_idx = i + 1
            file_base = f"{prefix}_{cid}_{spot_idx}"
            md_path = MD_DIR / f"{file_base}.md"
            img_path = IMG_DIR / f"{file_base}.webp"
            md_rel = f"md/{file_base}.md"
            img_rel = f"img/{file_base}.webp"

            print(f"    [{spot_idx}] {spot['name']}")

            # Write .md
            md_content = f"# {spot['name']}\n\n"
            md_content += f"**{city_name}** ({pref_name})\n\n"
            md_content += spot.get("description", "")
            md_path.write_text(md_content, encoding="utf-8")

            # Search & download image
            img_size = 0
            query = spot.get("search_query", spot["name"])
            print(f"      Searching: {query}")
            file_title = search_wikimedia_image(query)
            if file_title:
                print(f"      Found: {file_title}")
                img_url = get_image_url(file_title)
                if img_url:
                    img_size = download_and_convert_webp(img_url, str(img_path))
                    if img_size:
                        print(f"      Saved: {img_size/1024:.1f} KB")
                    else:
                        print(f"      Convert failed")
                else:
                    print(f"      No URL found")
            else:
                # Fallback: try Japanese name
                print(f"      No results, trying: {spot['name']}")
                file_title = search_wikimedia_image(spot["name"])
                if file_title:
                    img_url = get_image_url(file_title)
                    if img_url:
                        img_size = download_and_convert_webp(img_url, str(img_path))
                        if img_size:
                            print(f"      Fallback saved: {img_size/1024:.1f} KB")

            spot_data = {
                "name": spot["name"],
                "summary": spot.get("summary", ""),
                "md": md_rel,
                "img": img_rel if img_size > 0 else "",
            }
            city_data["spots"].append(spot_data)

            time.sleep(0.5)  # Rate limit for Wikimedia

        pref_data["cities"][cid] = city_data

    return pref_data


def main():
    MD_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing data if any
    all_data = {"prefectures": {}}
    if DATA_FILE.exists():
        try:
            all_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except:
            pass

    # Parse args: which prefectures to process
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["北海道"]

    if targets == ["--all"]:
        targets = list(PREFECTURES.keys())

    for pref in targets:
        if pref not in PREFECTURES:
            print(f"Unknown prefecture: {pref}")
            continue

        pref_data = build_prefecture(pref)
        if pref_data:
            all_data["prefectures"][pref] = pref_data

        # Save after each prefecture
        DATA_FILE.write_text(
            json.dumps(all_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n  Saved to {DATA_FILE}")

    # Summary
    total_spots = sum(
        len(c["spots"])
        for p in all_data["prefectures"].values()
        for c in p["cities"].values()
    )
    total_imgs = len(list(IMG_DIR.glob("*.webp")))
    total_size = sum(f.stat().st_size for f in IMG_DIR.glob("*.webp"))

    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"  Prefectures: {len(all_data['prefectures'])}")
    print(f"  Total spots: {total_spots}")
    print(f"  Images: {total_imgs} ({total_size/1024/1024:.1f} MB)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
