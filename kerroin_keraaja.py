"""
Kerroinkeräjä GitHub Actionsille: tekee YHDEN kierroksen ja päättää itse mitä haetaan.
Valioliiga + Serie B, Pinnacle 1X2, The Odds API:n ilmaisen paketin budjetilla.
Tallentaa kertoimet tiedostoon kertoimet.csv ja hakujen lokin tiedostoon haut_loki.csv.
API-avain luetaan ympäristömuuttujasta ODDS_API_KEY (GitHub Secret).
"""
import csv
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests

API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_CSV = "kertoimet.csv"
LOG_CSV = "haut_loki.csv"
ODDS_FIELDS = ["ts", "league", "match_id", "home", "away", "commence", "o_home", "o_draw", "o_away"]
LOG_FIELDS = ["ts", "league", "remaining", "cost"]

MONTHLY_CREDITS = 500
RESERVE = 25              # muiden mallien käyttö (~20/kk) + pelivara
RESET_DAY = 1             # kuun päivä jolloin krediitit nollautuvat (tarkista The Odds API -tilistä)
QUIET_START, QUIET_END = 1, 7   # yötauko Suomen aikaa
TOLERANCE_SEC = 300       # GitHubin ajastus voi myöhästyä, sallitaan 5 min heitto

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")   # ntfy.sh-aihe puhelimen ilmoituksille (GitHub Secret)
DROP_THRESHOLD = 0.10     # ilmoitus, kun Pinnaclen kerroin laskee vähintään näin paljon edellisestä haustasta

LEAGUES = {"Valioliiga": "soccer_epl", "Serie B": "soccer_italy_serie_b"}
SCHEDULE = [(2, 30), (24, 90), (72, 240)]   # (tuntia otteluun, hakuväli min)
DEFAULT_INTERVAL = 720


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_csv(path, fields, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def days_until_reset(today):
    if today.day < RESET_DAY:
        reset = date(today.year, today.month, RESET_DAY)
    else:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        reset = date(y, m, RESET_DAY)
    return max((reset - today).days, 1)


def interval_for(odds_rows, league, now):
    kickoffs = {r["commence"] for r in odds_rows if r["league"] == league}
    future = [parse(k) for k in kickoffs if parse(k) > now]
    if not future:
        return DEFAULT_INTERVAL, 1e9
    hours = (min(future) - now).total_seconds() / 3600
    for limit, minutes in SCHEDULE:
        if hours <= limit:
            return minutes, hours
    return DEFAULT_INTERVAL, hours


def notify(title, message):
    """Lähettää push-ilmoituksen ntfy.sh:n kautta. Ei tee mitään, jos NTFY_TOPIC puuttuu."""
    if not NTFY_TOPIC:
        print("NTFY_TOPIC puuttuu, ilmoitusta ei lähetetä:", message)
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "chart_with_downwards_trend"},
            timeout=15,
        )
    except Exception as e:
        print("Ilmoituksen lähetys epäonnistui:", e)


def find_drops(prev_row, row):
    """Palauttaa listan (tulos, vanha, uusi), joissa kerroin on laskenut vähintään DROP_THRESHOLD."""
    drops = []
    for key, name in [("o_home", "Koti"), ("o_draw", "Tasapeli"), ("o_away", "Vieras")]:
        try:
            old, new = float(prev_row[key]), float(row[key])
        except (TypeError, ValueError, KeyError):
            continue
        if old - new >= DROP_THRESHOLD - 1e-9:
            drops.append((name, old, new))
    return drops


def fetch(sport_key):
    r = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
        params={"apiKey": API_KEY, "regions": "eu", "markets": "h2h",
                "bookmakers": "pinnacle", "oddsFormat": "decimal"},
        timeout=30,
    )
    r.raise_for_status()
    rem = r.headers.get("x-requests-remaining")
    cost = float(r.headers.get("x-requests-last", 1))
    return r.json(), (float(rem) if rem is not None else None), cost


def main():
    if not API_KEY:
        raise SystemExit("ODDS_API_KEY puuttuu")
    now = datetime.now(timezone.utc)
    if QUIET_START <= now.astimezone(ZoneInfo("Europe/Helsinki")).hour < QUIET_END:
        print("Yötauko, ei haeta.")
        return

    log = read_csv(LOG_CSV)
    odds = read_csv(ODDS_CSV)
    remaining = float(log[-1]["remaining"]) if log else float(MONTHLY_CREDITS)
    today = now.date()
    spent = sum(float(r["cost"]) for r in log if r["ts"].startswith(today.isoformat()))

    prev_by_match = {}
    for r in odds:                      # tiedosto on aikajärjestyksessä, viimeinen rivi voittaa
        prev_by_match[r["match_id"]] = r

    due = []
    for league in LEAGUES:
        minutes, hours = interval_for(odds, league, now)
        times = [parse(r["ts"]) for r in log if r["league"] == league]
        last = max(times) if times else None
        if last is None or (now - last).total_seconds() >= minutes * 60 - TOLERANCE_SEC:
            due.append((hours, league))

    for _, league in sorted(due):
        # päiväbudjetti: jäljellä oleva + tänään käytetty, miinus varaus, jaettuna päivillä
        allowance = (remaining + spent - RESERVE) / days_until_reset(today)
        if remaining <= RESERVE or spent + 1 > allowance:
            print(f"Budjetti täynnä (jäljellä {remaining:.0f}, tänään {spent:.0f}), ohitetaan.")
            break
        try:
            games, rem, cost = fetch(LEAGUES[league])
        except Exception as e:
            print(f"{league}: virhe {e}")
            continue
        ts = now.isoformat(timespec="seconds")
        rows = []
        for g in games:
            pin = next((b for b in g["bookmakers"] if b["key"] == "pinnacle"), None)
            market = next((m for m in pin["markets"] if m["key"] == "h2h"), None) if pin else None
            if not market:
                continue
            p = {o["name"]: o["price"] for o in market["outcomes"]}
            rows.append({"ts": ts, "league": league, "match_id": g["id"], "home": g["home_team"],
                         "away": g["away_team"], "commence": g["commence_time"],
                         "o_home": p.get(g["home_team"]), "o_draw": p.get("Draw"),
                         "o_away": p.get(g["away_team"])})
        for row in rows:
            prev = prev_by_match.get(row["match_id"])
            if not prev or parse(row["commence"]) <= now:
                continue
            drops = find_drops(prev, row)
            if drops:
                lines = [f"{n}: {o:.2f} -> {nw:.2f} ({nw - o:+.2f})" for n, o, nw in drops]
                notify("Pinnacle-kerroin laski",
                       f"{league}: {row['home']} - {row['away']}\n" + "\n".join(lines))
        remaining = rem if rem is not None else remaining - cost
        spent += cost
        if rows:
            append_csv(ODDS_CSV, ODDS_FIELDS, rows)
        append_csv(LOG_CSV, LOG_FIELDS, [{"ts": ts, "league": league, "remaining": remaining, "cost": cost}])
        print(f"{league}: {len(rows)} ottelua, krediittejä jäljellä {remaining:.0f}")


if __name__ == "__main__":
    main()
