import requests
import re
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify
from threading import Timer

app = Flask(__name__)

# ========== CONFIGURATION ==========
CREDENTIALS = {
    "username": "Ak_78600",
    "password": "112233"
}
BASE_URL = "http://51.89.99.105/NumberPanel"
STATS_PAGE_URL = BASE_URL + "/agent/SMSCDRStats2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE_URL,
    "Accept-Language": "en-US,en;q=0.9,ur-PK;q=0.8,ur;q=0.7"
}

CACHE_TTL = 16          # seconds
SESSION_TTL = 60 * 60   # 1 hour (seconds)

# ========== GLOBAL STATE ==========
state = {
    "last_login": 0,
    "cookie": None,
    "sesskey": None
}

# SMS cache (accumulative per day)
sms_cache = {
    "all_data": [],
    "seen_ids": set(),
    "last_fetch": 0,
    "date": None
}
numbers_cache = {
    "data": None,
    "last_fetch": 0,
    "date": None
}

# ========== HELPERS ==========
def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def extract_sesskey(html):
    match = re.search(r'sesskey=([^&"\']+)', html)
    if match:
        return match[1]
    match = re.search(r'sesskey\s*[:=]\s*["\']([^"\']+)["\']', html)
    if match:
        return match[1]
    return None

# ========== LOGIN ==========
def login():
    print("[LOGIN] Starting login...")
    session = requests.Session()
    session.headers.update(HEADERS)

    # Step 1: Get login page (captcha)
    r1 = session.get(f"{BASE_URL}/login")
    if r1.status_code != 200:
        raise Exception(f"Failed to load login page: {r1.status_code}")

    # Extract captcha (e.g., "What is 12 + 34 = ?")
    captcha_match = re.search(r'What is (\d+) \+ (\d+) = \?', r1.text)
    if not captcha_match:
        raise Exception("Captcha not found in login page")
    ans = int(captcha_match[1]) + int(captcha_match[2])
    print(f"[LOGIN] Captcha: {ans}")

    # Step 2: Submit login
    r2 = session.post(f"{BASE_URL}/signin", data={
        "username": CREDENTIALS["username"],
        "password": CREDENTIALS["password"],
        "capt": ans
    }, headers={"Referer": f"{BASE_URL}/login"}, allow_redirects=False)

    if r2.status_code not in (200, 302):
        raise Exception(f"Login POST failed: {r2.status_code}")

    # Step 3: Access stats page to extract sesskey
    r3 = session.get(STATS_PAGE_URL, headers={"Referer": f"{BASE_URL}/agent/SMSDashboard"})
    if "id=\"loginform\"" in r3.text:
        raise Exception("Login rejected – wrong credentials or captcha")

    sesskey = extract_sesskey(r3.text)
    if not sesskey:
        raise Exception("sesskey not found after login")
    state["sesskey"] = sesskey
    state["cookie"] = "; ".join([f"{c.name}={c.value}" for c in session.cookies])
    state["last_login"] = time.time()
    print(f"[LOGIN] Success. sesskey={sesskey}")
    return session

def ensure_login():
    if not state["cookie"] or not state["sesskey"] or (time.time() - state["last_login"]) > SESSION_TTL:
        print("[LOGIN] Session expired or missing – refreshing...")
        login()

def fetch_with_relogin(url_func, referer):
    for attempt in range(1, 4):
        try:
            ensure_login()
            url = url_func() if callable(url_func) else url_func
            cookies = {}
            if state["cookie"]:
                for pair in state["cookie"].split("; "):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        cookies[k] = v
            r = requests.get(url, headers={
                **HEADERS,
                "Cookie": state["cookie"],
                "Referer": referer
            }, timeout=20)
            if "Direct Script" in r.text or "id=\"loginform\"" in r.text:
                print(f"[FETCH] Session expired (attempt {attempt}/3) – relogging...")
                state["cookie"] = None
                state["sesskey"] = None
                login()
                continue
            return r.text
        except Exception as e:
            print(f"[FETCH] Error attempt {attempt}: {e}")
            if attempt == 3:
                raise
            time.sleep(2)
    raise Exception("Max retries exceeded")

# ========== DATA PARSING ==========
def fix_numbers(data):
    # Input: { "aaData": [[...]] }
    if "aaData" not in data:
        return data
    fixed = []
    for row in data["aaData"]:
        # row[1] = number_id? row[3] = phone number, row[4] = range, row[7] = status
        fixed.append([
            row[1] if len(row) > 1 else "",
            "",
            row[3] if len(row) > 3 else "",
            (row[4] or "").replace("<[^>]+>", "").strip(),
            (row[7] or "").replace("<[^>]+>", "").strip()
        ])
    data["aaData"] = fixed
    return data

def fix_sms(data):
    if "aaData" not in data:
        return data
    fixed = []
    for row in data["aaData"]:
        msg = (row[5] or "").replace("kamibroken", "").strip()
        if not msg:
            continue
        fixed.append([
            row[0], row[1], row[2], row[3], msg, "$", row[7] if len(row) > 7 else 0
        ])
    data["aaData"] = fixed
    return data

