import requests
import re
import time
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from functools import lru_cache

app = Flask(__name__)

# ========== PANEL CONFIGURATION ==========
PANELS = [
    {
        "name": "Panel1",
        "base_url": "http://51.89.99.105/NumberPanel",
        "numbers_endpoint": "/agent/res/data_smsnumbers.php",
        "referer": "/agent/MySMSNumbers2",
        "credentials": {"username": "Ak_78600", "password": "112233"}
    },
    {
        "name": "KonektPremium",
        "base_url": "https://konektapremium.net",
        "numbers_endpoint": "/agent/MySMSNumbers",  # as provided
        "referer": "/agent/MySMSNumbers",
        "credentials": {"username": "your_username", "password": "your_password"}  # you need to provide
    }
]

# Country mapping based on phone prefix (ISO 3166-1)
COUNTRY_MAP = {
    "1": "US/CA", "44": "UK", "92": "Pakistan", "91": "India", "58": "Venezuela",
    "93": "Afghanistan", "355": "Albania", "213": "Algeria", "376": "Andorra",
    # add more as needed
}

def get_country(phone):
    """Return country name based on phone prefix (longest match first)."""
    s = str(phone).lstrip('+')
    for length in range(4, 0, -1):
        prefix = s[:length]
        if prefix in COUNTRY_MAP:
            return COUNTRY_MAP[prefix]
    return "Global"

# ========== PANEL LOGIN (same as before, now reusable) ==========
def login_panel(panel):
    """Login to a panel and return (session, sesskey, cookie)."""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": panel["base_url"],
        "Accept-Language": "en-US,en;q=0.9"
    })
    # Step 1: get login page
    r1 = sess.get(f"{panel['base_url']}/login")
    captcha_match = re.search(r'What is (\d+) \+ (\d+) = \?', r1.text)
    if not captcha_match:
        raise Exception(f"Captcha not found for {panel['name']}")
    ans = int(captcha_match[1]) + int(captcha_match[2])
    # Step 2: login
    r2 = sess.post(f"{panel['base_url']}/signin", data={
        "username": panel["credentials"]["username"],
        "password": panel["credentials"]["password"],
        "capt": ans
    }, headers={"Referer": f"{panel['base_url']}/login"}, allow_redirects=False)
    if r2.status_code not in (200, 302):
        raise Exception(f"Login failed for {panel['name']}")
    # Step 3: extract sesskey from numbers page
    r3 = sess.get(f"{panel['base_url']}{panel['numbers_endpoint']}", headers={"Referer": panel["base_url"]})
    match = re.search(r'sesskey=([a-f0-9]+)', r3.text)
    if not match:
        match = re.search(r"sesskey['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", r3.text)
    if not match:
        raise Exception(f"sesskey not found for {panel['name']}")
    sesskey = match.group(1)
    cookie = "; ".join([f"{c.name}={c.value}" for c in sess.cookies])
    return sess, sesskey, cookie

# ========== FETCH NUMBERS FROM A SINGLE PANEL ==========
def fetch_numbers_from_panel(panel):
    try:
        sess, sesskey, cookie = login_panel(panel)
        ts = int(time.time() * 1000)
        url = (f"{panel['base_url']}{panel['numbers_endpoint']}"
               f"?frange=&fagent=&sEcho=2&iDisplayStart=0&iDisplayLength=-1&_={ts}")
        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": cookie,
            "Referer": f"{panel['base_url']}{panel['referer']}"
        }
        r = sess.get(url, headers=headers, timeout=15)
        if "id=\"loginform\"" in r.text:
            raise Exception("Session expired")
        data = r.json()
        numbers = []
        for row in data.get("aaData", []):
            phone = row[3] if len(row) > 3 else ""
            plan = row[4] if len(row) > 4 else ""
            if phone:
                numbers.append({
                    "source": panel["name"],
                    "phone": phone,
                    "plan": plan,
                    "country": get_country(phone)
                })
        return numbers
    except Exception as e:
        print(f"Error fetching from {panel['name']}: {e}")
        return []

# ========== CACHED COMBINED RESULT ==========
cache = {"data": None, "last_fetch": 0}
CACHE_TTL = 60  # seconds

@app.route('/')
def get_all_numbers():
    # Return cached result if fresh
    now = time.time()
    if cache["data"] and (now - cache["last_fetch"]) < CACHE_TTL:
        return jsonify({
            "success": True,
            "cache": True,
            "count": len(cache["data"]),
            "numbers": cache["data"]
        })
    
    all_numbers = []
    for panel in PANELS:
        numbers = fetch_numbers_from_panel(panel)
        all_numbers.extend(numbers)
    
    # Update cache
    cache["data"] = all_numbers
    cache["last_fetch"] = now
    
    return jsonify({
        "success": True,
        "cache": False,
        "count": len(all_numbers),
        "numbers": all_numbers
    })

# ========== RUN ==========
if __name__ == "__main__":
    app.run(debug=True)
