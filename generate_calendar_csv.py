import requests
import json
import datetime
from dateutil.parser import parse
import os

GCAL_API_KEY = os.getenv("GCAL_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

# Config from your HTML
SHEET_URL = "https://script.google.com/macros/s/AKfycbzcqHOQUDSFqSmQ2vRA44DRS2DostY9shUyEZLFRy1F3WkBCSiK5PlNNwUmOA5U7hrlaQ/exec?year=2025"
GCAL_URL = f"https://www.googleapis.com/calendar/v3/calendars/a6593804dfea896d39158db12ee0af1f88cc01644db51df4c12ba3c9abdbd370@group.calendar.google.com/events?key={GCAL_API_KEY}&singleEvents=true&orderBy=startTime&timeMin=2025-01-01T00:00:00Z&timeMax=2025-12-31T23:59:59Z"
POLYGON_URL = f"https://api.polygon.io/v1/marketstatus/upcoming?apiKey={POLYGON_API_KEY}"
CURRENT_DATE = datetime.date(2025, 8, 26)  # Your current date
TZ = "America/Phoenix"

# Type to color map (from your HTML)
TYPE_TO_COLOR = {
    'holiday': '#ffd700',
    'early': '#ffa500',
    'expire': '#ff4d4f',
    'qexpire': '#ff85c0',
    'user': '#8a2be2'
}

# Name to ID map (expand as needed for your events; used for encoding)
NAME_TO_ID = {
    'Labor Day': 1,
    'Thanksgiving': 2,
    'Thanksgiving (Early Close)': 3,
    'Christmas': 4,
    'Christmas (Early Close)': 5,
    'Monthly Expiration': 6,
    'Quarterly Expiration': 7,
    'User Event': 8  # Generic for user
    # Add more for new events
}
ID_TO_NAME = {v: k for k, v in NAME_TO_ID.items()}

# Color to ID map
COLOR_TO_ID = {
    '#ffd700': 1,  # holiday
    '#ffa500': 2,  # early
    '#ff4d4f': 3,  # expire
    '#ff85c0': 4,  # qexpire
    '#8a2be2': 5   # user
}

def fetch_sheet():
    try:
        resp = requests.get(SHEET_URL)
        data = resp.json()
        events = []
        for row in data:
            date_str = row.get('date')
            if not date_str:
                continue
            date = parse(date_str).date()
            if date <= CURRENT_DATE:
                continue
            typ = row.get('type', '').lower()
            note = row.get('note', '').strip()
            early_time = row.get('early_close_time', '')
            extra = row.get('extra_note', '')
            details = [note or typ.capitalize()]
            if early_time:
                details.append(f"Close Time: {early_time}")
            if extra:
                details.append(extra)
            events.append({'date': date, 'type': typ, 'details': '\n'.join(details)})
        return events
    except Exception as e:
        print(f"Sheet fetch failed: {e}")
        return []

def fetch_gcal():
    try:
        resp = requests.get(GCAL_URL)
        data = resp.json()
        items = data.get('items', [])
        events = []
        for ev in items:
            start_str = ev.get('start', {}).get('date') or ev.get('start', {}).get('dateTime')
            if not start_str:
                continue
            start = parse(start_str).date()
            if start <= CURRENT_DATE:
                continue
            end_str = ev.get('end', {}).get('date')
            end = parse(end_str).date() if end_str else start
            # Expand multi-day, but for all-day holidays, use start
            summary = ev.get('summary', '').strip()
            desc = ev.get('description', '').strip()
            details = [summary, desc] if desc else [summary]
            typ = 'user' if 'user' in summary.lower() else 'holiday' if 'closed' in summary else 'early'
            events.append({'date': start, 'type': typ, 'details': '\n'.join(details)})
        return events
    except Exception as e:
        print(f"GCal fetch failed: {e}")
        return []

def fetch_polygon():
    try:
        resp = requests.get(POLYGON_URL)
        data = resp.json()
        events = []
        seen = set()
        for it in data:
            date_str = it.get('date')
            if not date_str or '2025' not in date_str:
                continue
            date = parse(date_str).date()
            if date <= CURRENT_DATE:
                continue
            name = it.get('name', '').strip()
            status = it.get('status', '').lower()
            typ = 'early' if 'early' in status else 'holiday'
            key = f"{date}_{typ}_{name}"
            if key in seen:
                continue
            seen.add(key)
            details = name
            events.append({'date': date, 'type': typ, 'details': details})
        return events
    except Exception as e:
        print(f"Polygon fetch failed: {e}")
        return []

def calculate_expirations(year=2025):
    expirations = []
    for month in range(1, 13):
        d = datetime.date(year, month, 1)
        while d.weekday() != 4:  # Friday
            d += datetime.timedelta(1)
        third_friday = d + datetime.timedelta(14)  # To 3rd Friday
        if third_friday.month != month:
            third_friday -= datetime.timedelta(7)
        if third_friday <= CURRENT_DATE:
            continue
        typ = 'qexpire' if month in [3, 6, 9, 12] else 'expire'
        details = 'Quarterly Expiration' if typ == 'qexpire' else 'Monthly Expiration'
        expirations.append({'date': third_friday, 'type': typ, 'details': details})
    return expirations

def sanitize_details(details):
    details = details.replace('[Market] ', '').replace(' (closed)', '').replace(' (early-close)', '').replace('[polygon] ', '').strip()
    return details

def merge_events(sheet, gcal, poly, exps):
    by_date = {}
    all_events = sheet + gcal + poly + exps
    for ev in all_events:
        date_str = ev['date'].strftime('%Y-%m-%d')
        typ = ev['type']
        details = sanitize_details(ev['details'])
        key = f"{date_str}_{typ}_{details}"
        if date_str not in by_date:
            by_date[date_str] = []
        if key not in [f"{date_str}_{e['type']}_{e['details']}" for e in by_date[date_str]]:
            by_date[date_str].append({'type': typ, 'details': details})
    # Flatten to list of unique events
    merged = []
    for date_str, specials in sorted(by_date.items()):
        for s in specials:
            merged.append({'date': date_str, 'type': s['type'], 'details': s['details']})
    return merged

def encode_event(ev):
    date = parse(ev['date'])
    year, month, day = date.year, date.month, date.day
    typ_id = {'holiday': 1, 'early': 2, 'expire': 3, 'qexpire': 4, 'user': 5}.get(ev['type'], 0)
    color_id = COLOR_TO_ID.get(TYPE_TO_COLOR.get(ev['type'], '#000000'), 0)
    name_id = NAME_TO_ID.get(ev['details'], 0)  # 0 for unknown
    # Encoding: open = year*10000 + month*100 + day
    o = float(year * 10000 + month * 100 + day)
    h = 0.0  # Hour/minute not used; default to 0
    l = float(typ_id)
    c = float(color_id)
    v = float(name_id)
    return ev['date'], o, h, l, c, v

# Main
sheet_events = fetch_sheet()
gcal_events = fetch_gcal()
poly_events = fetch_polygon()
exp_events = calculate_expirations()  # Add if not in sources
merged = merge_events(sheet_events, gcal_events, poly_events, exp_events)

# Generate CSV
with open('calendar_events.csv', 'w') as f:
    f.write("timestamp,open,high,low,close,volume\n")
    for ev in merged:
        ts, o, h, l, c, v = encode_event(ev)
        f.write(f"{ts},{o},{h},{l},{c},{v}\n")

print("CSV generated: calendar_events.csv")
print(f"Upcoming events encoded: {len(merged)}")