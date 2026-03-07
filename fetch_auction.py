"""
Fetches live auction data from CouchManagers and writes auction_data.json
to the repo root. GitHub Actions commits this file every 15 minutes.
The Grapefruit League site reads it from raw.githubusercontent.com.

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
    """Convert val to int safely, returning fallback for non-numeric strings like 'Done'."""
    try:
        return int(val or fallback)
    except (ValueError, TypeError):
        return fallback

def fetch_status():
    raw  = fetch(f"{CM_BASE}/ajax/update_auction_testing.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    return {
        "draft_status":    xml_text(root, "draft_status", "unknown"),
        "completed_total": safe_int(xml_text(root, "completed_total", "0")),
    }

def fetch_active():
    raw  = fetch(f"{CM_BASE}/ajax/update_current_auctions.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(raw)
    items = []

    # Try <nom> first, fall back to <player>
    nodes = root.findall("nom") or root.findall(".//nom") or \
            root.findall("player") or root.findall(".//player")

    for n in nodes:
        h = safe_int(xml_text(n, "hoursleft",   "0"))
        m = safe_int(xml_text(n, "minutesleft",  "0"))
        s = safe_int(xml_text(n, "secondsleft",  "0"))
        items.append({
            "name":         xml_text(n, "player_name") or xml_text(n, "name"),
            "pos":          xml_text(n, "position")    or xml_text(n, "pos"),
            "currentBid":   safe_int(xml_text(n, "current_bid")  or xml_text(n, "bid")),
            "bidder":       xml_text(n, "current_bidder") or xml_text(n, "bidder"),
            "nominator":    xml_text(n, "nominator"),
            "hoursLeft":    h,
            "minutesLeft":  m,
            "secondsLeft":  s,
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
        # Skip header row (first row or any row where first col is "First Name")
        if i == 0 or (len(row) > 0 and row[0].strip().strip('"') in ("First Name", "")):
            continue
        if len(row) < 4:
            continue

        first_name  = row[0].strip().strip('"')
        last_name   = row[1].strip().strip('"')
        price       = safe_int(row[2].strip().strip('"'))
        fantasy_team = row[3].strip().strip('"')

        if not first_name or not last_name or not fantasy_team:
            continue

        rows.append({
            "player": first_name + " " + last_name,  # full player name
            "team":   fantasy_team,                   # fantasy team name
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
