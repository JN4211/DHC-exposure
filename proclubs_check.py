"""
FC26 ProClubs Match Checker
試合結果が更新されるたびに全件をDiscordに投稿する
GitHub Actionsが5分おきに自動実行する
"""

import asyncio
import json
import os
import aiohttp
from pathlib import Path
from datetime import datetime

EA_API_BASE = "https://proclubs.ea.com/api/fc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.ea.com/",
    "Accept":     "application/json",
}

RESULT_INFO = {
    1: {"label": "🏆 勝利",     "color": 0x00CC66},
    2: {"label": "😭 敗北",     "color": 0xEE3333},
    3: {"label": "🤝 引き分け", "color": 0x999999},
}


async def fetch_recent_matches(club_id: str, platform: str) -> list:
    url    = f"{EA_API_BASE}/clubs/matches"
    params = {"platform": platform, "clubIds": club_id, "matchType": "leagueMatch"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, params=params, headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            print(f"⚠️ APIエラー: HTTP {resp.status}")
            return []


def build_embed(match: dict, my_club_id: str) -> dict:
    clubs    = match.get("clubs", {})
    my_data  = clubs.get(str(my_club_id), {})
    opp_data = next((v for k, v in clubs.items() if k != str(my_club_id)), {})

    my_goals    = int(my_data.get("goals",  0))
    opp_goals   = int(opp_data.get("goals", 0))
    result_code = my_data.get("result", 3)

    info     = RESULT_INFO.get(result_code, {"label": "⚽ 試合終了", "color": 0x5865F2})
    my_name  = my_data.get("details",  {}).get("name", "自クラブ")
    opp_name = opp_data.get("details", {}).get("name", "相手クラブ")

    ts = match.get("timestamp", 0)
    dt = datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M") if ts else "不明"

    fields = [
        {
            "name":   info["label"],
            "value":  f"**{my_name}**　`  {my_goals}  -  {opp_goals}  `　**{opp_name}**",
            "inline": False,
        },
        {"name": "🕐 日時", "value": dt, "inline": True},
    ]

    scorer_lines = []
    for ea_id, stats in match.get("players", {}).get(str(my_club_id), {}).items():
        name    = stats.get("playername", f"Player_{ea_id}")
        goals   = int(stats.get("goals",   0))
        assists = int(stats.get("assists",  0))
        if goals > 0 or assists > 0:
            parts = []
            if goals   > 0: parts.append(f"⚽ {goals}G")
            if assists > 0: parts.append(f"🅰️ {assists}A")
            scorer_lines.append(f"{name}  {' / '.join(parts)}")

    if scorer_lines:
        fields.append({
            "name":   "📋 得点・アシスト",
            "value":  "\n".join(scorer_lines),
            "inline": False,
        })

    return {
        "title":  "⚽ FC26 ProClubs 試合結果",
        "color":  info["color"],
        "fields": fields,
        "footer": {"text": "FC26 ProClubs Tracker"},
    }


async def post_to_discord(webhook_url: str, embed: dict) -> None:
    async with aiohttp.ClientSession() as session:
        resp = await session.post(webhook_url, json={"embeds": [embed]})
        if resp.status in (200, 204):
            print("✅ Discord投稿成功！")
        else:
            print(f"❌ 投稿失敗 (HTTP {resp.status}): {await resp.text()}")


async def main() -> None:
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    club_id     = os.environ.get("CLUB_ID",     "")
    platform    = os.environ.get("PLATFORM",    "common-gen5")

    if not webhook_url or not club_id:
        print("❌ 環境変数 WEBHOOK_URL または CLUB_ID が未設定です")
        return

    state_path    = Path("state.json")
    last_match_id = None
    if state_path.exists():
        try:
            last_match_id = json.loads(state_path.read_text()).get("last_match_id")
        except Exception:
            pass

    print(f"🔍 チェック開始 | club_id={club_id} / platform={platform}")

    matches = await fetch_recent_matches(club_id, platform)
    if not matches:
        print("試合データなし / APIエラー")
        return

    # 初回実行：記録のみ、投稿しない
    if last_match_id is None:
        latest_id = matches[0].get("matchId", "")
        state_path.write_text(json.dumps({"last_match_id": latest_id}))
        print("📌 初回実行：最新試合IDを記録しました（次回から投稿開始）")
        return

    # 前回以降の新試合をすべて抽出（APIは新しい順で返す）
    new_matches = []
    for match in matches:
        if match.get("matchId") == last_match_id:
            break
        new_matches.append(match)

    if not new_matches:
        print("新しい試合なし")
        return

    print(f"🎮 {len(new_matches)} 試合の新着を検知！")

    # 古い順（時系列順）に投稿
    for match in reversed(new_matches):
        embed = build_embed(match, club_id)
        await post_to_discord(webhook_url, embed)
        await asyncio.sleep(1)

    # 最新の試合IDで更新
    new_last_id = matches[0].get("matchId", "")
    state_path.write_text(json.dumps({"last_match_id": new_last_id}))
    print(f"💾 state.json 更新: {new_last_id}")


if __name__ == "__main__":
    asyncio.run(main())
