import requests
import re
import time
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

app = Flask(__name__)

# ========== CONFIGURATION ==========
CREDENTIALS = {"username": "Ak_78600", "password": "112233"}
BASE_URL = "http://51.89.99.105/NumberPanel"

# Endpoints (exactly as in Node.js original)
NUMBERS_URL = f"{BASE_URL}/agent/res/data_smsnumbers.php"
SMS_URL = f"{BASE_URL}/agent/res/data_smscdr.php"
REFERER_NUMBERS = f"{BASE_URL}/agent/MySMSNumbers2"
REFERER_SMS = f"{BASE_URL}/agent/SMSCDRStats"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE_URL,
    "Accept-Language": "en-US,en;q=0.9"
}

state = {"cookie": None, "sesskey": None, "last_login": 0}
SESSION_TTL = 3600

# ========== HELPER: EXTRACT SESSKEY FROM ANY HTML/JS ==========
def extract_sesskey(html, url=""):
    """Try multiple patterns to find sesskey in HTML, JS, or URL."""
    patterns = [
        r'sesskey=([a-f0-9]+)',                    # URL parameter
        r'sesskey["\s]*[:=][\s]*["\']([a-f0-9]+)["\']',  # JS variable assignment
        r'<input[^>]*name=["\']sesskey["\'][^>]*value=["\']([a-f0-9]+)["\']',  # form input
        r'sesskey["\s]*[:=][\s]*([a-f0-9]+)',      # without quotes
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    if url:
        m = re.search(r'sesskey=([a-f0-9]+)', url)
        if m:
            return m.group(1)
    return None

# ========== LOGIN ==========
def login():
    print("[LOGIN] Starting...")
    sess = requests.Session()
    sess.headers.update(HEADERS)

    # 1. Get login page + captcha
    r1 = sess.get(f"{BASE_URL}/login")
    if r1.status_code != 200:
        raise Exception(f"Login page failed: {r1.status_code}")
    captcha_match = re.search(r'What is (\d+) \+ (\d+) = \?', r1.text)
    if not captcha_match:
        raise Exception("Captcha not found")
    ans = int(captcha_match[1]) + int(captcha_match[2])

    # 2. Submit login
    r2 = sess.post(f"{BASE_URL}/signin", data={
        "username": CREDENTIALS["username"],
        "password": CREDENTIALS["password"],
        "capt": ans
    }, headers={"Referer": f"{BASE_URL}/login"}, allow_redirects=False)
    if r2.status_code not in (200, 302):
        raise Exception(f"Login POST failed: {r2.status_code}")

    # 3. Access a page that definitely contains the sesskey (try multiple)
    possible_pages = [
        f"{BASE_URL}/agent/MySMSNumbers2",
        f"{BASE_URL}/agent/SMSCDRStats",
        f"{BASE_URL}/agent/SMSDashboard",
        f"{BASE_URL}/dashboard"
    ]
    sesskey = None
    last_html = ""
    for page in possible_pages:
        try:
            r = sess.get(page, headers={"Referer": BASE_URL}, timeout=10)
            last_html = r.text
            sesskey = extract_sesskey(last_html, r.url)
            if sesskey:
                print(f"[LOGIN] sesskey found in {page}")
                break
        except:
            continue
    if not sesskey:
        # Debug: print first 500 chars of last response
        print(f"[LOGIN] Failed to extract sesskey. Response snippet:\n{last_html[:500]}")
        raise Exception("sesskey not found after login")

    # Store session
    state["sesskey"] = sesskey
    state["cookie"] = "; ".join([f"{c.name}={c.value}" for c in sess.cookies])
    state["last_login"] = time.time()
    print(f"[LOGIN] Success. sesskey={sesskey}")
    return sess

# ========== ENSURE SESSION ==========
def ensure_session():
    if not state["sesskey"] or (time.time() - state["last_login"]) > SESSION_TTL:
        login()

# ========== FETCH WITH AUTO-RELOGIN ==========
def fetch_with_relogin(url, referer):
    ensure_session()
    cookies = {}
    if state["cookie"]:
        for pair in state["cookie"].split("; "):
            if "=" in pair:
                k, v = pair.split("=", 1)
                cookies[k] = v
    for attempt in range(3):
        try:
            r = requests.get(url, headers={**HEADERS, "Cookie": state["cookie"], "Referer": referer}, timeout=15)
            if "id=\"loginform\"" in r.text or "Direct Script" in r.text:
                print(f"[FETCH] Session expired, relogging...")
                login()
                cookies = {}
                if state["cookie"]:
                    for pair in state["cookie"].split("; "):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            cookies[k] = v
                continue
            return r.text
        except Exception as e:
            print(f"[FETCH] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise
            time.sleep(2)
    raise Exception("Max retries exceeded")

# ========== API ==========
@app.route('/')
def index():
    typ = request.args.get('type')
    if typ not in ('numbers', 'sms'):
        return jsonify({"error": "Use ?type=numbers or ?type=sms"}), 400

    today = datetime.now().strftime("%Y-%m-%d")
    ts = int(time.time() * 1000)

    # Numbers endpoint (already working)
    if typ == 'numbers':
        url = f"{NUMBERS_URL}?frange=&fagent=&sEcho=2&iDisplayStart=0&iDisplayLength=-1&_={ts}"
        try:
            raw = fetch_with_relogin(url, REFERER_NUMBERS)
            data = json.loads(raw)
            if "aaData" in data:
                new_rows = []
                for row in data["aaData"]:
                    new_rows.append([
                        row[1] if len(row) > 1 else "",
                        "",
                        row[3] if len(row) > 3 else "",
                        (row[4] or "").replace("<[^>]+>", "").strip(),
                        (row[7] or "").replace("<[^>]+>", "").strip()
                    ])
                data["aaData"] = new_rows
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # SMS endpoint
    url = (f"{SMS_URL}?fdate1={today}%2000:00:00&fdate2={today}%2023:59:59"
           f"&frange=&fclient=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgclient=&fgnumber=&fgcli=&fg=0"
           f"&sesskey={state['sesskey']}&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
           f"&iDisplayStart=0&iDisplayLength=-1&mDataProp_0=0&sSearch_0=&bRegex_0=false&bSearchable_0=true&bSortable_0=true"
           f"&mDataProp_1=1&sSearch_1=&bRegex_1=false&bSearchable_1=true&bSortable_1=true"
           f"&mDataProp_2=2&sSearch_2=&bRegex_2=false&bSearchable_2=true&bSortable_2=true"
           f"&mDataProp_3=3&sSearch_3=&bRegex_3=false&bSearchable_3=true&bSortable_3=true"
           f"&mDataProp_4=4&sSearch_4=&bRegex_4=false&bSearchable_4=true&bSortable_4=true"
           f"&mDataProp_5=5&sSearch_5=&bRegex_5=false&bSearchable_5=true&bSortable_5=true"
           f"&mDataProp_6=6&sSearch_6=&bRegex_6=false&bSearchable_6=true&bSortable_6=true"
           f"&mDataProp_7=7&sSearch_7=&bRegex_7=false&bSearchable_7=true&bSortable_7=true"
           f"&mDataProp_8=8&sSearch_8=&bRegex_8=false&bSearchable_8=true&bSortable_8=false"
           f"&sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1&_={ts}")
    try:
        raw = fetch_with_relogin(url, REFERER_SMS)
        data = json.loads(raw)
        if "aaData" in data:
            filtered = []
            for row in data["aaData"]:
                msg = (row[5] or "").replace("kamibroken", "").strip()
                if msg:
                    filtered.append([row[0], row[1], row[2], row[3], msg, "$", row[7] if len(row)>7 else 0])
            data["aaData"] = filtered
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== INITIAL LOGIN ==========
if __name__ != "__main__":
    # For Vercel, run login at startup
    try:
        login()
    except Exception as e:
        print(f"Initial login error: {e}")

if __name__ == "__main__":
    try:
        login()
    except:
        pass
    app.run(debug=True)
