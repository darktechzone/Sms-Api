import requests
import re
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ========== CONFIGURATION ==========
BASE_URL = "http://51.89.99.105/NumberPanel"
CREDENTIALS = {"username": "Ak_78600", "password": "112233"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE_URL,
    "Accept-Language": "en-US,en;q=0.9"
}

# Country mapping by prefix (add as needed)
COUNTRY_MAP = {
    "1": "US/Canada",
    "44": "UK",
    "92": "Pakistan",
    "91": "India",
    "58": "Venezuela",
    "93": "Afghanistan",
    "355": "Albania",
    "213": "Algeria",
    "376": "Andorra",
    "244": "Angola",
    "54": "Argentina",
    "374": "Armenia",
    "61": "Australia",
    "43": "Austria",
    "994": "Azerbaijan",
    "880": "Bangladesh",
    "375": "Belarus",
    "32": "Belgium",
    "55": "Brazil",
    "359": "Bulgaria",
    "855": "Cambodia",
    "237": "Cameroon",
    "56": "Chile",
    "86": "China",
    "57": "Colombia",
    "506": "Costa Rica",
    "385": "Croatia",
    "53": "Cuba",
    "357": "Cyprus",
    "420": "Czech Republic",
    "45": "Denmark",
    "593": "Ecuador",
    "20": "Egypt",
    "503": "El Salvador",
    "372": "Estonia",
    "251": "Ethiopia",
    "679": "Fiji",
    "358": "Finland",
    "33": "France",
    "241": "Gabon",
    "220": "Gambia",
    "995": "Georgia",
    "49": "Germany",
    "233": "Ghana",
    "30": "Greece",
    "502": "Guatemala",
    "224": "Guinea",
    "509": "Haiti",
    "504": "Honduras",
    "852": "Hong Kong",
    "36": "Hungary",
    "354": "Iceland",
    "62": "Indonesia",
    "98": "Iran",
    "964": "Iraq",
    "353": "Ireland",
    "972": "Israel",
    "39": "Italy",
    "81": "Japan",
    "962": "Jordan",
    "7": "Kazakhstan",
    "254": "Kenya",
    "965": "Kuwait",
    "996": "Kyrgyzstan",
    "856": "Laos",
    "371": "Latvia",
    "961": "Lebanon",
    "218": "Libya",
    "423": "Liechtenstein",
    "370": "Lithuania",
    "352": "Luxembourg",
    "853": "Macau",
    "389": "North Macedonia",
    "261": "Madagascar",
    "265": "Malawi",
    "60": "Malaysia",
    "960": "Maldives",
    "223": "Mali",
    "356": "Malta",
    "596": "Martinique",
    "222": "Mauritania",
    "230": "Mauritius",
    "52": "Mexico",
    "373": "Moldova",
    "377": "Monaco",
    "976": "Mongolia",
    "382": "Montenegro",
    "212": "Morocco",
    "258": "Mozambique",
    "95": "Myanmar",
    "264": "Namibia",
    "977": "Nepal",
    "31": "Netherlands",
    "64": "New Zealand",
    "505": "Nicaragua",
    "227": "Niger",
    "234": "Nigeria",
    "47": "Norway",
    "968": "Oman",
    "507": "Panama",
    "675": "Papua New Guinea",
    "595": "Paraguay",
    "51": "Peru",
    "63": "Philippines",
    "48": "Poland",
    "351": "Portugal",
    "974": "Qatar",
    "40": "Romania",
    "250": "Rwanda",
    "966": "Saudi Arabia",
    "221": "Senegal",
    "381": "Serbia",
    "65": "Singapore",
    "421": "Slovakia",
    "386": "Slovenia",
    "27": "South Africa",
    "82": "South Korea",
    "34": "Spain",
    "94": "Sri Lanka",
    "249": "Sudan",
    "46": "Sweden",
    "41": "Switzerland",
    "963": "Syria",
    "886": "Taiwan",
    "255": "Tanzania",
    "66": "Thailand",
    "228": "Togo",
    "216": "Tunisia",
    "90": "Turkey",
    "993": "Turkmenistan",
    "256": "Uganda",
    "380": "Ukraine",
    "971": "UAE",
    "598": "Uruguay",
    "998": "Uzbekistan",
    "58": "Venezuela",
    "84": "Vietnam",
    "967": "Yemen",
    "260": "Zambia",
    "263": "Zimbabwe"
}

def get_country(phone):
    s = str(phone).lstrip('+')
    for length in range(4, 0, -1):
        prefix = s[:length]
        if prefix in COUNTRY_MAP:
            return COUNTRY_MAP[prefix]
    return "Global"

def get_numbers():
    """Fetch numbers from the panel using the same logic as your original working script."""
    session = requests.Session()
    session.headers.update(HEADERS)

    # Step 1: Get login page + captcha
    r1 = session.get(f"{BASE_URL}/login")
    if r1.status_code != 200:
        raise Exception("Failed to load login page")
    m = re.search(r'What is (\d+) \+ (\d+) = \?', r1.text)
    if not m:
        raise Exception("Captcha not found")
    ans = int(m[1]) + int(m[2])

    # Step 2: Submit login
    r2 = session.post(f"{BASE_URL}/signin", data={
        "username": CREDENTIALS["username"],
        "password": CREDENTIALS["password"],
        "capt": ans
    }, headers={"Referer": f"{BASE_URL}/login"}, allow_redirects=False)
    if r2.status_code not in (200, 302):
        raise Exception("Login failed")

    # Step 3: Fetch numbers (as in your original Node.js)
    ts = int(time.time() * 1000)
    url = f"{BASE_URL}/agent/res/data_smsnumbers.php?frange=&fagent=&sEcho=2&iDisplayStart=0&iDisplayLength=-1&_={ts}"
    r3 = session.get(url, headers={"Referer": f"{BASE_URL}/agent/MySMSNumbers2"})
    if "id=\"loginform\"" in r3.text:
        raise Exception("Session expired")
    data = r3.json()

    numbers = []
    for row in data.get("aaData", []):
        phone = row[3] if len(row) > 3 else ""
        plan = row[4] if len(row) > 4 else ""
        if phone:
            numbers.append({
                "phone": phone,
                "plan": plan,
                "country": get_country(phone)
            })
    return numbers

# ========== CACHING ==========
cache = {"data": None, "last_fetch": 0}
CACHE_TTL = 60  # seconds

@app.route('/')
def index():
    now = time.time()
    if cache["data"] and (now - cache["last_fetch"]) < CACHE_TTL:
        return jsonify({
            "success": True,
            "cached": True,
            "count": len(cache["data"]),
            "numbers": cache["data"]
        })
    try:
        numbers = get_numbers()
        cache["data"] = numbers
        cache["last_fetch"] = now
        return jsonify({
            "success": True,
            "cached": False,
            "count": len(numbers),
            "numbers": numbers
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run()
