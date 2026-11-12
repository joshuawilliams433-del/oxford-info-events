#!/usr/bin/env python3
"""
Oxford Info — daily events builder.

Pulls events from several sources, filters for quality, de-duplicates, and
writes docs/events.json, which GitHub Pages serves to the app for free.

Sources (each is optional — missing keys are skipped):
  • curated.json           Your hand-picked events (always included, shown first)
  • Ticketmaster           Concerts, theatre, comedy (env TICKETMASTER_API_KEY)
  • Skiddle                Gigs, theatre, arts, festivals (env SKIDDLE_API_KEY)
  • iCal feeds in sources.json   Any venue/college/council calendar that offers .ics

Run locally:  TICKETMASTER_API_KEY=xxx python3 fetch_events.py
Uses ~2–4 API calls per run — far below every free limit.
"""
import json
import os
import re
import sys
import hashlib
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
OUT = HERE / "docs" / "events.json"
LONDON = ZoneInfo("Europe/London")

OXFORD_LAT, OXFORD_LON = 51.7520, -1.2577
RADIUS_KM = 6
DAYS_AHEAD = 45
MAX_EVENTS = 80
MAX_PER_VENUE = 6            # stops one venue flooding the map
MAX_DATES_PER_SHOW = 1       # a 3-week panto shows once, with a date range

# Venues that reliably put on quality events get a boost.
QUALITY_VENUES = [
    "new theatre", "oxford playhouse", "sheldonian", "o2 academy oxford",
    "holywell music room", "jacqueline du pré", "pegasus theatre",
    "north wall", "old fire station", "ashmolean", "pitt rivers",
    "natural history", "christ church", "bodleian", "weston library",
    "university church", "town hall", "jam factory", "cellar",
    "modern art oxford", "story museum", "blenheim",
]

# Things that aren't really events for visitors.
JUNK = re.compile(
    r"\b(club night|clubnight|silent disco|parking|car park|upgrade|vip package|hospitality package|gift card|voucher|"
    r"merch|add-?on|cloakroom|test event|private|members only|resale)\b", re.I)


# ----------------------------------------------------------------- helpers

def http_json(url, headers=None):
    req = Request(url, headers={"User-Agent": "OxfordInfoEvents/1.0", **(headers or {})})
    with urlopen(req, timeout=30) as r:
        return json.load(r)


