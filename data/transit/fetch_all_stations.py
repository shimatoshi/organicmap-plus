#!/usr/bin/env python3
"""
Phase 1: 国土数値情報 + Overpass API から全鉄道駅データを取得
出力: all_stations.json
"""
import json, time, sys, os, subprocess

OUT = os.path.join(os.path.dirname(__file__), "all_stations.json")

def overpass_query(query, retries=3):
    """Use curl for reliability — urllib gets 406/504 from Overpass"""
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "180",
                 "--data-urlencode", f"data={query}",
                 "https://overpass-api.de/api/interpreter"],
                capture_output=True, text=True, timeout=200
            )
            if result.returncode == 0 and result.stdout.strip().startswith("{"):
                return json.loads(result.stdout)
            else:
                print(f"  Overpass attempt {attempt+1}: curl exit={result.returncode}, body={result.stdout[:100]}", file=sys.stderr)
        except Exception as e:
            print(f"  Overpass attempt {attempt+1} failed: {e}", file=sys.stderr)
        if attempt < retries - 1:
            time.sleep(30 * (attempt + 1))
    return None

print("=== Fetching all railway stations in Japan from Overpass ===")

# Get all railway stations in Japan using bbox (24-46N, 122-154E)
# Split into regions to avoid timeout
REGIONS = [
    ("hokkaido", 41.5, 139.0, 46.0, 146.0),
    ("tohoku", 37.5, 138.5, 41.5, 142.0),
    ("kanto", 34.5, 138.5, 37.5, 141.0),
    ("chubu", 34.5, 135.5, 38.0, 139.0),
    ("kinki", 33.5, 134.0, 36.0, 136.5),
    ("chugoku", 33.5, 130.5, 36.0, 134.5),
    ("shikoku", 32.5, 132.0, 34.5, 134.5),
    ("kyushu", 30.5, 129.0, 34.0, 132.5),
    ("okinawa", 24.0, 122.0, 28.0, 132.0),
]

all_elements = []
for region_name, south, west, north, east in REGIONS:
    print(f"  Fetching {region_name}...")
    query = f"""
[out:json][timeout:120];
(
  node["railway"="station"]["name"]({south},{west},{north},{east});
  node["railway"="halt"]["name"]({south},{west},{north},{east});
);
out body;
"""
    result = overpass_query(query)
    if result:
        els = result.get("elements", [])
        all_elements.extend(els)
        print(f"    {region_name}: {len(els)} elements")
    else:
        print(f"    WARNING: {region_name} failed")
    time.sleep(5)  # Rate limit between requests

result = {"elements": all_elements}
print(f"Total elements from all regions: {len(all_elements)}")

elements = all_elements
if not elements:
    print("FATAL: No stations fetched from any region", file=sys.stderr)
    sys.exit(1)
print(f"Raw elements: {len(elements)}")

# Parse stations
stations = []
seen = set()
for el in elements:
    name = el.get("tags", {}).get("name", "")
    lat = el.get("lat")
    lon = el.get("lon")
    if not name or not lat or not lon:
        continue

    # Deduplicate by name + rough location (0.01 degree ~ 1km)
    key = f"{name}_{round(lat,2)}_{round(lon,2)}"
    if key in seen:
        continue
    seen.add(key)

    tags = el.get("tags", {})
    station = {
        "name": name,
        "name_en": tags.get("name:en", ""),
        "lat": lat,
        "lon": lon,
        "osm_id": el.get("id"),
        "operator": tags.get("operator", ""),
        "railway": tags.get("railway", "station"),
        "lines": [],  # will be filled later
        "wikidata": tags.get("wikidata", ""),
        "wikipedia": tags.get("wikipedia", ""),
    }
    stations.append(station)

print(f"Unique stations: {len(stations)}")

# Sort by prefecture assignment will happen later; sort by lat desc for now
stations.sort(key=lambda s: (-s["lat"], s["lon"]))

output = {
    "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    "count": len(stations),
    "stations": stations
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Saved to {OUT}")
