#!/usr/bin/env python3
"""Generate spot data for all municipalities using Gemini API."""
import json, urllib.request, urllib.parse, os, time, sys, re

API_KEY = "AIzaSyDhnv07MSx5Ao0RNvthOTSu9Y6JhsBFDYk"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

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

def call_gemini(prompt):
    """Call Gemini API and return text response."""
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 65536,
            "responseMimeType": "application/json"
        }
    }).encode()
    
    req = urllib.request.Request(API_URL, data=payload, headers={
        "Content-Type": "application/json"
    })
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return text
        except Exception as e:
            if attempt < 2:
                print(f"  retry({attempt+1})...", end=" ", flush=True)
                time.sleep(3)
                req = urllib.request.Request(API_URL, data=payload, headers={
                    "Content-Type": "application/json"
                })
            else:
                raise

def generate_for_prefecture(pref_name, municipalities):
    """Generate spots for all municipalities in a prefecture."""
    muni_list = "\n".join(f"- {m}" for m in municipalities)
    
    prompt = f"""以下の{pref_name}の市区町村それぞれについて、観光・名所スポットを正確に3つずつ挙げてください。

市区町村リスト:
{muni_list}

各スポットについて以下の情報を含めてください:
- name: スポット名
- summary: 15文字以内の一言説明
- desc: 80〜150文字の説明文。以下を必ず含む:
  - 最寄り公共交通機関（鉄道: 路線名+駅名、バス: 路線名+バス停名。両方あれば両方書く）
  - 住所（「〒」不要、都道府県から書く）
  - 営業時間（あれば。24時間開放の公園等は「24時間開放」と記載）

レスポンスは以下のJSON形式で返してください（配列の配列、市区町村順）:
{{
  "municipalities": [
    {{
      "name": "市区町村名",
      "spots": [
        {{
          "name": "スポット名",
          "summary": "一言説明",
          "desc": "# スポット名\\n\\n**市区町村名** ({pref_name})\\n\\n説明文。\\n\\n**住所:** ...\\n**アクセス:** ...\\n**営業時間:** ..."
        }},
        ...
      ]
    }},
    ...
  ]
}}

注意:
- 実在するスポットのみ挙げること（架空のものは不可）
- descのMarkdown書式を守ること（# 見出し、**太字**）
- 小さな村でも公園、神社、自然スポット等3つは必ず出すこと
- 営業時間がないスポット（神社、公園等）は「24時間開放」または「参拝自由」と記載
"""
    
    text = call_gemini(prompt)
    return json.loads(text)

def make_city_id(name):
    """Create a simple city ID from Japanese name."""
    # Remove 市/町/村/区 suffix for shorter ID
    clean = re.sub(r'(市|町|村|区)$', '', name)
    return clean

def main():
    with open("/home/organicmap-plus/data/spots/municipalities.json", encoding="utf-8") as f:
        all_munis = json.load(f)
    
    # Load existing data or start fresh
    output_path = "/home/organicmap-plus/data/spots/spots_data_full.json"
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            spots_data = json.load(f)
    else:
        spots_data = {"prefectures": {}}
    
    # Determine which prefectures to process
    start_idx = 0
    if len(sys.argv) > 1:
        start_idx = int(sys.argv[1])
    
    pref_list = list(all_munis.keys())
    
    for i, pref_name in enumerate(pref_list):
        if i < start_idx:
            continue
        
        if pref_name in spots_data["prefectures"]:
            existing_cities = len(spots_data["prefectures"][pref_name]["cities"])
            expected_cities = len(all_munis[pref_name])
            if existing_cities >= expected_cities:
                print(f"[{i+1}/47] {pref_name} already done ({existing_cities} cities), skipping")
                continue
            else:
                print(f"[{i+1}/47] {pref_name} partial ({existing_cities}/{expected_cities}), regenerating...")
                # Remove partial data, regenerate fully
                del spots_data["prefectures"][pref_name]
        
        municipalities = all_munis[pref_name]
        if not municipalities:
            print(f"[{i+1}/47] {pref_name} has no municipalities, skipping")
            continue
        
        # Split into batches of 20 municipalities (to avoid token limits)
        batch_size = 20
        all_muni_data = []
        
        for batch_start in range(0, len(municipalities), batch_size):
            batch = municipalities[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, len(municipalities))
            print(f"[{i+1}/47] {pref_name} ({batch_start+1}-{batch_end}/{len(municipalities)})...", end=" ", flush=True)
            
            try:
                result = generate_for_prefecture(pref_name, batch)
                all_muni_data.extend(result["municipalities"])
                print(f"OK ({len(result['municipalities'])} cities)")
            except Exception as e:
                print(f"ERROR: {e}")
                # Save progress and continue
                continue
            
            time.sleep(1)  # Rate limiting
        
        # Build prefecture entry
        pref_data = {
            "area": AREA_MAP.get(pref_name, ""),
            "cities": {}
        }
        
        pref_idx = pref_list.index(pref_name) + 1
        for j, muni in enumerate(all_muni_data):
            city_id = f"{pref_idx:02d}_{j+1:03d}"
            city_name = muni["name"]
            
            spots = []
            for k, spot in enumerate(muni.get("spots", [])):
                spots.append({
                    "name": spot["name"],
                    "summary": spot.get("summary", ""),
                    "desc": spot.get("desc", ""),
                    "img": ""  # Will be filled by image fetcher
                })
            
            pref_data["cities"][city_id] = {
                "name": city_name,
                "spots": spots
            }
        
        spots_data["prefectures"][pref_name] = pref_data
        
        # Save after each prefecture
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(spots_data, f, ensure_ascii=False, indent=2)
        
        print(f"  Saved. Total prefectures: {len(spots_data['prefectures'])}")

    # Final summary
    total_cities = sum(len(p["cities"]) for p in spots_data["prefectures"].values())
    total_spots = sum(
        len(s["spots"]) 
        for p in spots_data["prefectures"].values() 
        for s in p["cities"].values()
    )
    print(f"\nDone! {len(spots_data['prefectures'])} prefectures, {total_cities} cities, {total_spots} spots")

if __name__ == "__main__":
    main()
