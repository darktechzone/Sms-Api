import requests
import re
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ========== PANEL CONFIGURATION ==========
PANELS = {
    "Panel1": {
        "name": "Panel1",
        "base_url": "http://51.89.99.105/NumberPanel",
        "numbers_endpoint": "/agent/res/data_smsnumbers.php",
        "referer": "/agent/MySMSNumbers2",
        "credentials": {"username": "Ak_78600", "password": "112233"}
    },
    "KonektPremium": {
        "name": "KonektPremium",
        "base_url": "https://konektapremium.net",
        "numbers_endpoint": "/agent/MySMSNumbers",
        "referer": "/agent/MySMSNumbers",
        "credentials": {"username": "your_username", "password": "your_password"}  # <-- UPDATE
    }
}

COUNTRY_MAP = {
    "1": "US/CA", "44": "UK", "92": "Pakistan", "91": "India", "58": "Venezuela",
    # add more as needed
}

def get_country(phone):
    s = str(phone).lstrip('+')
    for length in range(4, 0, -1):
        prefix = s[:length]
        if prefix in COUNTRY_MAP:
            return COUNTRY_MAP[prefix]
    return "Global"

# ========== PANEL LOGIN (with detailed logging) ==========
def login_panel(panel_key):
    panel = PANELS[panel_key]
    print(f"[LOGIN] Trying {panel_key} at {panel['base_url']}")
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": panel["base_url"],
        "Accept-Language": "en-US,en;q=0.9"
    })
    
    # Step 1: get login page
    try:
        r1 = sess.get(f"{panel['base_url']}/login", timeout=10)
    except Exception as e:
        raise Exception(f"Cannot fetch login page: {e}")
    
    captcha_match = re.search(r'What is (\d+) \+ (\d+) = \?', r1.text)
    if not captcha_match:
        raise Exception(f"Captcha not found in {panel_key}")
    ans = int(captcha_match[1]) + int(captcha_match[2])
    print(f"[LOGIN] {panel_key} captcha answer: {ans}")
    
    # Step 2: submit login
    r2 = sess.post(f"{panel['base_url']}/signin", data={
        "username": panel["credentials"]["username"],
        "password": panel["credentials"]["password"],
        "capt": ans
    }, headers={"Referer": f"{panel['base_url']}/login"}, allow_redirects=False)
    
    if r2.status_code not in (200, 302):
        raise Exception(f"Login POST returned {r2.status_code}")
    
    # Step 3: get numbers page to extract sesskey
    numbers_url = f"{panel['base_url']}{panel['numbers_endpoint']}"
    r3 = sess.get(numbers_url, headers={"Referer": panel["base_url"]}, timeout=10)
    
    # Debug: print first 500 chars if sesskey missing
    match = re.search(r'sesskey=([a-f0-9]+)', r3.text)
    if not match:
        match = re.search(r"sesskey['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", r3.text)
    if not match:
        # print snippet
        print(f"[LOGIN] Failed to find sesskey. Response snippet:\n{r3.text[:500]}")
        raise Exception("sesskey not found")
    sesskey = match.group(1)
    
    cookie = "; ".join([f"{c.name}={c.value}" for c in sess.cookies])
    print(f"[LOGIN] {panel_key} success, sesskey={sesskey}")
    return sess, sesskey, cookie

# ========== FETCH NUMBERS FROM ONE PANEL ==========
def fetch_numbers_from_panel(panel_key):
    panel = PANELS[panel_key]
    try:
        sess, sesskey, cookie = login_panel(panel_key)
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
            raise Exception("Session expired after login")
        
        # Try to parse JSON
        try:
            data = r.json()
        except:
            print(f"[ERROR] {panel_key} – Response not JSON:\n{r.text[:500]}")
            return []
        
        numbers = []
        for row in data.get("aaData", []):
            # Based on original Node.js, phone is at index 3, plan at index 4
            phone = row[3] if len(row) > 3 else ""
            plan = row[4] if len(row) > 4 else ""
            if phone:
                numbers.append({
                    "source": panel["name"],
                    "phone": phone,
                    "plan": plan,
                    "country": get_country(phone)
                })
        print(f"[SUCCESS] {panel_key} fetched {len(numbers)} numbers")
        return numbers
    except Exception as e:
        print(f"[ERROR] {panel_key}: {e}")
        return []

# ========== API ENDPOINTS ==========
cache = {"data": None, "last_fetch": 0}
CACHE_TTL = 60

@app.route('/')
def get_all_numbers():
    now = time.time()
    if cache["data"] and (now - cache["last_fetch"]) < CACHE_TTL:
        return jsonify({
            "success": True,
            "cached": True,
            "count": len(cache["data"]),
            "numbers": cache["data"]
        })
    
    all_numbers = []
    for panel_key in PANELS:
        numbers = fetch_numbers_from_panel(panel_key)
        all_numbers.extend(numbers)
    
    cache["data"] = all_numbers
    cache["last_fetch"] = now
    
    return jsonify({
        "success": True,
        "cached": False,
        "count": len(all_numbers),
        "numbers": all_numbers
    })

@app.route('/test')
def test_panel():
    panel = request.args.get('panel')
    if panel not in PANELS:
        return jsonify({"error": "Valid panels: " + ", ".join(PANELS.keys())})
    numbers = fetch_numbers_from_panel(panel)
    return jsonify({
        "panel": panel,
        "count": len(numbers),
        "numbers": numbers
    })

if __name__ == "__main__":
    app.run(debug=True)
