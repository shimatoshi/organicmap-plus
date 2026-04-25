#!/usr/bin/env python3
"""
Fetch POIs around all stations using Yahoo Maps internal proxy API.

Usage: python3 fetch_yahoo_pois.py [--resume] [--dist 1] [--results 20]

Workflow:
1. Get session cookies + eappid from map.yahoo.co.jp
2. For each station, query each genre within dist km
3. Save results incrementally to yahoo_pois.json
"""

import json, urllib.request, urllib.parse, http.cookiejar
import re, time, sys, os, signal

# Config
DIST_KM = 1  # search radius in km
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

SAVE_INTERVAL = 50  # save every N stations
OUTPUT_FILE = '/home/organicmap-plus/data/transit/yahoo_pois.json'
PROGRESS_FILE = '/home/organicmap-plus/data/transit/yahoo_pois_progress.json'

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


class YahooMapClient:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.eappid = None
        self.request_count = 0
        self._refresh_session()
    
    def _refresh_session(self):
        """Get fresh cookies and eappid"""
        req = urllib.request.Request('https://map.yahoo.co.jp/', headers={
            'User-Agent': UA,
            'Accept': 'text/html',
            'Accept-Language': 'ja,en;q=0.9',
        })
        html = self.opener.open(req, timeout=15).read().decode('utf-8')
        m = re.search(r'"eappid":"([^"]+)"', html)
        if not m:
            raise RuntimeError("Failed to extract eappid")
        self.eappid = m.group(1)
        self.request_count = 0
        print(f"  [Session refreshed] eappid={self.eappid[:20]}...", flush=True)
    
    def search(self, query, lat, lon, dist=1, results=20):
        """Search for POIs near a location"""
        # Refresh session every 500 requests
        if self.request_count >= 500:
            time.sleep(3)
            self._refresh_session()
        
        params = urllib.parse.urlencode({
            'eappid': self.eappid,
            'device': 'pc',
            'query': query,
            'lat': str(lat),
            'lon': str(lon),
            'dist': str(dist),
            'results': str(results),
        })
        
        url = f"https://map.yahoo.co.jp/proxy/search?{params}"
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Referer': 'https://map.yahoo.co.jp/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ja,en;q=0.9',
        })
        
        self.request_count += 1
        resp = self.opener.open(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))


def extract_pois(search_result):
    """Extract relevant POI data from search result"""
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
    # Parse args
    resume = '--resume' in sys.argv
    
    # Load stations
    with open('/home/organicmap-plus/data/transit/transit_data.json') as f:
        data = json.load(f)
    
    # Only process railway stations (not tram_stop for now)
    stations = [s for s in data['stations'] if s.get('railway') == 'station']
    print(f"Total stations to process: {len(stations)}", flush=True)
    
    # Load existing progress
    results = {}
    start_idx = 0
    if resume and os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            results = json.load(f)
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE) as f:
                progress = json.load(f)
                start_idx = progress.get('last_idx', 0) + 1
        print(f"Resuming from station {start_idx}, {len(results)} stations already done", flush=True)
    
    # Setup client
    client = YahooMapClient()
    
    # Signal handler for graceful shutdown
    shutdown = False
    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True
        print("\nShutdown requested, saving progress...", flush=True)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    errors = 0
    for idx in range(start_idx, len(stations)):
        if shutdown:
            break
        
        station = stations[idx]
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
                time.sleep(0.3)  # rate limit
                errors = 0  # reset error counter on success
            except Exception as e:
                errors += 1
                print(f"  ERROR at {station['name']}/{genre}: {e}", flush=True)
                if errors >= 5:
                    print("  Too many consecutive errors, refreshing session...", flush=True)
                    time.sleep(10)
                    try:
                        client._refresh_session()
                        errors = 0
                    except:
                        print("  Session refresh failed, waiting 60s...", flush=True)
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
        
        # Progress report
        total_pois = sum(len(v) for v in station_pois.values())
        if (idx - start_idx) % 10 == 0 or total_pois > 50:
            print(f"  [{idx+1}/{len(stations)}] {station['name']}: "
                  f"{len(station_pois)} genres, {total_pois} POIs", flush=True)
        
        # Save periodically
        if (idx - start_idx + 1) % SAVE_INTERVAL == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(results, f, ensure_ascii=False)
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({'last_idx': idx, 'total': len(stations)}, f)
            print(f"  [Saved] {len(results)} stations done", flush=True)
    
    # Final save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({'last_idx': idx if not shutdown else idx - 1, 'total': len(stations)}, f)
    
    print(f"\nDone! {len(results)} stations processed", flush=True)
    
    # Stats
    total_pois = sum(
        sum(len(pois) for pois in v['pois'].values())
        for v in results.values()
    )
    print(f"Total POIs collected: {total_pois}", flush=True)
    genre_counts = {}
    for v in results.values():
        for genre, pois in v['pois'].items():
            genre_counts[genre] = genre_counts.get(genre, 0) + len(pois)
    for g, c in sorted(genre_counts.items(), key=lambda x: -x[1]):
        print(f"  {g}: {c}", flush=True)


if __name__ == '__main__':
    main()
