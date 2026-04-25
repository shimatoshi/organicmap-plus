#!/usr/bin/env python3
"""
全データを統合して最終的な transit_data.json を生成

入力:
- overpass_raw/stations_*.json  (駅の基本データ)
- overpass_raw/lines_*.json     (路線データ)
- wiki_stations.json            (Wikipedia説明+画��)
- bus_stops.json                (��ス停+バス路線)
- station_images.json           (駅写真 - あれば)
- station_photos_google.json    (Google画像 - あれば)

出力:
- transit_data.json             (統合データ)
"""
import json, os, glob, time, math

BASE = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def haversine(lat1, lon1, lat2, lon2):
    """Distance in meters between two points"""
    R = 6371000
    p = math.pi / 180
    a = 0.5 - math.cos((lat2-lat1)*p)/2 + math.cos(lat1*p)*math.cos(lat2*p) * (0.5 - math.cos((lon2-lon1)*p)/2)
    return 2 * R * math.asin(math.sqrt(a))

def assign_prefecture(lat, lon):
    """Rough prefecture assignment based on coordinates"""
    # Simplified bounding box approach
    prefs = [
        ("北海道", 41.3, 139.2, 45.6, 145.9),
        ("青森県", 40.2, 139.4, 41.5, 141.7),
        ("岩手県", 38.7, 139.0, 40.4, 142.1),
        ("宮城県", 37.8, 140.2, 39.0, 141.7),
        ("秋田県", 39.0, 139.5, 40.5, 140.6),
        ("山形県", 37.7, 139.5, 39.2, 140.7),
        ("福島県", 36.8, 139.2, 37.9, 141.1),
        ("茨城県", 35.7, 139.7, 36.9, 140.9),
        ("栃木県", 36.2, 139.3, 37.2, 140.3),
        ("群馬県", 36.0, 138.5, 37.1, 139.7),
        ("埼玉県", 35.7, 138.7, 36.3, 139.9),
        ("千葉県", 34.9, 139.7, 36.0, 140.9),
        ("東京都", 35.5, 138.9, 35.9, 139.9),
        ("神奈川県", 35.1, 138.9, 35.7, 139.8),
        ("新潟県", 36.7, 137.8, 38.6, 140.1),
        ("富山県", 36.3, 136.7, 37.0, 137.8),
        ("石川県", 36.1, 136.2, 37.9, 137.4),
        ("福井県", 35.5, 135.5, 36.3, 136.9),
        ("山梨県", 35.2, 138.2, 35.9, 139.1),
        ("長野県", 35.2, 137.3, 37.1, 138.8),
        ("岐阜県", 35.1, 136.3, 36.5, 137.7),
        ("静岡県", 34.6, 137.5, 35.6, 139.2),
        ("愛知県", 34.6, 136.7, 35.4, 137.7),
        ("三重県", 33.7, 135.8, 35.2, 137.0),
        ("滋賀県", 34.8, 135.8, 35.6, 136.5),
        ("京都府", 34.8, 135.0, 35.8, 136.1),
        ("大阪府", 34.3, 135.1, 35.0, 135.8),
        ("兵庫県", 34.2, 134.2, 35.7, 135.5),
        ("奈良県", 34.0, 135.6, 34.8, 136.2),
        ("和歌山県", 33.4, 135.0, 34.4, 136.0),
        ("鳥取県", 35.1, 133.2, 35.7, 134.5),
        ("島根県", 34.3, 131.7, 35.6, 133.4),
        ("岡山県", 34.4, 133.3, 35.4, 134.4),
        ("広島県", 34.0, 132.0, 35.0, 133.5),
        ("山口県", 33.7, 130.8, 34.8, 132.2),
        ("徳島県", 33.7, 134.0, 34.3, 134.8),
        ("香川県", 34.0, 133.5, 34.6, 134.4),
        ("愛媛県", 33.0, 132.0, 34.0, 133.7),
        ("高知県", 32.7, 132.5, 33.9, 134.3),
        ("福岡県", 33.0, 130.0, 33.9, 131.2),
        ("佐賀県", 33.0, 129.7, 33.6, 130.5),
        ("長崎県", 32.5, 128.6, 34.7, 130.3),
        ("熊本県", 32.1, 130.1, 33.3, 131.3),
        ("大分県", 32.7, 130.8, 33.7, 132.1),
        ("宮崎県", 31.4, 130.7, 32.9, 131.9),
        ("鹿児島県", 27.0, 128.3, 32.4, 131.2),
        ("沖縄県", 24.0, 122.9, 27.9, 131.3),
    ]
    best = None
    best_dist = float("inf")
    for pname, s, w, n, e in prefs:
        clat = (s + n) / 2
        clon = (w + e) / 2
        if s <= lat <= n and w <= lon <= e:
            d = haversine(lat, lon, clat, clon)
            if d < best_dist:
                best_dist = d
                best = pname
    if not best:
        # Find nearest
        for pname, s, w, n, e in prefs:
            clat = (s + n) / 2
            clon = (w + e) / 2
            d = haversine(lat, lon, clat, clon)
            if d < best_dist:
                best_dist = d
                best = pname
    return best


