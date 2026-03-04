"""
Fetches MiLB draft results from the Fantrax API and writes fantrax_data.json.
Tries the public fxea endpoint first (no auth needed).
Falls back to authenticated POST endpoint using FANTRAX_USERNAME + FANTRAX_SECRET_ID.
GitHub Actions runs this every 10 minutes during the draft.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

LEAGUE_ID  = "nkgdrcl4mi3kzyk6"
USERNAME   = os.environ.get("FANTRAX_USERNAME", "")
SECRET_ID  = os.environ.get("FANTRAX_SECRET_ID", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GFL-DraftFetch/1.0)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def http_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def http_post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

# ── Fetch draft results ────────────────────────────────────────────────────────

def fetch_draft_results_public():
    """Try the public fxea endpoint — works if league is set to public."""
    url  = f"https://www.fantrax.com/fxea/general/getDraftResults?leagueId={LEAGUE_ID}"
    data = http_get(url)
    return data

def fetch_draft_results_auth():
    """Authenticated endpoint using username + secretId."""
    url = "https://www.fantrax.com/fxea/general/getDraftResults"
    payload = {
        "leagueId":  LEAGUE_ID,
        "username":  USERNAME,
        "secretId":  SECRET_ID,
    }
    return http_post(url, payload)

def fetch_rosters_public():
    """Pull current rosters (shows who owns whom after the draft)."""
    url  = f"https://www.fantrax.com/fxea/general/getTeamRosters?leagueId={LEAGUE_ID}&period=1"
    return http_get(url)

def fetch_rosters_auth():
    url = "https://www.fantrax.com/fxea/general/getTeamRosters"
    payload = {
        "leagueId":  LEAGUE_ID,
        "period":    1,
        "username":  USERNAME,
        "secretId":  SECRET_ID,
    }
    return http_post(url, payload)

def fetch_league_info():
    url  = f"https://www.fantrax.com/fxea/general/getLeagueInfo?leagueId={LEAGUE_ID}"
    return http_get(url)

# ── Parse draft picks ──────────────────────────────────────────────────────────

def parse_draft_picks(raw):
    """
    Normalise whatever shape the API returns into a flat list of picks.
    Fantrax returns: { "draftResults": [ { "pick": N, "teamName": "...",
                       "playerName": "...", "position": "...", ... } ] }
    """
    picks = []

    # Common shapes seen in the wild
    results = (
        raw.get("draftResults")
        or raw.get("picks")
        or raw.get("data", {}).get("draftResults")
        or raw.get("data", {}).get("picks")
        or []
    )

    for item in results:
        # Flatten nested player object if present
        player = item.get("player") or item
        picks.append({
            "pick":       item.get("pick") or item.get("pickNumber") or len(picks) + 1,
            "round":      item.get("round") or item.get("roundNumber") or "",
            "team":       item.get("teamName") or item.get("fantasyTeamName") or item.get("team", {}).get("name", ""),
            "teamId":     item.get("teamId") or item.get("fantasyTeamId") or "",
            "player":     player.get("name") or player.get("playerName") or "",
            "pos":        player.get("position") or player.get("pos") or "",
            "mlbTeam":    player.get("team") or player.get("mlbTeam") or "",
            "fantraxId":  player.get("id") or player.get("fantraxId") or "",
        })

    return picks

def parse_rosters(raw):
    """
    Turn getTeamRosters response into a list of {teamName, players[]}.
    Shape: { "rosters": { "teamId": { "teamName": "...", "rosterItems": [...] } } }
    """
    teams = []
    rosters = raw.get("rosters") or raw.get("data", {}).get("rosters") or {}

    for tid, tdata in rosters.items():
        name    = tdata.get("teamName") or tdata.get("name") or tid
        players = []
        for item in (tdata.get("rosterItems") or tdata.get("players") or []):
            p = item.get("player") or item
            players.append({
                "name":    p.get("name") or p.get("playerName") or "",
                "pos":     p.get("position") or p.get("pos") or "",
                "mlbTeam": p.get("team") or "",
            })
        teams.append({"teamId": tid, "teamName": name, "players": players})

    teams.sort(key=lambda t: t["teamName"])
    return teams

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"Fetching Fantrax draft data for league {LEAGUE_ID}…")

    # 1. Try public endpoint first
    draft_raw  = None
    roster_raw = None
    league_raw = None
    auth_used  = False

    try:
        draft_raw = fetch_draft_results_public()
        print("  ✅ Draft results via public endpoint")
    except Exception as e:
        print(f"  ⚠ Public draft endpoint failed ({e}), trying authenticated…")
        if not USERNAME or not SECRET_ID:
            print("  ❌ FANTRAX_USERNAME / FANTRAX_SECRET_ID not set — cannot authenticate")
            sys.exit(1)
        try:
            draft_raw = fetch_draft_results_auth()
            auth_used = True
            print("  ✅ Draft results via authenticated endpoint")
        except Exception as e2:
            print(f"  ❌ Authenticated draft endpoint also failed: {e2}")
            sys.exit(1)

    try:
        roster_raw = fetch_rosters_public() if not auth_used else fetch_rosters_auth()
        print("  ✅ Rosters fetched")
    except Exception as e:
        print(f"  ⚠ Roster fetch failed ({e}) — skipping")
        roster_raw = {}

    try:
        league_raw = fetch_league_info()
        print("  ✅ League info fetched")
    except Exception as e:
        print(f"  ⚠ League info fetch failed ({e}) — skipping")
        league_raw = {}

    picks  = parse_draft_picks(draft_raw)
    rosters = parse_rosters(roster_raw)

    data = {
        "fetchedAt":   datetime.now(timezone.utc).isoformat(),
        "leagueId":    LEAGUE_ID,
        "leagueName":  league_raw.get("leagueName") or league_raw.get("name") or "Grapefruit League MiLB Draft",
        "draftStatus": league_raw.get("draftStatus") or ("complete" if picks else "pending"),
        "totalPicks":  len(picks),
        "picks":       picks,
        "rosters":     rosters,
        # Raw responses saved for debugging (truncated if huge)
        "_rawDraft":   draft_raw if len(str(draft_raw)) < 50000 else {"truncated": True},
    }

    with open("fantrax_data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"  ✅ Written fantrax_data.json — {len(picks)} picks, {len(rosters)} teams")

if __name__ == "__main__":
    main()
