#!/usr/bin/env python3
"""Overpass APIで stations.json に lat/lon と osm_id を補完する。
全駅をバッチで一括クエリ→県の bbox で判別して紐付け。
"""
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "stations.json"
OVERPASS = "https://overpass-api.de/api/interpreter"

# 都道府県 bbox (south, west, north, east)
PREF_BBOX = {
    "北海道":     (41.35, 139.33, 45.55, 148.90),
    "青森県":     (40.21, 139.49, 41.56, 141.68),
    "岩手県":     (38.74, 140.65, 40.45, 142.07),
    "宮城県":     (37.77, 140.27, 39.00, 141.68),
    "秋田県":     (38.87, 139.69, 40.51, 140.99),
    "山形県":     (37.73, 139.52, 39.21, 140.64),
    "福島県":     (36.79, 139.16, 38.00, 141.05),
    "茨城県":     (35.74, 139.69, 36.95, 140.87),
    "栃木県":     (36.20, 139.32, 37.16, 140.30),
    "群馬県":     (35.99, 138.40, 37.10, 139.69),
    "埼玉県":     (35.74, 138.71, 36.29, 139.91),
    "千葉県":     (34.89, 139.74, 36.10, 140.87),
    "東京都":     (24.22, 136.06, 35.90, 153.99),
    "神奈川県":   (35.13, 138.91, 35.67, 139.79),
    "新潟県":     (36.71, 137.62, 38.55, 139.83),
    "富山県":     (36.27, 136.77, 36.98, 137.77),
    "石川県":     (36.07, 136.25, 37.86, 137.36),
    "福井県":     (35.34, 135.45, 36.29, 136.83),
    "山梨県":     (35.16, 138.20, 35.97, 139.13),
    "長野県":     (35.20, 137.32, 37.03, 138.74),
    "岐阜県":     (35.13, 136.27, 36.46, 137.66),
    "静岡県":     (34.58, 137.46, 35.65, 139.20),
    "愛知県":     (34.57, 136.67, 35.42, 137.84),
    "三重県":     (33.72, 135.85, 35.26, 136.99),
    "滋賀県":     (34.79, 135.77, 35.71, 136.45),
    "京都府":     (34.70, 134.85, 35.78, 136.06),
    "大阪府":     (34.27, 135.09, 35.05, 135.74),
    "兵庫県":     (34.15, 134.25, 35.67, 135.47),
    "奈良県":     (33.86, 135.69, 34.78, 136.23),
    "和歌山県":   (33.42, 135.00, 34.39, 136.02),
    "鳥取県":     (35.06, 133.13, 35.61, 134.53),
    "島根県":     (34.30, 131.66, 36.36, 133.42),
    "岡山県":     (34.30, 133.27, 35.36, 134.43),
    "広島県":     (34.02, 132.04, 35.10, 133.48),
    "山口県":     (33.71, 130.77, 34.79, 132.42),
    "徳島県":     (33.54, 133.66, 34.27, 134.81),
    "香川県":     (34.00, 133.45, 34.59, 134.45),
    "愛媛県":     (32.89, 132.00, 34.31, 133.69),
    "高知県":     (32.70, 132.48, 33.88, 134.32),
    "福岡県":     (33.10, 130.05, 34.27, 131.18),
    "佐賀県":     (32.95, 129.74, 33.62, 130.55),
    "長崎県":     (32.55, 128.59, 34.73, 130.45),
    "熊本県":     (32.09, 129.99, 33.22, 131.34),
    "大分県":     (32.71, 130.81, 33.74, 132.07),
    "宮崎県":     (31.36, 130.71, 32.84, 131.88),
    "鹿児島県":   (27.02, 128.40, 32.21, 131.18),
    "沖縄県":     (24.04, 122.93, 27.88, 131.33),
}

def in_bbox(lat, lon, bbox):
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e

def query_all(names: list[str]) -> list[dict]:
    """全駅名を一括クエリ。"""
    parts = []
    for n in names:
        base = n.rstrip("駅")
        parts.append(f'  node["railway"="station"]["name"="{base}"];')
        parts.append(f'  node["railway"="station"]["name"="{base}駅"];')
    q = "[out:json][timeout:300];\n(\n" + "\n".join(parts) + "\n);\nout;"
    print(f"Query size: {len(q)} chars, {len(names)} stations")
    data = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request(OVERPASS, data=data)
    with urllib.request.urlopen(req, timeout=360) as r:
        return json.loads(r.read())["elements"]

def main():
    doc = json.loads(DATA.read_text())
    stations = doc["stations"]
    pending = [s for s in stations if "lat" not in s]
    print(f"Pending: {len(pending)} / {len(stations)}")

    if not pending:
        print("All stations enriched.")
        return

    elems = query_all([s["name"] for s in pending])
    print(f"Got {len(elems)} OSM nodes")

    # 駅名→候補ノード辞書
    by_name = {}
    for e in elems:
        nm = e.get("tags", {}).get("name", "").rstrip("駅")
        by_name.setdefault(nm, []).append(e)

    misses = []
    for s in pending:
        base = s["name"].rstrip("駅")
        cands = by_name.get(base, [])
        if not cands:
            misses.append(s)
            print(f"  MISS {s['pref']} {s['name']}")
            continue
        bbox = PREF_BBOX[s["pref"]]
        in_pref = [c for c in cands if in_bbox(c["lat"], c["lon"], bbox)]
        if not in_pref:
            print(f"  WARN {s['pref']} {s['name']}: {len(cands)} cands but none in bbox")
            in_pref = cands
        e = in_pref[0]
        s["lat"] = e["lat"]
        s["lon"] = e["lon"]
        s["osm_id"] = e["id"]
        print(f"  OK   {s['pref']} {s['name']}: ({e['lat']:.4f}, {e['lon']:.4f})")

    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(f"\n--- Done. Misses: {len(misses)} ---")
    for m in misses:
        print(f"  {m['pref']} {m['name']}")

if __name__ == "__main__":
    main()
