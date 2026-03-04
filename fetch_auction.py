"""
Fetches live auction data from CouchManagers and writes auction_data.json
to the repo root. GitHub Actions commits this file every 15 minutes.
The Grapefruit League site reads it from raw.githubusercontent.com.
"""

import json
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime, timezone

AUCTION_ID = "1543"
CM_BASE    = "https://www.couchmanagers.com/auctions"

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GFL-AuctionFetch/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")

def xml_text(el, tag, default=""):
    n = el.find(tag)
    return n.text.strip() if n is not None and n.text else default

def fetch_status():
    raw  = fetch(f"{CM_BASE}/ajax/update_auction_testing.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    return {
        "draft_status":    xml_text(root, "draft_status", "unknown"),
        "completed_total": int(xml_text(root, "completed_total", "0") or 0),
    }

def fetch_active():
    raw  = fetch(f"{CM_BASE}/ajax/update_current_auctions.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    items = []

    # Try <nom> first, fall back to <player>
    nodes = root.findall("nom") or root.findall(".//nom") or \
            root.findall("player") or root.findall(".//player")

    for n in nodes:
        h  = int(xml_text(n, "hoursleft",   "0") or 0)
        m  = int(xml_text(n, "minutesleft", "0") or 0)
        s  = int(xml_text(n, "secondsleft", "0") or 0)
        items.append({
            "name":      xml_text(n, "player_name") or xml_text(n, "displayName") or xml_text(n, "name"),
            "pos":       xml_text(n, "position") or xml_text(n, "pos"),
            "mlbTeam":   xml_text(n, "mlb_team") or xml_text(n, "team"),
            "bid":       xml_text(n, "current_bid") or xml_text(n, "price") or "1",
            "bidder":    xml_text(n, "high_bidder") or xml_text(n, "owner_name"),
            "nominator": xml_text(n, "nominator"),
            "hoursLeft":   h,
            "minutesLeft": m,
            "secondsLeft": s,
            "totalSeconds": h * 3600 + m * 60 + s,
        })
    return items

def fetch_teams():
    raw  = fetch(f"{CM_BASE}/ajax/update_teams_2025_02_03.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    teams = []
    for t in root.findall(".//team"):
        name = xml_text(t, "teamname")
        if not name or name == "-":
            continue
        teams.append({
            "name":      name,
            "moneyLeft": int(xml_text(t, "real_money_left") or xml_text(t, "money_left") or 260),
            "spent":     int(xml_text(t, "money_spent") or 0),
            "won":       int(xml_text(t, "players_won")  or 0),
        })
    return teams

def fetch_completed():
    raw = fetch(f"{CM_BASE}/csv/download.php?auction_id={AUCTION_ID}")
    if "No completed" in raw:
        return []
    rows = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("Player"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        rows.append({
            "player": parts[0].strip(),
            "team":   parts[1].strip(),
            "price":  int((parts[2].strip().replace("$","").replace(" ","")) or 0),
            "pos":    parts[3].strip() if len(parts) > 3 else "",
        })
    return list(reversed(rows))  # newest first

def main():
    print("Fetching CouchManagers auction data…")
    try:
        status    = fetch_status()
        active    = fetch_active()
        teams     = fetch_teams()
        completed = fetch_completed()
    except Exception as e:
        print(f"  ❌ Fetch failed: {e}")
        raise

    data = {
        "fetchedAt":      datetime.now(timezone.utc).isoformat(),
        "draftStatus":    status["draft_status"],
        "completedTotal": status["completed_total"],
        "active":         active,
        "teams":          teams,
        "completed":      completed,
    }

    with open("auction_data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"  ✅ Written auction_data.json")
    print(f"     Status: {data['draftStatus']} | Active: {len(active)} | Completed: {len(completed)}")

if __name__ == "__main__":
    main()
