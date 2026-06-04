import requests
import re
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_URL = "http://51.89.99.105/NumberPanel"
CREDENTIALS = {"username": "Ak_78600", "password": "112233"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE_URL,
    "Accept-Language": "en-US,en;q=0.9"
}

def get_numbers():
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. Get login page + captcha
    r1 = session.get(f"{BASE_URL}/login")
    if r1.status_code != 200:
        raise Exception(f"Login page failed: {r1.status_code}")
    m = re.search(r'What is (\d+) \+ (\d+) = \?', r1.text)
    if not m:
        raise Exception("Captcha not found")
    ans = int(m[1]) + int(m[2])
    print(f"Captcha answer: {ans}")

    # 2. Submit login
    r2 = session.post(f"{BASE_URL}/signin", data={
        "username": CREDENTIALS["username"],
        "password": CREDENTIALS["password"],
        "capt": ans
    }, headers={"Referer": f"{BASE_URL}/login"}, allow_redirects=False)
    print(f"Login POST status: {r2.status_code}")

    # 3. Fetch numbers endpoint
    ts = int(time.time() * 1000)
    url = f"{BASE_URL}/agent/res/data_smsnumbers.php?frange=&fagent=&sEcho=2&iDisplayStart=0&iDisplayLength=-1&_={ts}"
    r3 = session.get(url, headers={"Referer": f"{BASE_URL}/agent/MySMSNumbers2"})
    print(f"Numbers endpoint status: {r3.status_code}")
    print(f"Response preview: {r3.text[:200]}")

    if "id=\"loginform\"" in r3.text:
        raise Exception("Session expired – need to relogin")
    
    # Try to parse JSON
    try:
        data = r3.json()
    except:
        raise Exception(f"Response not JSON: {r3.text[:500]}")
    
    numbers = []
    for row in data.get("aaData", []):
        phone = row[3] if len(row) > 3 else ""
        plan = row[4] if len(row) > 4 else ""
        if phone:
            numbers.append({"phone": phone, "plan": plan})
    return numbers

@app.route('/')
def index():
    try:
        numbers = get_numbers()
        return jsonify({"success": True, "count": len(numbers), "numbers": numbers})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run()
