#!/usr/bin/env python3
"""
Phase 3: 駅データ enrichment
- Wikipedia 説明文
- Wikimedia Commons 写真URL
- 最寄りコンビニ（座標+住所）
- 最寄り飲食店（座標+住所）

all_stations.json を読み込んで stations_enriched.json を出力
Overpass API のレート制限を考慮してバッチ処理
"""
import json, urllib.request, urllib.parse, time, sys, os, re

BASE = os.path.dirname(__file__)
STATIONS_FILE = os.path.join(BASE, "all_stations.json")
OUT_FILE = os.path.join(BASE, "stations_enriched.json")
PROGRESS_FILE = os.path.join(BASE, ".enrich_progress.json")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

def http_get(url, timeout=30, retries=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OrganicMapPlus/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None

def overpass_query(query, retries=3):
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(OVERPASS_URL, data, headers={"User-Agent": "OrganicMapPlus/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  Overpass retry {attempt+1}: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(20 * (attempt + 1))
    return None

def get_wikipedia_extract(station_name):
    """Get Wikipedia extract for a station"""
    # Try "XX駅" article first
    titles_to_try = [f"{station_name}駅", station_name]
    if station_name.endswith("駅"):
        titles_to_try = [station_name, station_name[:-1]]

    for title in titles_to_try:
        params = urllib.parse.urlencode({
            "action": "query",
            "titles": title,
            "prop": "extracts|pageimages",
            "exintro": 1,
            "explaintext": 1,
            "exsectionformat": "plain",
            "piprop": "original",
            "format": "json",
        })
        resp = http_get(f"{WIKIPEDIA_API}?{params}")
        if not resp:
            continue
        try:
            data = json.loads(resp)
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if pid == "-1":
                    continue
                extract = page.get("extract", "")
                image = page.get("original", {}).get("source", "")
                if extract:
                    # Trim to ~500 chars
                    if len(extract) > 500:
                        extract = extract[:497] + "..."
                    return {"text": extract, "image": image, "title": page.get("title", "")}
        except:
            pass
    return None

def get_wikidata_image(wikidata_id):
    """Get image from Wikidata entity"""
    if not wikidata_id:
        return None
    params = urllib.parse.urlencode({
        "action": "wbgetclaims",
        "entity": wikidata_id,
        "property": "P18",
        "format": "json",
    })
    resp = http_get(f"{WIKIDATA_API}?{params}")
    if not resp:
        return None
    try:
        data = json.loads(resp)
        claims = data.get("claims", {}).get("P18", [])
        if claims:
            filename = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
            if filename:
                # Convert to Commons URL
                import hashlib
                md5 = hashlib.md5(filename.replace(" ", "_").encode()).hexdigest()
                encoded = urllib.parse.quote(filename.replace(" ", "_"))
                return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{md5[0]}/{md5[:2]}/{encoded}/640px-{encoded}"
    except:
        pass
    return None

def get_nearby_poi(lat, lon, poi_type, radius=500):
    """
    Get nearest POI using Overpass.
    poi_type: "convenience" or "restaurant"
    Returns: {name, lat, lon, address} or None
    """
    if poi_type == "convenience":
        tag_filter = '["shop"="convenience"]'
    elif poi_type == "restaurant":
        tag_filter = '["amenity"~"restaurant|fast_food|cafe"]'
    else:
        return None

    query = f"""
[out:json][timeout:30];
(
  node{tag_filter}(around:{radius},{lat},{lon});
);
out body 1;
"""
    result = overpass_query(query, retries=2)
    if not result:
        return None

    elements = result.get("elements", [])
    if not elements:
        # Try larger radius
        if radius < 1000:
            return get_nearby_poi(lat, lon, poi_type, 1000)
        return None

    el = elements[0]
    tags = el.get("tags", {})

    # Build address from tags
    addr_parts = []
    for k in ["addr:province", "addr:city", "addr:quarter", "addr:neighbourhood",
              "addr:block_number", "addr:housenumber"]:
        v = tags.get(k, "")
        if v:
            addr_parts.append(v)
    address = "".join(addr_parts) if addr_parts else tags.get("addr:full", "")

    return {
        "name": tags.get("name", ""),
        "lat": el.get("lat"),
        "lon": el.get("lon"),
        "address": address,
        "brand": tags.get("brand", ""),
        "osm_id": el.get("id"),
    }


def batch_nearby_pois(stations_batch):
    """
    Batch query for nearest convenience stores and restaurants for multiple stations.
    More efficient than individual queries.
    """
    if not stations_batch:
        return {}

    # Build a union query for all stations
    around_parts_conv = []
    around_parts_rest = []
    for st in stations_batch:
        lat, lon = st["lat"], st["lon"]
        around_parts_conv.append(f'node["shop"="convenience"](around:800,{lat},{lon});')
        around_parts_rest.append(f'node["amenity"~"restaurant|fast_food|cafe"](around:800,{lat},{lon});')

    query = f"""
[out:json][timeout:120];
(
  {"".join(around_parts_conv)}
  {"".join(around_parts_rest)}
);
out body;
"""
    result = overpass_query(query, retries=2)
    if not result:
        return {}

    elements = result.get("elements", [])

    # For each station, find nearest convenience and restaurant
    results = {}
    for st in stations_batch:
        slat, slon = st["lat"], st["lon"]
        best_conv = None
        best_rest = None
        best_conv_dist = float("inf")
        best_rest_dist = float("inf")

        for el in elements:
            elat = el.get("lat", 0)
            elon = el.get("lon", 0)
            tags = el.get("tags", {})

            # Simple distance (good enough for <1km)
            dist = ((slat - elat) ** 2 + (slon - elon) ** 2) ** 0.5

            if tags.get("shop") == "convenience" and dist < best_conv_dist:
                best_conv_dist = dist
                addr_parts = []
                for k in ["addr:province", "addr:city", "addr:quarter", "addr:neighbourhood",
                          "addr:block_number", "addr:housenumber"]:
                    v = tags.get(k, "")
                    if v:
                        addr_parts.append(v)
                best_conv = {
                    "name": tags.get("name", ""),
                    "lat": elat, "lon": elon,
                    "address": "".join(addr_parts) if addr_parts else tags.get("addr:full", ""),
                    "brand": tags.get("brand", ""),
                    "osm_id": el.get("id"),
                }

            if tags.get("amenity") in ("restaurant", "fast_food", "cafe") and dist < best_rest_dist:
                best_rest_dist = dist
                addr_parts = []
                for k in ["addr:province", "addr:city", "addr:quarter", "addr:neighbourhood",
                          "addr:block_number", "addr:housenumber"]:
                    v = tags.get(k, "")
                    if v:
                        addr_parts.append(v)
                best_rest = {
                    "name": tags.get("name", ""),
                    "lat": elat, "lon": elon,
                    "address": "".join(addr_parts) if addr_parts else tags.get("addr:full", ""),
                    "cuisine": tags.get("cuisine", ""),
                    "osm_id": el.get("id"),
                }

        results[st["osm_id"]] = {
            "nearest_convenience": best_conv,
            "nearest_restaurant": best_rest,
        }

    return results


def main():
    if not os.path.exists(STATIONS_FILE):
        print(f"ERROR: {STATIONS_FILE} not found. Run fetch_all_stations.py first.")
        sys.exit(1)

    with open(STATIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    stations = data["stations"]
    total = len(stations)
    print(f"Total stations to enrich: {total}")

    # Load progress
    progress = {}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            progress = json.load(f)

    # Load existing enriched data
    enriched = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            edata = json.load(f)
            for st in edata.get("stations", []):
                enriched[st.get("osm_id")] = st

    # Process in batches
    BATCH_SIZE = 30  # For Overpass POI queries
    WIKI_DELAY = 0.5  # seconds between Wikipedia requests

    batch = []
    for i, st in enumerate(stations):
        osm_id = st.get("osm_id")

        # Skip if already enriched
        if osm_id in enriched and enriched[osm_id].get("wikipedia_text"):
            continue

        # Wikipedia
        wiki_key = f"wiki_{osm_id}"
        if wiki_key not in progress:
            print(f"[{i+1}/{total}] Wikipedia: {st['name']}")
            wiki = get_wikipedia_extract(st["name"])
            if wiki:
                st["wikipedia_text"] = wiki["text"]
                st["wikipedia_title"] = wiki["title"]
                if wiki["image"]:
                    st["wikipedia_image"] = wiki["image"]
            progress[wiki_key] = True
            time.sleep(WIKI_DELAY)

        # Wikidata image
        wd_key = f"wd_{osm_id}"
        if wd_key not in progress and st.get("wikidata"):
            img = get_wikidata_image(st["wikidata"])
            if img:
                st["wikidata_image"] = img
            progress[wd_key] = True
            time.sleep(0.3)

        batch.append(st)

        # Process POI batch
        if len(batch) >= BATCH_SIZE or i == total - 1:
            if batch:
                print(f"  POI batch query for {len(batch)} stations...")
                poi_results = batch_nearby_pois(batch)
                for bst in batch:
                    bid = bst.get("osm_id")
                    if bid in poi_results:
                        pois = poi_results[bid]
                        bst["nearest_convenience"] = pois.get("nearest_convenience")
                        bst["nearest_restaurant"] = pois.get("nearest_restaurant")
                    enriched[bid] = bst
                batch = []
                time.sleep(2)  # Rate limit

            # Save progress periodically
            if (i + 1) % 100 == 0 or i == total - 1:
                save_enriched(enriched, stations)
                with open(PROGRESS_FILE, "w") as f:
                    json.dump(progress, f)
                print(f"  Progress saved: {i+1}/{total}")

    save_enriched(enriched, stations)
    print(f"\nDone! Enriched {len(enriched)} stations -> {OUT_FILE}")


def save_enriched(enriched, stations):
    # Merge enriched data back into station order
    out_stations = []
    for st in stations:
        oid = st.get("osm_id")
        if oid in enriched:
            out_stations.append(enriched[oid])
        else:
            out_stations.append(st)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(out_stations),
            "stations": out_stations,
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
