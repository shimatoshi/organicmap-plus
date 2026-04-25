#!/usr/bin/env python3
"""駅ごとに散策動画をshimatube(yt-dlp)で検索→DL→HW HEVC 200k→音声32k monoに圧縮。

- 既に出力がある駅はスキップ（再開可能）
- 検索クエリは優先順で複数試す
- 候補は 5〜20分尺、再生数多い順
- 失敗はmanifest.jsonのfailuresに記録
"""
import json
import subprocess
import shlex
import shutil
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "stations.json"
MANIFEST = ROOT / "data" / "manifest.json"
VIDEO_DIR = ROOT / "cache" / "videos"
RAW_DIR = ROOT / "cache" / "raw"
SDCARD_TMP = Path.home() / "storage" / "downloads" / "_omp_tmp"

QUERIES = [
    "{name} 駅前 散策",
    "{name} 周辺 散策",
    "{name}駅 街歩き",
    "{name} ウォーキング",
]

MIN_DUR = 300      # 5 min
MAX_DUR = 1200     # 20 min
TARGET_HEIGHT = 480
HW_BITRATE = 200_000
AUDIO_BITRATE = "32k"


def run(cmd, **kw):
    """Run cmd list, return (rc, stdout_str, stderr_str)."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 900)
    p = subprocess.run(cmd, **kw)
    return p.returncode, p.stdout or "", p.stderr or ""


def search_video(query: str, topn: int = 3) -> list[dict]:
    """yt-dlpで検索、候補をviews降順でtopn件返す。"""
    cmd = [
        "yt-dlp", "--quiet", "--no-warnings",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(duration)s\t%(view_count)s",
        f"ytsearch10:{query}",
    ]
    rc, out, err = run(cmd, timeout=120)
    if rc != 0:
        return []
    cands = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        vid, title, dur_s = parts[0], parts[1], parts[2]
        views = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        try:
            dur = int(float(dur_s))
        except ValueError:
            continue
        if not (MIN_DUR <= dur <= MAX_DUR):
            continue
        if "ライブ" in title or "LIVE" in title.upper():
            continue
        cands.append({"id": vid, "title": title, "dur": dur, "views": views})
    cands.sort(key=lambda c: c["views"], reverse=True)
    return cands[:topn]


def download_video(vid: str, out_path: Path) -> bool:
    cmd = [
        "yt-dlp",
        "-f", f"best[height<={TARGET_HEIGHT}][ext=mp4]/best[ext=mp4]/best",
        "-o", str(out_path),
        "--quiet", "--no-warnings",
        f"https://www.youtube.com/watch?v={vid}",
    ]
    rc, out, err = run(cmd, timeout=600)
    return rc == 0 and out_path.exists()


def hw_encode(in_path: Path, out_path: Path) -> bool:
    """encode.shで HW HEVC 200kbps。入出力ともsdcard経由。"""
    SDCARD_TMP.mkdir(parents=True, exist_ok=True)
    sd_in = SDCARD_TMP / "in.mp4"
    sd_out = SDCARD_TMP / "out.mp4"
    shutil.copy(in_path, sd_in)
    sd_out.unlink(missing_ok=True)

    andr_in = f"/storage/emulated/0/Download/_omp_tmp/{sd_in.name}"
    andr_out = f"/storage/emulated/0/Download/_omp_tmp/{sd_out.name}"
    cmd = [
        "bash", "/home/.claude/skills/encode/encode.sh",
        andr_in, andr_out, str(HW_BITRATE),
    ]
    rc, out, err = run(cmd, timeout=1800)
    ok = sd_out.exists() and sd_out.stat().st_size > 0
    if ok:
        shutil.move(sd_out, out_path)
    sd_in.unlink(missing_ok=True)
    return ok


def audio_reencode(in_path: Path, out_path: Path) -> bool:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(in_path),
        "-c:v", "copy",
        "-ac", "1", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(out_path), "-y",
    ]
    rc, out, err = run(cmd, timeout=120)
    return rc == 0 and out_path.exists()


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"videos": {}, "failures": {}}


def save_manifest(m: dict):
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2))


def process_station(s: dict, manifest: dict) -> bool:
    sid = s["id"]
    name = s["name"].rstrip("駅")
    final = VIDEO_DIR / f"{sid}.mp4"
    if final.exists():
        if sid not in manifest["videos"]:
            manifest["videos"][sid] = {
                "path": f"videos/{sid}.mp4",
                "size_bytes": final.stat().st_size,
                "note": "recovered from filesystem; source metadata lost",
            }
        print(f"  [skip] {sid} already processed")
        return True

    print(f"  [search] {sid} ({name})")
    candidates = []
    for q_tmpl in QUERIES:
        q = q_tmpl.format(name=name)
        try:
            hits = search_video(q, topn=3)
        except Exception as e:
            print(f"    search err: {e}")
            continue
        for h in hits:
            h["_query"] = q
            candidates.append(h)
        if candidates:
            break
    if not candidates:
        manifest["failures"][sid] = "no candidate"
        return False

    raw = RAW_DIR / f"{sid}.mp4"
    hevc = RAW_DIR / f"{sid}_hevc.mp4"
    hit = None
    for c in candidates:
        print(f"    try: {c['id']} ({c['dur']}s, {c['views']}v) {c['title'][:40]}")
        raw.unlink(missing_ok=True)
        if download_video(c["id"], raw):
            hit = c
            break
        print(f"      DL failed, next...")
    if not hit:
        manifest["failures"][sid] = f"dl failed all {len(candidates)} candidates"
        return False
    used_q = hit["_query"]
    raw_size = raw.stat().st_size

    print(f"    encoding (HW HEVC)...")
    if not hw_encode(raw, hevc):
        manifest["failures"][sid] = f"hw encode failed: {hit['id']}"
        raw.unlink(missing_ok=True)
        return False

    if not audio_reencode(hevc, final):
        manifest["failures"][sid] = f"audio reencode failed: {hit['id']}"
        return False

    final_size = final.stat().st_size
    print(f"    ok: {raw_size//1048576}MB -> {final_size//1048576}MB "
          f"(-{100 - final_size*100//raw_size}%)")

    manifest["videos"][sid] = {
        "youtube_id": hit["id"],
        "title": hit["title"],
        "duration": hit["dur"],
        "source_url": f"https://www.youtube.com/watch?v={hit['id']}",
        "query": used_q,
        "size_bytes": final_size,
        "path": f"videos/{sid}.mp4",
    }
    if sid in manifest["failures"]:
        del manifest["failures"][sid]
    raw.unlink(missing_ok=True)
    hevc.unlink(missing_ok=True)
    return True


def main():
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    doc = json.loads(DATA.read_text())
    manifest = load_manifest()

    stations = doc["stations"]
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    if only:
        stations = [s for s in stations if s["id"] in only]

    print(f"Processing {len(stations)} stations")
    t0 = time.time()
    ok = 0
    for i, s in enumerate(stations, 1):
        print(f"[{i}/{len(stations)}] {s['pref']} {s['name']}")
        try:
            if process_station(s, manifest):
                ok += 1
        except Exception as e:
            print(f"  ERR: {e}")
            manifest["failures"][s["id"]] = f"exception: {e}"
        save_manifest(manifest)

    dt = time.time() - t0
    print(f"\n--- Done: {ok}/{len(stations)} success, {dt/60:.1f} min ---")


if __name__ == "__main__":
    main()
