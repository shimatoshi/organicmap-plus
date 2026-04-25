#!/usr/bin/env python3
"""
各駅の最寄りコンビニ・飲食店をOverpass APIで取���
transit_data.json を読み込んで enriched_transit.json を出力

バッチクエリ: 10駅ずつまとめて1クエリ
"""
import json, time, sys, os, subprocess, math

BASE = os.path.dirname(os.path.abspath(__file__))
INPUT = os.path.join(BASE, "transit_data.json")
OUT = os.path.join(BASE, "enriched_transit.json")
PROGRESS = os.path.join(BASE, ".poi_progress.json")

def overpass_curl(query, timeout=120):
    """Use curl for Overpass queries"""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout),
             "--data-urlencode", f"data={query}",
             "https://overpass-api.de/api/interpreter"],
            capture_output=True, text=True, timeout=timeout + 30
        )
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            return json.loads(result.stdout)
    except:
        pass
    return None

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p = math.pi / 180
    a = 0.5 - math.cos((lat2-lat1)*p)/2 + math.cos(lat1*p)*math.cos(lat2*p)*(0.5-math.cos((lon2-lon1)*p)/2)
    return 2 * R * math.asin(math.sqrt(a))

def batch_poi_query(stations_batch, radius=800):
    """Query convenience stores and restaurants near a batch of stations"""
    if not stations_batch:
        return {}

    # Build union query
    parts = []
    for st in stations_batch:
        lat, lon = st["lat"], st["lon"]
        parts.append(f'node["shop"="convenience"](around:{radius},{lat},{lon});')
        parts.append(f'node["amenity"~"restaurant|fast_food|cafe"](around:{radius},{lat},{lon});')

    query = f'[out:json][timeout:90];({"".join(parts)});out body;'
    result = overpass_curl(query)
    if not result:
        return {}

    elements = result.get("elements", [])

    # Match to each station
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
            dist = haversine(slat, slon, elat, elon)

            if dist > radius:
                continue

            # Build address
            addr_parts = []
            for k in ["addr:province", "addr:city", "addr:quarter", "addr:neighbourhood",
                       "addr:block_number", "addr:housenumber"]:
                v = tags.get(k, "")
                if v:
                    addr_parts.append(v)
            address = "".join(addr_parts) if addr_parts else tags.get("addr:full", "")

            if tags.get("shop") == "convenience" and dist < best_conv_dist:
                best_conv_dist = dist
                best_conv = {
                    "name": tags.get("name", tags.get("brand", "")),
                    "lat": elat, "lon": elon,
                    "address": address,
                    "brand": tags.get("brand", ""),
                    "distance_m": round(dist),
                }

            if tags.get("amenity") in ("restaurant", "fast_food", "cafe") and dist < best_rest_dist:
                best_rest_dist = dist
                best_rest = {
                    "name": tags.get("name", ""),
                    "lat": elat, "lon": elon,
                    "address": address,
                    "cuisine": tags.get("cuisine", ""),
                    "distance_m": round(dist),
                }

        results[st["osm_id"]] = {
            "nearest_convenience": best_conv,
            "nearest_restaurant": best_rest,
        }

    return results


def main():
    if not os.path.exists(INPUT):
        print(f"ERROR: {INPUT} not found. Run merge_all.py first.")
        sys.exit(1)

    with open(INPUT, "r", encoding="utf-8") as f:
        data = json.load(f)

    stations = data["stations"]
    total = len(stations)
    print(f"Enriching {total} stations with nearby POIs")

    # Load progress
    done_ids = set()
    if os.path.exists(PROGRESS):
        with open(PROGRESS) as f:
            done_ids = set(json.load(f))

    BATCH_SIZE = 5  # Smaller batch to avoid Overpass timeout
    batch = []
    processed = 0

    for i, st in enumerate(stations):
        if st.get("osm_id") in done_ids:
            continue
        batch.append(st)

        if len(batch) >= BATCH_SIZE or i == total - 1:
            print(f"[{i+1}/{total}] Querying POIs for {len(batch)} stations...", flush=True)
            results = batch_poi_query(batch)

            if results:
                for bst in batch:
                    oid = bst.get("osm_id")
                    if oid in results:
                        bst["nearest_convenience"] = results[oid]["nearest_convenience"]
                        bst["nearest_restaurant"] = results[oid]["nearest_restaurant"]
                        done_ids.add(oid)
            else:
                print(f"  WARNING: batch query returned empty, retrying individually...", flush=True)
                for bst in batch:
                    # Individual fallback with smaller radius
                    sq = f'[out:json][timeout:20];(node["shop"="convenience"](around:500,{bst["lat"]},{bst["lon"]});node["amenity"~"restaurant|fast_food|cafe"](around:500,{bst["lat"]},{bst["lon"]}););out body 1;'
                    r = overpass_curl(sq, timeout=30)
                    if r:
                        els = r.get("elements", [])
                        conv = None
                        rest = None
                        for el in els:
                            tags = el.get("tags", {})
                            if tags.get("shop") == "convenience" and not conv:
                                conv = {"name": tags.get("name", tags.get("brand", "")), "lat": el["lat"], "lon": el["lon"]}
                            if tags.get("amenity") in ("restaurant", "fast_food", "cafe") and not rest:
                                rest = {"name": tags.get("name", ""), "lat": el["lat"], "lon": el["lon"]}
                        bst["nearest_convenience"] = conv
                        bst["nearest_restaurant"] = rest
                        done_ids.add(bst["osm_id"])
                    time.sleep(3)

            batch = []
            processed += BATCH_SIZE
            time.sleep(8)  # Rate limit - increased

            # Save progress
            if processed % 100 == 0 or i == total - 1:
                with open(PROGRESS, "w") as f:
                    json.dump(list(done_ids), f)

                # Save enriched data
                data["stations"] = stations
                data["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                with open(OUT, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"  Saved progress: {len(done_ids)}/{total}")

    # Final save
    data["stations"] = stations
    data["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # Update stats
    has_conv = sum(1 for s in stations if s.get("nearest_convenience"))
    has_rest = sum(1 for s in stations if s.get("nearest_restaurant"))
    data["stats"]["stations_with_convenience"] = has_conv
    data["stats"]["stations_with_restaurant"] = has_rest

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nDone!")
    print(f"With convenience store: {has_conv}/{total}")
    print(f"With restaurant: {has_rest}/{total}")
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
