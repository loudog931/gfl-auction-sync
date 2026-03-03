"""
Grapefruit League Auction Sync
Polls CouchManagers auction XML and updates Firebase Firestore
when players are won in the auction.
"""

import os
import json
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from difflib import SequenceMatcher

# ── Firebase (via REST API — no SDK needed in GitHub Actions) ──────────────
FIREBASE_PROJECT = "grapefruit-league-uaat"
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "AIzaSyB4KS7EPb-mX1GBMo9zgQma2xGySM_JbWE")
FIRESTORE_BASE = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}/databases/(default)/documents"

# ── CouchManagers ──────────────────────────────────────────────────────────
AUCTION_ID = "1543"
CM_BASE = "https://www.couchmanagers.com/auctions"

# ── Team name mapping: CouchManagers name → GFL teamId ────────────────────
# GFL teams (from app): {1: Moneyball Martell, 2: Aces High, 3: Pythagorean Triple Play,
#   4: Mortytown Locos, 5: Logjammin' with Karl Hungus, 6: The Other Guys, 7: Stilettos,
#   8: Chaos In Tejas, 9: MC Grumpy D, 10: Schlittlers Full, 11: Enkidu,
#   12: Tennessee Jeds, 13: Up And At Them, 14: Ultimate Price, 15: Silver Panthers,
#   16: Gankin Zone, 17: Trot Nixon, 18: The Rolling Quintanas}
TEAM_MAP = {
    "tennessee jeds":           12,
    "ultimate price":           14,
    "schlittlers full":         10,
    "schlittler":               10,
    "the other guys":           6,
    "stilettos":                7,
    "uaat":                     13,   # "Up And At Them" — your team
    "up and at them":           13,
    "mcgrumpyd":                9,
    "mc grumpy d":              9,
    "chaos in tejas":           8,
    "chaos in tejas (gfl)":     8,
    "moneyball martell":        1,
    "aces high":                2,
    "pythagorean triple play":  3,
    "mortytown locos":          4,
    "logjammin":                5,
    "logjammin' with karl hungus": 5,
    "enkidu":                   11,
    "silver panthers":          15,
    "gankin zone":              16,
    "trot nixon":               17,
    "the rolling quintanas":    18,
}

GFL_TEAMS = {
    1: "Moneyball Martell", 2: "Aces High", 3: "Pythagorean Triple Play",
    4: "Mortytown Locos", 5: "Logjammin' with Karl Hungus", 6: "The Other Guys",
    7: "Stilettos", 8: "Chaos In Tejas", 9: "MC Grumpy D", 10: "Schlittlers Full",
    11: "Enkidu", 12: "Tennessee Jeds", 13: "Up And At Them", 14: "Ultimate Price",
    15: "Silver Panthers", 16: "Gankin Zone", 17: "Trot Nixon", 18: "The Rolling Quintanas"
}


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GFL-Sync/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def get_cm_status():
    """Returns completed_total count from CouchManagers."""
    xml = fetch_url(f"{CM_BASE}/ajax/update_auction_testing.php?auction_id={AUCTION_ID}")
    root = ET.fromstring(xml)
    total = root.findtext("completed_total") or "0"
    status = root.findtext("draft_status") or "unknown"
    return int(total), status


def get_cm_csv():
    """
    Fetches completed auction CSV from CouchManagers.
    Returns list of dicts: [{player_name, team_name, price}, ...]
    """
    text = fetch_url(f"{CM_BASE}/csv/download.php?auction_id={AUCTION_ID}")
    if "No completed auction data" in text:
        return []

    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("Player"):
            continue
        parts = line.split(",")
        if len(parts) >= 3:
            results.append({
                "player_name": parts[0].strip(),
                "team_name":   parts[1].strip(),
                "price":       int(parts[2].strip().replace("$", "").replace(" ", "") or 0),
            })
    return results


def fuzzy_match(name, ratio=0.82):
    """Returns the best match ratio for string comparison."""
    return ratio


def match_cm_team(cm_name):
    """Map a CouchManagers team name to a GFL teamId."""
    key = cm_name.lower().strip()
    if key in TEAM_MAP:
        return TEAM_MAP[key]
    # Fuzzy fallback
    best_score, best_id = 0, None
    for map_key, team_id in TEAM_MAP.items():
        score = SequenceMatcher(None, key, map_key).ratio()
        if score > best_score:
            best_score, best_id = score, team_id
    if best_score >= 0.75:
        return best_id
    print(f"  ⚠️  Could not map team: '{cm_name}' (best score: {best_score:.2f})")
    return None


def match_gfl_player(cm_name, gfl_players):
    """Find a GFL player by name, using fuzzy matching."""
    cm_lower = cm_name.lower().strip()
    # Exact match first
    for p in gfl_players:
        if p["name"].lower().strip() == cm_lower:
            return p
    # Fuzzy match
    best_score, best_player = 0, None
    for p in gfl_players:
        score = SequenceMatcher(None, cm_lower, p["name"].lower().strip()).ratio()
        if score > best_score:
            best_score, best_player = score, p
    if best_score >= 0.80:
        return best_player
    print(f"  ⚠️  Could not match player: '{cm_name}' (best: '{best_player['name'] if best_player else 'none'}' {best_score:.2f})")
    return None


# ── Firestore REST helpers ─────────────────────────────────────────────────

