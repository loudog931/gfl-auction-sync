"""
Fetches live auction data from CouchManagers and writes auction_data.json
to the repo root. GitHub Actions commits this file every 15 minutes.
The Grapefruit League site reads it from Firebase Hosting.

CSV column mapping (CouchManagers csv/download.php):
  Col 0 = First Name
  Col 1 = Last Name
  Col 2 = Price
  Col 3 = Fantasy Team Name
"""

import csv
import io
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

def safe_int(val, fallback=0):
    try:
        return int(val or fallback)
    except (ValueError, TypeError):
        return fallback

def parse_time3(time3):
    """Parse 'MM:SS' or 'HH:MM:SS' into total seconds."""
    parts = time3.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        pass
    return 0

def fetch_status():
    raw  = fetch(f"{CM_BASE}/ajax/update_auction_testing.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    return {
        "draft_status":    xml_text(root, "draft_status", "unknown"),
        "completed_total": safe_int(xml_text(root, "completed_total", "0")),
    }

def fetch_active():
    """
    CM returns <root><auction> nodes with:
      <playerid>, <teamnum>, <teamname>, <amount>, <time3> (MM:SS)
    We look up player names from the completed CSV by playerid if possible,
    otherwise show playerid as fallback.
    """
    raw  = fetch(f"{CM_BASE}/ajax/update_current_auctions.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    items = []

    for n in root.findall("auction"):
        time3      = xml_text(n, "time3", "0:00")
        total_secs = parse_time3(time3)
        mins       = total_secs // 60
        secs       = total_secs % 60
        items.append({
            "playerId":    xml_text(n, "playerid"),
            "currentBid":  safe_int(xml_text(n, "amount")),
            "bidder":      xml_text(n, "teamname"),
            "timeDisplay": xml_text(n, "time3"),
            "minutesLeft": mins,
            "secondsLeft": secs,
            "totalSeconds": total_secs,
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
            "moneyLeft": safe_int(xml_text(t, "real_money_left") or xml_text(t, "money_left"), 260),
            "spent":     safe_int(xml_text(t, "money_spent"), 0),
            "won":       safe_int(xml_text(t, "players_won"), 0),
        })
    return teams

def fetch_completed():
    raw = fetch(f"{CM_BASE}/csv/download.php?auction_id={AUCTION_ID}")
    if "No completed" in raw:
        return []

    rows = []
    reader = csv.reader(io.StringIO(raw))
    for i, row in enumerate(reader):
        if i == 0 or (len(row) > 0 and row[0].strip().strip('"') in ("First Name", "")):
            continue
        if len(row) < 4:
            continue

        first_name   = row[0].strip().strip('"')
        last_name    = row[1].strip().strip('"')
        price        = safe_int(row[2].strip().strip('"'))
        fantasy_team = row[3].strip().strip('"')

        if not first_name or not last_name or not fantasy_team:
            continue

        # Skip keepers ($0 bids to Minors teams) and $0 entries
        if price == 0:
            continue
        if fantasy_team.lower().startswith("minors"):
            continue

        rows.append({
            "player": first_name + " " + last_name,
            "team":   fantasy_team,
            "price":  price,
        })
    return rows

def main():
    print("Fetching auction status...")
    status = fetch_status()

    print("Fetching active nominations...")
    active = fetch_active()

    print("Fetching team budgets...")
    teams = fetch_teams()

    print("Fetching completed auctions...")
    completed = fetch_completed()

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

    print(f"Done. {len(completed)} completed, {len(active)} active, {len(teams)} teams.")

if __name__ == "__main__":
    main()
