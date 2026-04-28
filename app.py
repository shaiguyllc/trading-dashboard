from flask import Flask, render_template
import requests
import yfinance as yf
from datetime import datetime, timedelta
import time

app = Flask(__name__)

# ─── Ticker Map ───────────────────────────────────────────────────────────────
# Maps keywords found in contractor names → stock tickers
# None = private company (no ticker)
TICKER_MAP = {
    "LOCKHEED MARTIN": "LMT",
    "GENERAL DYNAMICS": "GD",
    "NORTHROP GRUMMAN": "NOC",
    "RAYTHEON": "RTX",
    "BOEING": "BA",
    "L3HARRIS": "LHX",
    "L3 HARRIS": "LHX",
    "HUNTINGTON INGALLS": "HII",
    "LEIDOS": "LDOS",
    "SCIENCE APPLICATIONS INTERNATIONAL": "SAIC",
    "BOOZ ALLEN": "BAH",
    "PALANTIR": "PLTR",
    "MICROSOFT": "MSFT",
    "AMAZON": "AMZN",
    "ALPHABET": "GOOGL",
    "GOOGLE": "GOOGL",
    "ORACLE": "ORCL",
    "SALESFORCE": "CRM",
    "IBM": "IBM",
    "ACCENTURE": "ACN",
    "UNITEDHEALTH": "UNH",
    "OPTUM": "UNH",
    "CATERPILLAR": "CAT",
    "GENERAL ELECTRIC": "GE",
    "BAE SYSTEMS": "BAESY",
    "TEXTRON": "TXT",
    "TRANSDIGM": "TDG",
    "KRATOS": "KTOS",
    "AEROJET": "AJRD",
    "ANDURIL": None,       # private
    "CACI": "CACI",
    "CUBIC": None,         # acquired/private
    "DXC": "DXC",
    "PERATON": None,       # private
    "SAIC": "SAIC",
    "VECTRUS": "VEC",
    "AMENTUM": None,       # private (spun from Jacobs)
    "JACOBS": "J",
    "KBR": "KBR",
    "FLUOR": "FLR",
    "PARSONS": "PSN",
    "TETRA TECH": "TTEK",
    "OSHKOSH": "OSK",
    "AM GENERAL": None,    # private
    "COLT": None,
    "SIG SAUER": None,     # private
    "GENERAL ATOMICS": None, # private
    "CURTISS-WRIGHT": "CW",
    "HEICO": "HEI",
    "MOOG": "MOG.A",
    "MERCURY SYSTEMS": "MRCY",
    "MAXAR": None,         # acquired by private equity
    "PLANET LABS": "PL",
    "SPIRE GLOBAL": "SPIR",
    "HONEYWELL": "HON",
    "AT&T": "T",
    "T-MOBILE": "TMUS",
    "VERIZON": "VZ",
    "DELL": "DELL",
    "HEWLETT PACKARD": "HPE",
    "GENERAL MOTORS": "GM",
    "UNITED TECHNOLOGIES": "RTX",
    "SPACE EXPLORATION": None,  # SpaceX — private
    "BECHTEL": None,            # private
    "UT-BATTELLE": None,        # private (manages Oak Ridge for DOE)
    "MAXIMUS": "MMS",
    "PERSPECTA": None,          # merged into Peraton (private)
}

# ─── Simple in-memory cache (avoids re-fetching on every page refresh) ────────
_cache = {"data": None, "timestamp": None}
CACHE_MINUTES = 60


def find_ticker(company_name: str):
    name_upper = company_name.upper()
    for keyword, ticker in TICKER_MAP.items():
        if keyword in name_upper:
            return ticker
    return None


