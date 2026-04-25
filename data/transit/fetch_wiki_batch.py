#!/usr/bin/env python3
"""
Wikipedia API バッチ取得 - 日本の鉄道駅記事から説明文を一括取得
Overpass結果を待たず、Wikipedia カテゴリから駅一覧を取得して先行処理
出力: wiki_stations.json
"""
import json, urllib.request, urllib.parse, time, sys, os

BASE = os.path.dirname(__file__)
OUT = os.path.join(BASE, "wiki_stations.json")
WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"

def wiki_get(params_dict, timeout=30):
    params_dict["format"] = "json"
    url = f"{WIKIPEDIA_API}?{urllib.parse.urlencode(params_dict)}"
    req = urllib.request.Request(url, headers={"User-Agent": "OrganicMapPlus/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  API error: {e}", file=sys.stderr)
        return None

def get_category_members(category, limit=500):
    """Get all pages in a category"""
    members = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmlimit": str(min(limit, 500)),
        "cmtype": "page",
    }
    cont = None
    while True:
        if cont:
            params["cmcontinue"] = cont
        data = wiki_get(params)
        if not data:
            break
        for m in data.get("query", {}).get("categorymembers", []):
            members.append(m["title"])
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont or len(members) >= limit:
            break
        time.sleep(0.5)
    return members

def batch_get_extracts(titles, batch_size=20):
    """Get extracts for multiple titles at once"""
    results = {}
    for i in range(0, len(titles), batch_size):
        batch = titles[i:i+batch_size]
        params = {
            "action": "query",
            "titles": "|".join(batch),
            "prop": "extracts|coordinates|pageimages|pageprops",
            "exintro": "1",
            "explaintext": "1",
            "colimit": "max",
            "piprop": "original",
            "ppprop": "wikibase_item",
        }
        data = wiki_get(params)
        if not data:
            time.sleep(2)
            continue

        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1":
                continue
            title = page.get("title", "")
            extract = page.get("extract", "")
            coords = page.get("coordinates", [{}])
            lat = coords[0].get("lat") if coords else None
            lon = coords[0].get("lon") if coords else None
            image = page.get("original", {}).get("source", "")
            wikidata = page.get("pageprops", {}).get("wikibase_item", "")

            if extract:
                if len(extract) > 600:
                    extract = extract[:597] + "..."
                results[title] = {
                    "title": title,
                    "extract": extract,
                    "lat": lat,
                    "lon": lon,
                    "image_url": image,
                    "wikidata_id": wikidata,
                }

        time.sleep(0.5)
        if (i + batch_size) % 100 == 0:
            print(f"  Fetched {min(i + batch_size, len(titles))}/{len(titles)} extracts")

    return results

# Prefectural railway station categories
# Pattern: "Category:日本の鉄道駅_X" where X is hiragana initial
PREF_CATEGORIES = [
    "Category:日本の鉄道駅_あ", "Category:日本の鉄道駅_い", "Category:日本の鉄道駅_う",
    "Category:日本の鉄道駅_え", "Category:日本の鉄道駅_お",
    "Category:日本の鉄道駅_か", "Category:日本の鉄道駅_き", "Category:日本の鉄道駅_く",
    "Category:日本の鉄道駅_け", "Category:日本の鉄道駅_こ",
    "Category:日本の鉄道駅_さ", "Category:日本の鉄道駅_し", "Category:日本の鉄道駅_す",
    "Category:日本の鉄道駅_せ", "Category:日本の鉄道駅_そ",
    "Category:日本の鉄道駅_た", "Category:日本の鉄道駅_ち", "Category:日本の鉄道駅_つ",
    "Category:日本の鉄道駅_て", "Category:日本の鉄道駅_と",
    "Category:日本の鉄道駅_な", "Category:日本の鉄道駅_に", "Category:日本の鉄道駅_ぬ",
    "Category:日本の鉄道駅_ね", "Category:日本の鉄道駅_の",
    "Category:日本の鉄道駅_は", "Category:日本の鉄道駅_ひ", "Category:日本の鉄道駅_ふ",
    "Category:日本の鉄道駅_へ", "Category:日本の鉄道駅_ほ",
    "Category:日本の鉄道駅_ま", "Category:日本の鉄道駅_み", "Category:日本の鉄道駅_む",
    "Category:日本の鉄道駅_め", "Category:日本の鉄道駅_も",
    "Category:日本の鉄道駅_や", "Category:日本の鉄道駅_ゆ", "Category:日本の鉄道駅_よ",
    "Category:日本の鉄道駅_ら", "Category:日本の鉄道駅_り", "Category:日本の鉄道駅_る",
    "Category:日本の鉄道駅_れ", "Category:日本の鉄道駅_ろ",
    "Category:日本の鉄道駅_わ",
]

def main():
    # Load existing
    existing = {}
    if os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as f:
            existing = json.load(f).get("stations", {})
        print(f"Loaded {len(existing)} existing entries")

    # Step 1: Get all station article titles from Wikipedia categories
    all_titles = []
    print("=== Collecting station article titles from Wikipedia categories ===")
    for cat in PREF_CATEGORIES:
        kana = cat.split("_")[-1]
        members = get_category_members(cat, limit=500)
        all_titles.extend(members)
        print(f"  {kana}: {len(members)} articles")
        time.sleep(0.3)

    print(f"\nTotal station articles: {len(all_titles)}")

    # Filter out already fetched
    new_titles = [t for t in all_titles if t not in existing]
    print(f"New to fetch: {len(new_titles)}")

    # Step 2: Batch fetch extracts
    print("\n=== Fetching extracts ===")
    new_data = batch_get_extracts(new_titles)
    print(f"Got extracts for {len(new_data)} stations")

    # Merge
    existing.update(new_data)

    # Save
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(existing),
            "stations": existing,
        }, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(existing)} stations to {OUT}")

if __name__ == "__main__":
    main()