def firestore_get(doc_path):
    url = f"{FIRESTORE_BASE}/{doc_path}?key={FIREBASE_API_KEY}"
    try:
        raw = fetch_url(url)
        return json.loads(raw)
    except Exception as e:
        print(f"  Firestore GET error: {e}")
        return None


def firestore_patch(doc_path, fields_dict):
    """Update specific fields in a Firestore document via PATCH."""
    url = f"{FIRESTORE_BASE}/{doc_path}?key={FIREBASE_API_KEY}"
    # Build field mask
    field_names = "&".join(f"updateMask.fieldPaths={k}" for k in fields_dict.keys())
    url += "&" + field_names

    body = json.dumps({"fields": fields_dict}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PATCH",
                                  headers={"Content-Type": "application/json",
                                           "User-Agent": "GFL-Sync/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def decode_firestore_doc(doc):
    """Convert Firestore REST response to plain Python dict."""
    def decode_value(v):
        if "stringValue" in v:   return v["stringValue"]
        if "integerValue" in v:  return int(v["integerValue"])
        if "doubleValue" in v:   return float(v["doubleValue"])
        if "booleanValue" in v:  return v["booleanValue"]
        if "nullValue" in v:     return None
        if "arrayValue" in v:
            return [decode_value(i) for i in v["arrayValue"].get("values", [])]
        if "mapValue" in v:
            return {k: decode_value(vv) for k, vv in v["mapValue"]["fields"].items()}
        return None

    fields = doc.get("fields", {})
    return {k: decode_value(v) for k, v in fields.items()}


def encode_firestore_value(val):
    """Convert Python value to Firestore REST value."""
    if val is None:        return {"nullValue": None}
    if isinstance(val, bool): return {"booleanValue": val}
    if isinstance(val, int):   return {"integerValue": str(val)}
    if isinstance(val, float): return {"doubleValue": val}
    if isinstance(val, str):   return {"stringValue": val}
    if isinstance(val, list):
        return {"arrayValue": {"values": [encode_firestore_value(i) for i in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: encode_firestore_value(v) for k, v in val.items()}}}
    return {"stringValue": str(val)}


def encode_players_array(players):
    return {"arrayValue": {"values": [
        {"mapValue": {"fields": {k: encode_firestore_value(v) for k, v in p.items()}}}
        for p in players
    ]}}


# ── Main sync logic ────────────────────────────────────────────────────────

def run_sync():
    print("🍊 Grapefruit League Auction Sync starting...")

    # 1. Check CouchManagers status
    try:
        completed_total, draft_status = get_cm_status()
    except Exception as e:
        print(f"  ❌ Failed to fetch CouchManagers status: {e}")
        return

    print(f"  CouchManagers status: {draft_status}, completed auctions: {completed_total}")

    if completed_total == 0:
        print("  No completed auctions yet. Nothing to sync.")
        return

    # 2. Get completed auction results from CSV
    try:
        cm_results = get_cm_csv()
    except Exception as e:
        print(f"  ❌ Failed to fetch CouchManagers CSV: {e}")
        return

    if not cm_results:
        print("  CSV returned no results yet.")
        return

    print(f"  Found {len(cm_results)} completed auction(s) on CouchManagers")

    # 3. Load current GFL state from Firebase
    doc = firestore_get("gfl/state")
    if not doc:
        print("  ❌ Could not load GFL state from Firebase")
        return

    state = decode_firestore_doc(doc)
    gfl_players = state.get("players", [])
    print(f"  Loaded {len(gfl_players)} players from GFL Firebase")

    # 4. Find players that need updating
    updates_made = 0
    players_modified = False

    for result in cm_results:
        cm_player = result["player_name"]
        cm_team   = result["team_name"]
        cm_price  = result["price"]

        gfl_team_id = match_cm_team(cm_team)
        if gfl_team_id is None:
            print(f"  ⚠️  Skipping '{cm_player}' — unknown team '{cm_team}'")
            continue

        gfl_player = match_gfl_player(cm_player, gfl_players)
        if gfl_player is None:
            print(f"  ⚠️  Skipping '{cm_player}' — not found in GFL player pool")
            continue

        # Check if already up to date
        already_synced = (
            gfl_player.get("status") == "sold" and
            gfl_player.get("teamId") == gfl_team_id and
            gfl_player.get("auctionPrice") == cm_price
        )
        if already_synced:
            continue

        # Update the player
        team_name = GFL_TEAMS.get(gfl_team_id, f"Team {gfl_team_id}")
        print(f"  ✅ {cm_player} → {team_name} for ${cm_price}")
        gfl_player["status"]       = "sold"
        gfl_player["teamId"]       = gfl_team_id
        gfl_player["auctionPrice"] = cm_price
        gfl_player["isKeeper"]     = False
        players_modified = True
        updates_made += 1

    if not players_modified:
        print(f"  ✓ GFL already up to date — no changes needed")
        return

    # 5. Write updated players array back to Firebase
    print(f"  Writing {updates_made} update(s) to Firebase...")
    try:
        firestore_patch("gfl/state", {"players": encode_players_array(gfl_players)})
        print(f"  🎉 Sync complete! {updates_made} player(s) updated.")
    except Exception as e:
        print(f"  ❌ Firebase write failed: {e}")
        raise


if __name__ == "__main__":
    run_sync()
