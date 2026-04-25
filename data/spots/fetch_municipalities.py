#!/usr/bin/env python3
"""Fetch all Japanese municipalities by prefecture from Wikipedia API."""
import json, urllib.request, urllib.parse, re, time

PREF_LIST = [
    "北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県",
    "茨城県","栃木県","群馬県","埼玉県","千葉県","東京都","神奈川県",
    "新潟県","富山県","石川県","福井県","山梨県","長野県","岐阜県",
    "静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県",
    "奈良県","和歌山県","鳥取県","島根県","岡山県","広島県","山口県",
    "徳島県","香川県","愛媛県","高知県","福岡県","佐賀県","長崎県",
    "熊本県","大分県","宮崎県","鹿児島県","沖縄県"
]

# Area mapping
AREA_MAP = {
    "北海道":"北海道",
    "青森県":"東北","岩手県":"東北","宮城県":"東北","秋田県":"東北","山形県":"東北","福島県":"東北",
    "茨城県":"関東","栃木県":"関東","群馬県":"関東","埼玉県":"関東","千葉県":"関東","東京都":"関東","神奈川県":"関東",
    "新潟県":"中部","富山県":"中部","石川県":"中部","福井県":"中部","山梨県":"中部","長野県":"中部","岐阜県":"中部","静岡県":"中部","愛知県":"中部",
    "三重県":"近畿","滋賀県":"近畿","京都府":"近畿","大阪府":"近畿","兵庫県":"近畿","奈良県":"近畿","和歌山県":"近畿",
    "鳥取県":"中国","島根県":"中国","岡山県":"中国","広島県":"中国","山口県":"中国",
    "徳島県":"四国","香川県":"四国","愛媛県":"四国","高知県":"四国",
    "福岡県":"九州・沖縄","佐賀県":"九州・沖縄","長崎県":"九州・沖縄","熊本県":"九州・沖縄","大分県":"九州・沖縄","宮崎県":"九州・沖縄","鹿児島県":"九州・沖縄","沖縄県":"九州・沖縄"
}

def fetch_municipalities_for_pref(pref_name):
    """Fetch municipalities using Wikipedia category API."""
    # Use the category for municipalities of each prefecture
    # Category format: Category:XX県の市町村 or Category:北海道の市町村
    cat_name = f"{pref_name}の市町村"
    
    municipalities = []
    cmcontinue = None
    
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{cat_name}",
            "cmlimit": "500",
            "cmtype": "page",  # pages only, not subcategories
            "format": "json"
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
            
        url = "https://ja.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "OrganicMapPlus/1.0"})
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        
        for member in data.get("query", {}).get("categorymembers", []):
            title = member["title"]
            # Filter: must end with 市/町/村/区
            if re.search(r'(市|町|村|区)$', title):
                # Skip disambiguation pages, lists, etc.
                if 'の一覧' not in title and '曖昧さ' not in title:
                    municipalities.append(title)
        
        if "continue" in data:
            cmcontinue = data["continue"]["cmcontinue"]
        else:
            break
    
    return sorted(set(municipalities))

def make_city_id(name, pref_idx):
    """Create a romanized city ID."""
    # Simple approach: use prefecture index + sequential number
    return None  # Will be assigned later

def main():
    result = {}
    total = 0
    
    for i, pref in enumerate(PREF_LIST):
        print(f"[{i+1}/47] {pref}...", end=" ", flush=True)
        try:
            munis = fetch_municipalities_for_pref(pref)
            result[pref] = munis
            total += len(munis)
            print(f"{len(munis)} municipalities")
        except Exception as e:
            print(f"ERROR: {e}")
            result[pref] = []
        
        if i < len(PREF_LIST) - 1:
            time.sleep(0.5)  # Be nice to Wikipedia
    
    print(f"\nTotal: {total} municipalities across 47 prefectures")
    
    with open("/home/organicmap-plus/data/spots/municipalities.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("Saved to municipalities.json")

if __name__ == "__main__":
    main()