def fetch_contracts(days_back: int = 90, min_amount: int = 500_000_000) -> list:
    """Pull federal contract awards from USAspending.gov API (all agencies)."""
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days_back)

    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    payload = {
        "filters": {
            "time_period": [{
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date":   end_date.strftime("%Y-%m-%d"),
            }],
            "award_type_codes": ["A", "B", "C", "D"],   # contracts only
            "award_amounts": [{"lower_bound": min_amount}],
        },
        "fields": [
            "Recipient Name",
            "Award Amount",
            "Description",
            "Awarding Agency",
            "Start Date",
        ],
        "limit": 100,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        print(f"[contracts] API error: {e}")
        return []


def get_ma_status(ticker: str):
    """
    Pull 3 months of daily price data and calculate:
    - Current price vs 20-day MA
    - Whether MA is rising
    - Setup grade (A/B/C/D)
    """
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if hist.empty or len(hist) < 21:
            return None

        close     = hist["Close"]
        price     = round(float(close.iloc[-1]), 2)
        ma20      = round(float(close.rolling(20).mean().iloc[-1]), 2)
        ma20_prev = float(close.rolling(20).mean().iloc[-6])   # 5 bars ago
        ma_rising = ma20 > ma20_prev

        pct_from_ma = round(((price - ma20) / ma20) * 100, 1)

        if price > ma20 and ma_rising:
            if abs(pct_from_ma) <= 3:
                grade = "A"
                grade_label = "Pullback to MA — ideal entry"
            elif pct_from_ma <= 8:
                grade = "B"
                grade_label = "Extended — wait for pullback"
            else:
                grade = "C"
                grade_label = "Too extended — don't chase"
        elif price < ma20:
            grade = "D"
            grade_label = "Below MA — avoid"
        else:
            grade = "C"
            grade_label = "MA flat — no trend"

        return {
            "price":       price,
            "ma20":        ma20,
            "pct_from_ma": pct_from_ma,
            "ma_rising":   ma_rising,
            "grade":       grade,
            "grade_label": grade_label,
        }
    except Exception as e:
        print(f"[technicals] {ticker} error: {e}")
        return None


def build_data() -> list:
    """Fetch contracts, map to tickers, get technical grades, return sorted list."""
    contracts = fetch_contracts()
    aggregated = {}   # key = ticker (or company name if no ticker)

    for c in contracts:
        company    = c.get("Recipient Name", "Unknown")
        amount     = c.get("Award Amount", 0) or 0
        desc       = (c.get("Description") or "")[:100]
        ticker     = find_ticker(company)

        key = ticker if ticker else company[:40]

        if key in aggregated:
            aggregated[key]["total_amount"]  += amount
            aggregated[key]["contract_count"] += 1
        else:
            aggregated[key] = {
                "company":        company,
                "ticker":         ticker,
                "total_amount":   amount,
                "contract_count": 1,
                "description":    desc,
                "technical":      None,   # filled in below
            }

    # Now fetch technicals (slow — yfinance call per ticker)
    for key, row in aggregated.items():
        if row["ticker"]:
            print(f"[technicals] fetching {row['ticker']}...")
            row["technical"] = get_ma_status(row["ticker"])
            time.sleep(0.3)   # be polite to Yahoo Finance

    public_only = [r for r in aggregated.values() if r["ticker"]]
    return sorted(public_only, key=lambda x: x["total_amount"], reverse=True)


@app.route("/")
def index():
    global _cache

    # Serve from cache if fresh
    if _cache["data"] and _cache["timestamp"]:
        age_minutes = (datetime.now() - _cache["timestamp"]).seconds / 60
        if age_minutes < CACHE_MINUTES:
            return render_template(
                "index.html",
                data=_cache["data"],
                last_updated=_cache["timestamp"].strftime("%B %d, %Y at %I:%M %p"),
                cached=True,
                cache_age=int(age_minutes),
            )

    print("[app] Fetching fresh data...")
    data = build_data()
    _cache["data"]      = data
    _cache["timestamp"] = datetime.now()

    return render_template(
        "index.html",
        data=data,
        last_updated=_cache["timestamp"].strftime("%B %d, %Y at %I:%M %p"),
        cached=False,
        cache_age=0,
    )


@app.route("/refresh")
def refresh():
    """Force a fresh data pull (bypasses cache)."""
    global _cache
    _cache["data"]      = None
    _cache["timestamp"] = None
    from flask import redirect
    return redirect("/")


if __name__ == "__main__":
    print("Starting Trading Dashboard on http://localhost:5001")
    print("First load takes ~30-60 seconds (fetching contract + price data)")
    app.run(debug=False, port=5001)