def http_text(url):
    req = Request(url, headers={"User-Agent": "OxfordInfoEvents/1.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def nice_when(start, end=None, all_day=False):
    """'Fri 14 Nov · 19:30'  or  'Sat 15 Nov – Sun 4 Jan'"""
    s = start.astimezone(LONDON)
    if end and end.astimezone(LONDON).date() > s.date() + timedelta(days=1):
        e = end.astimezone(LONDON)
        return f"{s:%a %-d %b} – {e:%a %-d %b}"
    return f"{s:%a %-d %b}" if all_day else f"{s:%a %-d %b · %H:%M}"


def clean(text, limit=600):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def make_id(*parts):
    return "ev-" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def norm_title(t):
    t = re.sub(r"\(.*?\)|\[.*?\]", "", t.lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def event(**kw):
    """Shape matches the app's Place model."""
    cats = ["events"] + (["free"] if kw.get("free") else [])
    return {
        "id": kw["id"],
        "name": kw["name"].strip(),
        "categories": cats,
        "latitude": round(float(kw["lat"]), 6),
        "longitude": round(float(kw["lon"]), 6),
        "summary": kw.get("summary") or kw.get("venue", ""),
        "details": kw.get("details") or kw.get("summary") or "",
        "address": kw.get("address") or kw.get("venue", "Oxford"),
        "price": kw.get("price"),
        "website": kw.get("url"),
        "when": kw.get("when"),
        "startsAt": iso(kw.get("start")),
        "endsAt": iso(kw.get("end")),
        "imageURL": kw.get("image"),
        "venue": kw.get("venue"),
        "source": kw["source"],
        "_score": kw.get("score", 0),
    }


def score(name, venue, has_image, has_desc, base=0):
    s = base
    v = (venue or "").lower()
    if any(q in v for q in QUALITY_VENUES):
        s += 3
    if has_image:
        s += 1
    if has_desc:
        s += 1
    if JUNK.search(name or ""):
        s -= 100
    return s


def venue_key(name):
    """Treat sister rooms as one venue (e.g. 'O2 Academy2 Oxford' = 'O2 Academy Oxford')."""
    v = re.sub(r"(\D)\d\b", r"\1", name.lower().strip())
    return re.sub(r"\s+", " ", v)


def within_radius(lat, lon):
    from math import radians, sin, cos, asin, sqrt
    dlat, dlon = radians(lat - OXFORD_LAT), radians(lon - OXFORD_LON)
    a = sin(dlat / 2) ** 2 + cos(radians(OXFORD_LAT)) * cos(radians(lat)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a)) <= RADIUS_KM + 1


# ----------------------------------------------------------------- sources

def from_curated():
    path = HERE / "curated.json"
    if not path.exists():
        return []
    out = []
    for c in json.loads(path.read_text()):
        start = datetime.fromisoformat(c["start"]).replace(tzinfo=LONDON) if c.get("start") else None
        end = datetime.fromisoformat(c["end"]).replace(tzinfo=LONDON) if c.get("end") else None
        when = c.get("when") or (nice_when(start, end, all_day="T" not in c["start"]) if start else None)
        out.append(event(
            id=c.get("id") or make_id("cur", c["name"], c.get("start")),
            name=c["name"], lat=c["latitude"], lon=c["longitude"],
            summary=c.get("summary"), details=c.get("details"), address=c.get("address"),
            venue=c.get("venue"), price=c.get("price"), url=c.get("website"),
            image=c.get("imageURL"), free=c.get("free", False),
            start=start, end=end, when=when, source="curated", score=100))
    return out


def from_ticketmaster(key, start, end):
    params = {
        "apikey": key, "latlong": f"{OXFORD_LAT},{OXFORD_LON}", "radius": RADIUS_KM, "unit": "km",
        "countryCode": "GB", "locale": "*", "size": 200, "sort": "date,asc",
        "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "segmentName": "Music,Arts & Theatre,Miscellaneous,Film",
    }
    data = http_json("https://app.ticketmaster.com/discovery/v2/events.json?" + urlencode(params))
    out = []
    for e in data.get("_embedded", {}).get("events", []):
        venues = e.get("_embedded", {}).get("venues") or [{}]
        v = venues[0]
        loc = v.get("location") or {}
        if not loc.get("latitude"):
            continue
        lat, lon = float(loc["latitude"]), float(loc["longitude"])
        if not within_radius(lat, lon):
            continue
        d = e.get("dates", {}).get("start", {})
        if d.get("dateTime"):
            st = datetime.fromisoformat(d["dateTime"].replace("Z", "+00:00"))
            all_day = False
        elif d.get("localDate"):
            st = datetime.fromisoformat(d["localDate"]).replace(tzinfo=LONDON)
            all_day = True
        else:
            continue
        imgs = sorted((i for i in e.get("images", []) if i.get("ratio") == "16_9"),
                      key=lambda i: i.get("width", 0), reverse=True)
        image = imgs[0]["url"] if imgs else None
        pr = (e.get("priceRanges") or [{}])[0]
        price = f"From £{pr['min']:.0f}" if pr.get("min") else None
        genre = ((e.get("classifications") or [{}])[0].get("genre") or {}).get("name")
        venue_name = v.get("name", "")
        desc = clean(e.get("info") or e.get("description") or "")
        summary = " · ".join(x for x in [genre if genre and genre != "Undefined" else None, venue_name] if x)
        out.append(event(
            id=make_id("tm", e["id"]), name=e["name"], lat=lat, lon=lon,
            summary=summary, details=desc or f"Live at {venue_name}.",
            address=", ".join(x for x in [(v.get("address") or {}).get("line1"), v.get("postalCode")] if x),
            venue=venue_name, price=price, url=e.get("url"), image=image,
            start=st, when=nice_when(st, all_day=all_day), source="ticketmaster",
            score=score(e["name"], venue_name, bool(image), bool(desc))))
    return out


SKIDDLE_CODES = {"LIVE", "THEATRE", "COMEDY", "ARTS", "FEST", "EXHIB", "KIDS", "LIVE MUSIC"}

def from_skiddle(key, start, end):
    params = {
        "api_key": key, "latitude": OXFORD_LAT, "longitude": OXFORD_LON,
        "radius": round(RADIUS_KM * 0.621, 1), "limit": 100, "order": "date", "description": 1,
        "minDate": start.strftime("%Y-%m-%d"), "maxDate": end.strftime("%Y-%m-%d"),
        "imagefilter": 1,
    }
    data = http_json("https://www.skiddle.com/api/v1/events/search/?" + urlencode(params))
    out = []
    for e in data.get("results", []):
        if (e.get("EventCode") or "").upper() not in SKIDDLE_CODES:
            continue
        v = e.get("venue") or {}
        try:
            lat, lon = float(v["latitude"]), float(v["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not within_radius(lat, lon):
            continue
        doors = (e.get("openingtimes") or {}).get("doorsopen") or "00:00"
        try:
            st = datetime.fromisoformat(f"{e['date']}T{doors}").replace(tzinfo=LONDON)
        except (KeyError, ValueError):
            continue
        desc = clean(e.get("description"))
        out.append(event(
            id=make_id("sk", e.get("id")), name=e.get("eventname", ""), lat=lat, lon=lon,
            summary=v.get("name", ""), details=desc, venue=v.get("name"),
            address=", ".join(x for x in [v.get("address"), v.get("postcode")] if x),
            price=e.get("entryprice") or None, url=e.get("link"), image=e.get("largeimageurl"),
            free=str(e.get("entryprice", "")).strip().lower() in {"free", "£0", "0"},
            start=st, when=nice_when(st, all_day=doors == "00:00"), source="skiddle",
            score=score(e.get("eventname"), v.get("name"), True, bool(desc))))
    return out


def parse_ics(text):
    """Tiny iCal parser (VEVENT: SUMMARY, DTSTART, DTEND, DESCRIPTION, LOCATION, URL)."""
    text = re.sub(r"\r?\n[ \t]", "", text)           # unfold lines
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        ev = {}
        for line in block.strip().splitlines():
            if ":" not in line:
                continue
            k, val = line.split(":", 1)
            name, *params = k.split(";")
            val = val.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
            ev[name.upper()] = (val, ";".join(params))
        yield ev


def ics_time(value, params):
    v = value.strip()
    if re.fullmatch(r"\d{8}", v):
        return datetime.strptime(v, "%Y%m%d").replace(tzinfo=LONDON), True
    tz = timezone.utc if v.endswith("Z") else LONDON
    m = re.search(r"TZID=([^;:]+)", params or "")
    if m and not v.endswith("Z"):
        try:
            tz = ZoneInfo(m.group(1))
        except Exception:
            pass
    return datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=tz), False


def from_ics_sources(start, end):
    path = HERE / "sources.json"
    if not path.exists():
        return []
    out = []
    for src in json.loads(path.read_text()).get("ical", []):
        try:
            text = http_text(src["url"])
        except Exception as ex:
            print(f"  ! {src['name']}: {ex}", file=sys.stderr)
            continue
        include = re.compile(src["include"], re.I) if src.get("include") else None
        for ev in parse_ics(text):
            if "SUMMARY" not in ev or "DTSTART" not in ev:
                continue
            title = ev["SUMMARY"][0].strip()
            if include and not include.search(title + " " + ev.get("DESCRIPTION", ("", ""))[0]):
                continue
            st, all_day = ics_time(*ev["DTSTART"])
            en = ics_time(*ev["DTEND"])[0] if "DTEND" in ev else None
            if not (start <= st.astimezone(timezone.utc) <= end):
                continue
            desc = clean(ev.get("DESCRIPTION", ("", ""))[0])
            out.append(event(
                id=make_id("ics", src["name"], ev.get("UID", (title,))[0], st),
                name=title, lat=src["latitude"], lon=src["longitude"],
                summary=src.get("summary", src["name"]), details=desc or src.get("summary", ""),
                venue=src.get("venue", src["name"]),
                address=ev.get("LOCATION", (src.get("address", ""),))[0],
                price=src.get("price"), url=ev.get("URL", (src.get("website"),))[0],
                free=src.get("free", False), start=st, end=en,
                when=nice_when(st, en, all_day), source=src["name"],
                score=src.get("score", 2) + (1 if desc else 0)))
    return out


# ----------------------------------------------------------------- build

def build():
    now = datetime.now(timezone.utc)
    start, end = now, now + timedelta(days=DAYS_AHEAD)

    events = from_curated()
    print(f"curated: {len(events)}")

    if key := os.environ.get("TICKETMASTER_API_KEY"):
        try:
            tm = from_ticketmaster(key, start, end); events += tm; print(f"ticketmaster: {len(tm)}")
        except Exception as ex:
            print(f"  ! ticketmaster: {ex}", file=sys.stderr)
    if key := os.environ.get("SKIDDLE_API_KEY"):
        try:
            sk = from_skiddle(key, start, end); events += sk; print(f"skiddle: {len(sk)}")
        except Exception as ex:
            print(f"  ! skiddle: {ex}", file=sys.stderr)
    ics = from_ics_sources(start, end); events += ics; print(f"ical: {len(ics)}")

    # Quality gate: drop junk and late-night club nights (start 22:00–05:00)
    def late_night(e):
        if e["source"] == "curated" or not e.get("startsAt"):
            return False
        h = datetime.fromisoformat(e["startsAt"].replace("Z", "+00:00")).astimezone(LONDON).hour
        return h >= 22 or h < 5
    events = [e for e in events if e["_score"] >= 0 and e["name"] and not late_night(e)]

    # Collapse repeated shows (e.g. 20 nights of a panto) into one with a date range.
    groups = {}
    for e in events:
        k = (norm_title(e["name"]), (e.get("venue") or "").lower())
        groups.setdefault(k, []).append(e)
    merged = []
    for items in groups.values():
        items.sort(key=lambda e: e["startsAt"] or "9999")
        first = dict(items[0])
        if len(items) > MAX_DATES_PER_SHOW and items[0]["startsAt"] and items[-1]["startsAt"]:
            s = datetime.fromisoformat(items[0]["startsAt"].replace("Z", "+00:00"))
            l = datetime.fromisoformat(items[-1]["startsAt"].replace("Z", "+00:00"))
            if l.date() != s.date():
                first["when"] = nice_when(s, l)
                first["endsAt"] = items[-1]["startsAt"]
        merged.append(first)

    # Rank: curated first, then score, then soonest. Limit per venue + overall.
    merged.sort(key=lambda e: (-e["_score"], e["startsAt"] or "9999"))
    per_venue, final = {}, []
    for e in merged:
        v = venue_key(e.get("venue") or e["source"])
        if e["source"] != "curated" and per_venue.get(v, 0) >= MAX_PER_VENUE:
            continue
        per_venue[v] = per_venue.get(v, 0) + 1
        final.append(e)
        if len(final) >= MAX_EVENTS:
            break

    for e in final:
        e.pop("_score", None)
        for k in [k for k, v in e.items() if v is None]:
            e.pop(k)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": iso(now), "count": len(final), "events": final}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"wrote {len(final)} events → {OUT}")


if __name__ == "__main__":
    build()
