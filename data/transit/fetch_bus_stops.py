#!/usr/bin/env python3
"""
Phase 4: バス停データ取得 - Overpass API
各駅の周辺バス停 + 主要バス路線
出力: bus_stops.json
"""
import json, urllib.request, urllib.parse, time, sys, os

BASE = os.path.dirname(__file__)
OUT = os.path.join(BASE, "bus_stops.json")

def overpass_query(query, retries=3):
    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data, headers={"User-Agent": "OrganicMapPlus/1.0"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  Overpass attempt {attempt+1} failed: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(30 * (attempt + 1))
    return None

# Get bus stops in Japan by region to avoid timeout
print("=== Fetching bus stops in Japan (by region) ===")

REGIONS = [
    ("hokkaido", 41.5, 139.0, 46.0, 146.0),
    ("tohoku", 37.5, 138.5, 41.5, 142.0),
    ("kanto", 34.5, 138.5, 37.5, 141.0),
    ("chubu", 34.5, 135.5, 38.0, 139.0),
    ("kinki", 33.5, 134.0, 36.0, 136.5),
    ("chugoku_shikoku", 32.5, 130.5, 36.0, 134.5),
    ("kyushu_okinawa", 24.0, 129.0, 34.0, 132.5),
]

elements = []
for region_name, south, west, north, east in REGIONS:
    print(f"  Fetching {region_name}...")
    query = f"""
[out:json][timeout:180];
(
  node["highway"="bus_stop"]["name"]({south},{west},{north},{east});
  node["public_transport"="platform"]["bus"="yes"]["name"]({south},{west},{north},{east});
);
out body;
"""
    result = overpass_query(query)
    if result:
        els = result.get("elements", [])
        elements.extend(els)
        print(f"    {region_name}: {len(els)} stops")
    else:
        print(f"    WARNING: {region_name} failed")
    time.sleep(8)  # Rate limit

print(f"Raw bus stop elements: {len(elements)}")

# Parse and deduplicate
stops = []
seen = set()
for el in elements:
    tags = el.get("tags", {})
    name = tags.get("name", "")
    lat = el.get("lat")
    lon = el.get("lon")
    if not name or not lat or not lon:
        continue

    key = f"{name}_{round(lat,3)}_{round(lon,3)}"
    if key in seen:
        continue
    seen.add(key)

    stops.append({
        "name": name,
        "lat": lat,
        "lon": lon,
        "osm_id": el.get("id"),
        "operator": tags.get("operator", ""),
        "network": tags.get("network", ""),
        "route_ref": tags.get("route_ref", ""),
    })

print(f"Unique bus stops: {len(stops)}")

# Also fetch bus routes (by region)
print("\n=== Fetching bus routes ===")
route_elements = []
for region_name, south, west, north, east in REGIONS:
    print(f"  Bus routes: {region_name}...")
    query_routes = f"""
[out:json][timeout:120];
relation["route"="bus"]["name"]({south},{west},{north},{east});
out tags;
"""
    route_result = overpass_query(query_routes)
    if route_result:
        route_elements.extend(route_result.get("elements", []))
    time.sleep(8)

route_result = {"elements": route_elements} if route_elements else None
routes = []
if route_result:
    for el in route_result.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name", "")
        if name:
            routes.append({
                "name": name,
                "operator": tags.get("operator", ""),
                "network": tags.get("network", ""),
                "from": tags.get("from", ""),
                "to": tags.get("to", ""),
                "osm_id": el.get("id"),
            })
    print(f"Bus routes: {len(routes)}")

output = {
    "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    "bus_stops": {"count": len(stops), "data": stops},
    "bus_routes": {"count": len(routes), "data": routes},
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nSaved to {OUT}")
print(f"Bus stops: {len(stops)}, Routes: {len(routes)}")