def accumulate_sms(new_rows):
    added = 0
    for row in new_rows:
        sid = row[0]  # first column is ID
        if sid not in sms_cache["seen_ids"]:
            sms_cache["seen_ids"].add(sid)
            sms_cache["all_data"].append(row)
            added += 1
    if added:
        print(f"[SMS] Added {added} new SMS. Total: {len(sms_cache['all_data'])}")

# ========== API ROUTES ==========
@app.route('/', methods=['GET'])
def api():
    type_param = request.args.get('type')
    if type_param not in ('sms', 'numbers'):
        return jsonify({"error": "Use ?type=sms or ?type=numbers"}), 400

    today = get_today()
    now = time.time()

    if type_param == 'numbers':
        # Check date change
        if numbers_cache["date"] and numbers_cache["date"] != today:
            numbers_cache["data"] = None
            numbers_cache["last_fetch"] = 0
            numbers_cache["date"] = None
        # Cache hit
        if numbers_cache["data"] and (now - numbers_cache["last_fetch"]) < CACHE_TTL:
            return jsonify(numbers_cache["data"])
        # Fetch fresh
        try:
            url = f"{BASE_URL}/agent/res/data_smsnumbers.php?frange=&fagent=&sEcho=2&iDisplayStart=0&iDisplayLength=-1&_={int(now*1000)}"
            referer = f"{BASE_URL}/agent/MySMSNumbers2"
            raw = fetch_with_relogin(url, referer)
            data = json.loads(raw)
            data = fix_numbers(data)
            if data.get("aaData") and len(data["aaData"]) > 0:
                numbers_cache["data"] = data
                numbers_cache["last_fetch"] = now
                numbers_cache["date"] = today
            else:
                # fallback to cache if available
                if numbers_cache["data"]:
                    return jsonify(numbers_cache["data"])
            return jsonify(data)
        except Exception as e:
            print(f"[ERROR] Numbers: {e}")
            if numbers_cache["data"]:
                return jsonify(numbers_cache["data"])
            return jsonify({"error": str(e)}), 500

    # SMS
    if sms_cache["date"] and sms_cache["date"] != today:
        sms_cache["all_data"] = []
        sms_cache["seen_ids"] = set()
        sms_cache["last_fetch"] = 0
        sms_cache["date"] = None

    # Cache hit (within TTL)
    if sms_cache["date"] and (now - sms_cache["last_fetch"]) < CACHE_TTL:
        return jsonify({
            "sEcho": 1,
            "iTotalRecords": len(sms_cache["all_data"]),
            "iTotalDisplayRecords": len(sms_cache["all_data"]),
            "aaData": sms_cache["all_data"]
        })

    # Fetch fresh
    try:
        ts = int(now * 1000)
        url = (f"{BASE_URL}/agent/res/data_smscdr.php?fdate1={today}%2000:00:00&fdate2={today}%2023:59:59"
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
        referer = f"{BASE_URL}/agent/SMSCDRStats"
        raw = fetch_with_relogin(url, referer)
        data = json.loads(raw)
        data = fix_sms(data)
        new_rows = data.get("aaData", [])
        if new_rows:
            accumulate_sms(new_rows)
        sms_cache["last_fetch"] = now
        sms_cache["date"] = today
        # build response
        response = {
            "sEcho": 1,
            "iTotalRecords": len(sms_cache["all_data"]),
            "iTotalDisplayRecords": len(sms_cache["all_data"]),
            "aaData": sms_cache["all_data"]
        }
        return jsonify(response)
    except Exception as e:
        print(f"[ERROR] SMS: {e}")
        if sms_cache["all_data"]:
            return jsonify({
                "sEcho": 1,
                "iTotalRecords": len(sms_cache["all_data"]),
                "iTotalDisplayRecords": len(sms_cache["all_data"]),
                "aaData": sms_cache["all_data"]
            })
        return jsonify({"error": str(e)}), 500

# ========== AUTO-RELOGIN SCHEDULER (runs every hour) ==========
def schedule_relogin():
    now = datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    delay = (next_hour - now).total_seconds()
    print(f"[SCHED] Next auto relogin at {next_hour.strftime('%H:%M:%S')} (in {delay:.0f}s)")
    Timer(delay, auto_relogin).start()

def auto_relogin():
    print("[SCHED] Auto relogin triggered...")
    state["cookie"] = None
    state["sesskey"] = None
    try:
        login()
    except Exception as e:
        print(f"[SCHED] Auto relogin failed: {e}")
    schedule_relogin()

# Start the scheduler after first login
try:
    login()
    schedule_relogin()
except Exception as e:
    print(f"Initial login error: {e}")

# For Vercel (serverless) we expose app
# The scheduler will run only when the instance is alive – may not persist,
# but login will be re‑attempted on each request if needed.