def main():
    print("=== Merging all transit data ===")

    # 1. Load stations from overpass_raw
    raw_dir = os.path.join(BASE, "overpass_raw")
    all_elements = []
    for f in sorted(glob.glob(os.path.join(raw_dir, "stations_*.json"))):
        try:
            data = json.load(open(f))
            els = data.get("elements", [])
            all_elements.extend(els)
            print(f"  {os.path.basename(f)}: {len(els)}")
        except Exception as e:
            print(f"  {os.path.basename(f)}: ERROR {e}")

    print(f"Total raw station elements: {len(all_elements)}")

    # Deduplicate stations by OSM ID (not by name+location)
    stations = []
    seen = set()
    for el in all_elements:
        tags = el.get("tags", {})
        name = tags.get("name", "")
        lat = el.get("lat")
        lon = el.get("lon")
        if not name or not lat or not lon:
            continue
        osm_id = el.get("id")
        if osm_id in seen:
            continue
        seen.add(osm_id)
        stations.append({
            "name": name,
            "name_en": tags.get("name:en", ""),
            "lat": lat,
            "lon": lon,
            "osm_id": el.get("id"),
            "operator": tags.get("operator", ""),
            "railway": tags.get("railway", "station"),
            "wikidata": tags.get("wikidata", ""),
            "wikipedia_tag": tags.get("wikipedia", ""),
            "lines": [],
            "pref": "",
        })

    print(f"Unique stations: {len(stations)}")

    # Assign prefectures
    for st in stations:
        st["pref"] = assign_prefecture(st["lat"], st["lon"])

    # 2. Load lines and assign to stations
    station_lines_map = {}  # osm_id -> [line names]
    all_lines = []
    for f in sorted(glob.glob(os.path.join(raw_dir, "lines_*.json"))):
        try:
            data = json.load(open(f))
            for el in data.get("elements", []):
                tags = el.get("tags", {})
                name = tags.get("name", tags.get("ref", ""))
                if not name:
                    continue
                all_lines.append({
                    "name": name,
                    "name_en": tags.get("name:en", ""),
                    "operator": tags.get("operator", ""),
                    "route": tags.get("route", "train"),
                    "colour": tags.get("colour", ""),
                    "osm_id": el.get("id"),
                })
                for member in el.get("members", []):
                    if member.get("type") == "node" and member.get("role") in ("stop", "station", ""):
                        nid = member.get("ref")
                        if nid:
                            station_lines_map.setdefault(nid, set()).add(name)
        except:
            pass

    # Deduplicate lines
    seen_lines = set()
    unique_lines = []
    for l in all_lines:
        if l["name"] not in seen_lines:
            seen_lines.add(l["name"])
            unique_lines.append(l)
    print(f"Rail lines: {len(unique_lines)}")

    # Assign lines to stations
    for st in stations:
        oid = st.get("osm_id")
        if oid in station_lines_map:
            st["lines"] = sorted(station_lines_map[oid])

    # 3. Load Wikipedia data
    wiki_data = load_json(os.path.join(BASE, "wiki_stations.json"))
    wiki_map = {}
    if wiki_data:
        wiki_stations = wiki_data.get("stations", {})
        # Build lookup by name
        for title, info in wiki_stations.items():
            # Try matching by station name
            clean_name = title.replace("駅", "").strip()
            wiki_map[title] = info
            wiki_map[clean_name + "駅"] = info
            wiki_map[clean_name] = info
        print(f"Wikipedia entries: {len(wiki_stations)}")

    # Match Wikipedia to stations
    wiki_matched = 0
    for st in stations:
        name = st["name"]
        # Try various name forms
        for try_name in [name, name + "駅", name.replace("駅", "") + "駅"]:
            if try_name in wiki_map:
                info = wiki_map[try_name]
                st["wikipedia_text"] = info.get("extract", "")
                st["wikipedia_image"] = info.get("image_url", "")
                st["wikidata_id"] = info.get("wikidata_id", st.get("wikidata", ""))
                wiki_matched += 1
                break
    print(f"Wikipedia matched: {wiki_matched}/{len(stations)}")

    # 4. Load bus stops
    bus_data = load_json(os.path.join(BASE, "bus_stops.json"))
    bus_stops = []
    bus_routes = []
    if bus_data:
        bus_stops = bus_data.get("bus_stops", {}).get("data", [])
        bus_routes = bus_data.get("bus_routes", {}).get("data", [])
        print(f"Bus stops: {len(bus_stops)}, Routes: {len(bus_routes)}")

    # Find nearby bus stops for each station (within 500m)
    if bus_stops:
        print("Matching bus stops to stations...")
        # Build spatial index (simple grid)
        grid = {}
        for bs in bus_stops:
            gk = f"{round(bs['lat'],1)}_{round(bs['lon'],1)}"
            grid.setdefault(gk, []).append(bs)

        for si, st in enumerate(stations):
            slat, slon = st["lat"], st["lon"]
            nearby = []
            # Check neighboring grid cells
            for dlat in [-0.1, 0, 0.1]:
                for dlon in [-0.1, 0, 0.1]:
                    gk = f"{round(slat+dlat,1)}_{round(slon+dlon,1)}"
                    for bs in grid.get(gk, []):
                        d = haversine(slat, slon, bs["lat"], bs["lon"])
                        if d < 500:
                            nearby.append({
                                "name": bs["name"],
                                "lat": bs["lat"],
                                "lon": bs["lon"],
                                "distance_m": round(d),
                                "operator": bs.get("operator", ""),
                            })
            if nearby:
                nearby.sort(key=lambda x: x["distance_m"])
                st["nearby_bus_stops"] = nearby[:5]  # Top 5 nearest

            if (si + 1) % 1000 == 0:
                print(f"  {si+1}/{len(stations)}")

    # 5. Sort by prefecture then name
    pref_order = [
        "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
        "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
        "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
        "岐阜県", "静岡県", "愛知県", "三重県",
        "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
        "鳥取県", "島根県", "岡山県", "広島県", "山口県",
        "徳島県", "香川県", "愛媛県", "高知県",
        "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
    ]
    pref_idx = {p: i for i, p in enumerate(pref_order)}
    stations.sort(key=lambda s: (pref_idx.get(s["pref"], 99), s["name"]))

    # Stats
    pref_counts = {}
    for st in stations:
        pref_counts[st["pref"]] = pref_counts.get(st["pref"], 0) + 1

    print("\n=== Prefecture distribution ===")
    for p in pref_order:
        if p in pref_counts:
            print(f"  {p}: {pref_counts[p]}")

    has_wiki = sum(1 for s in stations if s.get("wikipedia_text"))
    has_lines = sum(1 for s in stations if s.get("lines"))
    has_bus = sum(1 for s in stations if s.get("nearby_bus_stops"))

    # Output
    output = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": {
            "total_stations": len(stations),
            "total_lines": len(unique_lines),
            "total_bus_stops": len(bus_stops),
            "total_bus_routes": len(bus_routes),
            "stations_with_wikipedia": has_wiki,
            "stations_with_lines": has_lines,
            "stations_with_bus_stops": has_bus,
            "prefectures": len(pref_counts),
        },
        "rail_lines": unique_lines,
        "stations": stations,
    }

    outpath = os.path.join(BASE, "transit_data.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n=== Output ===")
    print(f"Saved to {outpath}")
    print(f"Stations: {len(stations)}")
    print(f"Lines: {len(unique_lines)}")
    print(f"With Wikipedia: {has_wiki}")
    print(f"With lines: {has_lines}")
    print(f"With bus: {has_bus}")


if __name__ == "__main__":
    main()
