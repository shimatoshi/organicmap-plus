#!/usr/bin/env python3
"""
Fetch POIs for remaining stations (tram_stop + halt) not covered by initial run.
Reads transit_data.json, skips stations already in yahoo_pois.json.
"""

import json, urllib.request, urllib.parse, http.cookiejar
import re, time, sys, os, signal

DIST_KM = 1
RESULTS_PER_QUERY = 20
GENRES = [
    'コンビニ',
    'ラーメン',
    '飲食店',
    'カフェ',
    'ドラッグストア',
    'ATM',
    '銭湯 温泉',
    'スーパーマーケット',
]

SAVE_INTERVAL = 50
OUTPUT_FILE = '/home/organicmap-plus/data/transit/yahoo_pois.json'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


class YahooMapClient:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.eappid = None
        self.request_count = 0
        self._refresh_session()

    def _refresh_session(self):
        req = urllib.request.Request('https://map.yahoo.co.jp/', headers={
            'User-Agent': UA, 'Accept': 'text/html', 'Accept-Language': 'ja,en;q=0.9',
        })
        html = self.opener.open(req, timeout=15).read().decode('utf-8')
        m = re.search(r'"eappid":"([^"]+)"', html)
        if not m:
            raise RuntimeError("Failed to extract eappid")
        self.eappid = m.group(1)
        self.request_count = 0
        print(f"  [Session refreshed] eappid={self.eappid[:20]}...", flush=True)

    def search(self, query, lat, lon, dist=1, results=20):
        if self.request_count >= 500:
            time.sleep(3)
            self._refresh_session()
        params = urllib.parse.urlencode({
            'eappid': self.eappid, 'device': 'pc', 'query': query,
            'lat': str(lat), 'lon': str(lon), 'dist': str(dist), 'results': str(results),
        })
        url = f"https://map.yahoo.co.jp/proxy/search?{params}"
        req = urllib.request.Request(url, headers={
            'User-Agent': UA, 'Referer': 'https://map.yahoo.co.jp/',
            'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'ja,en;q=0.9',
        })
        self.request_count += 1
        resp = self.opener.open(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))


def extract_pois(search_result):
    pois = []
    for item in search_result.get('results', []):
        poi = {
            'name': item.get('name', ''),
            'address': item.get('address', ''),
            'lat': item.get('coordinates', {}).get('lat'),
            'lon': item.get('coordinates', {}).get('lon'),
            'category': item.get('businessCategory', {}).get('main', {}).get('name', ''),
            'category_id': item.get('businessCategory', {}).get('main', {}).get('id', ''),
            'time': item.get('time', []),
            'star': item.get('star'),
            'review': item.get('review'),
        }
        if poi['lat'] and poi['lon']:
            pois.append(poi)
    return pois


def main():
    # Load all stations
    with open('/home/organicmap-plus/data/transit/transit_data.json') as f:
        data = json.load(f)

    # Load existing POIs
    with open(OUTPUT_FILE) as f:
        results = json.load(f)

    existing_keys = set(results.keys())

    # Find missing stations (skip Russian/non-Japanese names)
    missing = []
    for s in data['stations']:
        key = f"{s['name']}_{s['lat']}_{s['lon']}"
        if key not in existing_keys:
            # Skip Russian station names
            if re.search(r'[\u0400-\u04FF]', s['name']):
                continue
            missing.append(s)

    print(f"Missing stations to fetch: {len(missing)}", flush=True)
    if not missing:
        print("Nothing to do!")
        return

    client = YahooMapClient()

    shutdown = False
    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True
        print("\nShutdown requested, saving...", flush=True)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    errors = 0
    done = 0
    for idx, station in enumerate(missing):
        if shutdown:
            break

        station_key = f"{station['name']}_{station['lat']}_{station['lon']}"
        if station_key in results:
            continue

        station_pois = {}
        for genre in GENRES:
            try:
                search_result = client.search(
                    genre, station['lat'], station['lon'],
                    dist=DIST_KM, results=RESULTS_PER_QUERY
                )
                pois = extract_pois(search_result)
                if pois:
                    station_pois[genre] = pois
                time.sleep(0.3)
                errors = 0
            except Exception as e:
                errors += 1
                print(f"  ERROR at {station['name']}/{genre}: {e}", flush=True)
                if errors >= 5:
                    print("  Too many errors, refreshing session...", flush=True)
                    time.sleep(10)
                    try:
                        client._refresh_session()
                        errors = 0
                    except:
                        print("  Refresh failed, waiting 60s...", flush=True)
                        time.sleep(60)
                        client._refresh_session()
                        errors = 0
                else:
                    time.sleep(2)

        results[station_key] = {
            'station_name': station['name'],
            'lat': station['lat'],
            'lon': station['lon'],
            'pref': station.get('pref', ''),
            'pois': station_pois
        }
        done += 1

        total_pois = sum(len(v) for v in station_pois.values())
        if done % 10 == 0 or total_pois > 50:
            print(f"  [{done}/{len(missing)}] {station['name']} ({station.get('pref','')}): "
                  f"{len(station_pois)} genres, {total_pois} POIs", flush=True)

        if done % SAVE_INTERVAL == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(results, f, ensure_ascii=False)
            print(f"  [Saved] {len(results)} total stations", flush=True)

    # Final save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False)

    print(f"\nDone! Added {done} stations, total now {len(results)}", flush=True)

    total_pois = sum(
        sum(len(pois) for pois in v['pois'].values())
        for v in results.values()
    )
    print(f"Total POIs: {total_pois}", flush=True)


if __name__ == '__main__':
    main()
