#!/usr/bin/env python3
"""
Contract → Setup Dashboard Generator
-------------------------------------
Run locally:  python3 generate.py
              then open docs/index.html in your browser

Runs automatically via GitHub Actions every weekday at 5pm ET.
Output is saved to docs/index.html and served via GitHub Pages.
"""

import requests
import yfinance as yf
from datetime import datetime, timedelta
import os
import time

# ── Ticker Map ────────────────────────────────────────────────────────────────
# Maps keywords found in contractor names → stock tickers
# None = private company (skipped)
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
    "CACI": "CACI",
    "DXC": "DXC",
    "JACOBS": "J",
    "KBR": "KBR",
    "FLUOR": "FLR",
    "PARSONS": "PSN",
    "TETRA TECH": "TTEK",
    "OSHKOSH": "OSK",
    "CURTISS-WRIGHT": "CW",
    "HEICO": "HEI",
    "MERCURY SYSTEMS": "MRCY",
    "PLANET LABS": "PL",
    "SPIRE GLOBAL": "SPIR",
    "HONEYWELL": "HON",
    "AT&T": "T",
    "T-MOBILE": "TMUS",
    "VERIZON": "VZ",
    "DELL": "DELL",
    "HEWLETT PACKARD": "HPE",
    "MAXIMUS": "MMS",
    "SAIC": "SAIC",
    "VECTRUS": "VEC",
    # Private — skip
    "ANDURIL": None,
    "SPACE EXPLORATION": None,
    "BECHTEL": None,
    "PERATON": None,
    "GENERAL ATOMICS": None,
    "AM GENERAL": None,
    "UT-BATTELLE": None,
    "AMENTUM": None,
}

GRADE_COLORS = {
    "A": ("#1a4d2e", "#56d364", "#238636"),
    "B": ("#2d2a1a", "#e3b341", "#9e6a03"),
    "C": ("#1e1e1e", "#8b949e", "#30363d"),
    "D": ("#3d1c1c", "#f85149", "#da3633"),
}


def find_ticker(company_name: str):
    name_upper = company_name.upper()
    for keyword, ticker in TICKER_MAP.items():
        if keyword in name_upper:
            return ticker
    return "UNKNOWN"


def fetch_contracts(days_back: int = 90, min_amount: int = 500_000_000) -> list:
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days_back)

    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    payload = {
        "filters": {
            "time_period": [{
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date":   end_date.strftime("%Y-%m-%d"),
            }],
            "award_type_codes": ["A", "B", "C", "D"],
            "award_amounts": [{"lower_bound": min_amount}],
        },
        "fields": ["Recipient Name", "Award Amount", "Description", "Awarding Agency", "Start Date"],
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
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if hist.empty or len(hist) < 21:
            return None

        close     = hist["Close"]
        price     = round(float(close.iloc[-1]), 2)
        ma20      = round(float(close.rolling(20).mean().iloc[-1]), 2)
        ma20_prev = float(close.rolling(20).mean().iloc[-6])
        ma_rising = ma20 > ma20_prev
        pct       = round(((price - ma20) / ma20) * 100, 1)

        if price > ma20 and ma_rising:
            if abs(pct) <= 3:
                grade, label = "A", "Pullback to MA — ideal entry"
            elif pct <= 8:
                grade, label = "B", "Uptrend, extended — wait"
            else:
                grade, label = "C", "Too extended — don't chase"
        elif price < ma20:
            grade, label = "D", "Below MA — avoid"
        else:
            grade, label = "C", "MA flat — no trend"

        return {
            "price": price,
            "ma20": ma20,
            "pct": pct,
            "ma_rising": ma_rising,
            "grade": grade,
            "label": label,
        }
    except Exception as e:
        print(f"[technicals] {ticker}: {e}")
        return None


def build_data() -> list:
    contracts = fetch_contracts()
    aggregated = {}

    for c in contracts:
        company = c.get("Recipient Name", "Unknown")
        amount  = c.get("Award Amount", 0) or 0
        desc    = (c.get("Description") or "")[:100]
        agency  = c.get("Awarding Agency", "")
        ticker  = find_ticker(company)

        if ticker is None or ticker == "UNKNOWN":
            continue  # skip private + unrecognized

        key = ticker
        if key in aggregated:
            aggregated[key]["total_amount"]  += amount
            aggregated[key]["contract_count"] += 1
        else:
            aggregated[key] = {
                "company":        company,
                "ticker":         ticker,
                "agency":         agency,
                "total_amount":   amount,
                "contract_count": 1,
                "description":    desc,
                "technical":      None,
            }

    print(f"Found {len(aggregated)} public companies — fetching prices...")
    for key, row in aggregated.items():
        print(f"  {row['ticker']}...")
        row["technical"] = get_ma_status(row["ticker"])
        time.sleep(0.3)

    return sorted(aggregated.values(), key=lambda x: x["total_amount"], reverse=True)


def fmt_amount(n):
    if n >= 1e9:
        return f"${n/1e9:.1f}B"
    return f"${n/1e6:.0f}M"


def grade_badge(grade):
    if not grade:
        return '<span style="color:#484f58">—</span>'
    bg, fg, border = GRADE_COLORS.get(grade, ("#1e1e1e", "#8b949e", "#30363d"))
    return (f'<span style="background:{bg};color:{fg};border:1px solid {border};'
            f'padding:3px 10px;border-radius:12px;font-size:12px;font-weight:700;">{grade}</span>')


def build_rows_table(data):
    rows = []
    for r in data:
        t = r["technical"]
        price    = f"${t['price']}" if t else "—"
        ma20     = f"${t['ma20']}"  if t else "—"
        pct_html = ""
        if t:
            color = "#56d364" if t["pct"] >= 0 else "#f85149"
            sign  = "+" if t["pct"] >= 0 else ""
            pct_html = f'<span style="color:{color}">{sign}{t["pct"]}%</span>'
        else:
            pct_html = "—"
        arrow    = ('▲' if (t and t["ma_rising"]) else '▼') if t else "—"
        a_color  = "#56d364" if (t and t["ma_rising"]) else "#f85149"
        badge    = grade_badge(t["grade"] if t else None)
        label    = t["label"] if t else "—"

        rows.append(f"""
        <tr>
          <td><div class="co-name" title="{r['company']}">{r['company']}</div>
              <div class="co-desc" title="{r['description']}">{r['description']}</div></td>
          <td><span class="ticker">{r['ticker']}</span></td>
          <td class="mono green">{fmt_amount(r['total_amount'])}</td>
          <td class="center muted">{r['contract_count']}</td>
          <td class="mono">{price}</td>
          <td class="mono">{ma20}</td>
          <td class="mono">{pct_html}</td>
          <td class="center" style="color:{a_color}">{arrow}</td>
          <td>{badge}</td>
          <td class="action">{label}</td>
        </tr>""")
    return "\n".join(rows)


def build_cards(data):
    cards = []
    for r in data:
        t = r["technical"]
        grade    = t["grade"] if t else "?"
        bg, fg, border = GRADE_COLORS.get(grade, ("#1e1e1e", "#8b949e", "#30363d"))
        label    = t["label"] if t else "No price data"
        price    = f"${t['price']}" if t else "—"
        pct_sign = "+" if (t and t["pct"] >= 0) else ""
        pct_str  = f"{pct_sign}{t['pct']}%" if t else "—"
        pct_col  = "#56d364" if (t and t["pct"] >= 0) else "#f85149"
        arrow    = "▲" if (t and t["ma_rising"]) else "▼"
        arr_col  = "#56d364" if (t and t["ma_rising"]) else "#f85149"

        cards.append(f"""
        <div class="card">
          <div class="card-top">
            <div>
              <div class="card-ticker">{r['ticker']}</div>
              <div class="card-company">{r['company'][:45]}</div>
            </div>
            <div class="card-grade" style="background:{bg};color:{fg};border:1px solid {border};">{grade}</div>
          </div>
          <div class="card-label">{label}</div>
          <div class="card-stats">
            <div class="stat"><span class="stat-label">Contracts</span><span class="stat-val green">{fmt_amount(r['total_amount'])}</span></div>
            <div class="stat"><span class="stat-label">Price</span><span class="stat-val">{price}</span></div>
            <div class="stat"><span class="stat-label">vs 20-MA</span><span class="stat-val" style="color:{pct_col}">{pct_str}</span></div>
            <div class="stat"><span class="stat-label">MA Trend</span><span class="stat-val" style="color:{arr_col}">{arrow}</span></div>
          </div>
          <div class="card-agency">{r['agency']} · {r['contract_count']} contract{'s' if r['contract_count']!=1 else ''}</div>
        </div>""")
    return "\n".join(cards)


def render_html(data, last_updated):
    total_val  = sum(r["total_amount"] for r in data)
    grade_a    = sum(1 for r in data if r["technical"] and r["technical"]["grade"] == "A")
    grade_b    = sum(1 for r in data if r["technical"] and r["technical"]["grade"] == "B")
    rows_html  = build_rows_table(data)
    cards_html = build_cards(data)
    count      = len(data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Contract → Setup Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0d1117; color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px; line-height: 1.5; padding: 16px;
    }}

    /* ── Header ── */
    .header {{ display:flex; align-items:flex-start; justify-content:space-between;
               margin-bottom:20px; padding-bottom:16px; border-bottom:1px solid #21262d;
               gap:12px; flex-wrap:wrap; }}
    .header h1 {{ font-size:18px; font-weight:700; color:#f0f6fc; }}
    .header p  {{ font-size:12px; color:#8b949e; margin-top:4px; }}
    .refresh-note {{ font-size:12px; color:#8b949e; background:#161b22;
                     border:1px solid #30363d; border-radius:6px; padding:8px 12px;
                     text-align:right; }}
    .refresh-note a {{ color:#388bfd; text-decoration:none; }}

    /* ── Summary cards ── */
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
                gap:10px; margin-bottom:20px; }}
    .scard {{ background:#161b22; border:1px solid #21262d; border-radius:8px; padding:12px 14px; }}
    .scard-label {{ font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:.5px; }}
    .scard-val   {{ font-size:20px; font-weight:700; color:#f0f6fc; margin-top:2px; }}
    .scard-sub   {{ font-size:11px; color:#8b949e; margin-top:1px; }}

    /* ── Legend ── */
    .legend {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:16px; font-size:12px; color:#8b949e; }}
    .legend strong {{ color:#c9d1d9; margin-right:4px; }}

    /* ── Notice ── */
    .notice {{ background:#1c2128; border:1px solid #30363d; border-radius:6px;
               padding:8px 12px; font-size:12px; color:#8b949e; margin-bottom:16px;
               display:flex; align-items:center; gap:8px; }}
    .dot {{ width:7px; height:7px; border-radius:50%; background:#56d364; flex-shrink:0; }}

    /* ── Desktop table ── */
    .table-wrap {{ overflow-x:auto; border-radius:8px; border:1px solid #21262d; }}
    table {{ width:100%; border-collapse:collapse; min-width:800px; }}
    thead tr {{ background:#161b22; }}
    th {{ text-align:left; padding:9px 12px; font-size:11px; font-weight:600;
          color:#8b949e; text-transform:uppercase; letter-spacing:.5px;
          border-bottom:1px solid #21262d; white-space:nowrap; }}
    td {{ padding:10px 12px; border-bottom:1px solid #161b22; vertical-align:middle; }}
    tr:last-child td {{ border-bottom:none; }}
    tr:hover td {{ background:#161b22; }}
    .co-name {{ font-weight:500; color:#c9d1d9; max-width:200px;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .co-desc {{ font-size:11px; color:#484f58; max-width:200px;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .ticker  {{ font-family:"SF Mono","Fira Code",monospace; font-weight:700;
                color:#58a6ff; font-size:13px; }}
    .mono    {{ font-family:"SF Mono","Fira Code",monospace; font-size:13px; }}
    .green   {{ color:#56d364; }}
    .muted   {{ color:#8b949e; font-size:12px; text-align:center; }}
    .center  {{ text-align:center; }}
    .action  {{ font-size:12px; color:#8b949e; min-width:160px; }}

    /* ── Mobile cards ── */
    .cards-grid {{ display:none; flex-direction:column; gap:12px; }}
    .card {{ background:#161b22; border:1px solid #21262d; border-radius:10px; padding:14px; }}
    .card-top    {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px; }}
    .card-ticker {{ font-family:"SF Mono","Fira Code",monospace; font-size:18px;
                    font-weight:700; color:#58a6ff; }}
    .card-company{{ font-size:11px; color:#8b949e; margin-top:2px; }}
    .card-grade  {{ font-size:22px; font-weight:800; padding:4px 14px;
                    border-radius:8px; flex-shrink:0; }}
    .card-label  {{ font-size:13px; color:#c9d1d9; font-weight:500;
                    margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid #21262d; }}
    .card-stats  {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }}
    .stat        {{ background:#0d1117; border-radius:6px; padding:8px 10px; }}
    .stat-label  {{ font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:.4px; }}
    .stat-val    {{ font-size:16px; font-weight:600; font-family:"SF Mono","Fira Code",monospace;
                    color:#e6edf3; margin-top:2px; }}
    .card-agency {{ font-size:11px; color:#484f58; }}

    /* ── Footer ── */
    .footer {{ margin-top:20px; font-size:11px; color:#484f58; text-align:center; }}

    /* ── Responsive ── */
    @media (max-width: 700px) {{
      body {{ padding: 10px; }}
      .header h1 {{ font-size:16px; }}
      .table-wrap {{ display:none; }}
      .cards-grid {{ display:flex; }}
      .legend {{ display:none; }}
    }}
  </style>
</head>
<body>

<div class="header">
  <div>
    <h1>Contract → Stock Setup Dashboard</h1>
    <p>Federal contracts ≥$500M · last 90 days · public companies only · 20-day MA analysis</p>
  </div>
  <div class="refresh-note">
    Updated: {last_updated}<br/>
    <a href="https://github.com/YOUR_USERNAME/trading-dashboard/actions" target="_blank">Trigger manual refresh →</a>
  </div>
</div>

<div class="notice">
  <span class="dot"></span>
  Auto-updates every weekday at 5pm ET. To refresh now, click the link above → Run workflow.
</div>

<div class="summary">
  <div class="scard">
    <div class="scard-label">Total Contracts</div>
    <div class="scard-val">{fmt_amount(total_val)}</div>
    <div class="scard-sub">{count} public companies</div>
  </div>
  <div class="scard">
    <div class="scard-label">Grade A Setups</div>
    <div class="scard-val" style="color:#56d364">{grade_a}</div>
    <div class="scard-sub">pullback to MA now</div>
  </div>
  <div class="scard">
    <div class="scard-label">Grade B Setups</div>
    <div class="scard-val" style="color:#e3b341">{grade_b}</div>
    <div class="scard-sub">uptrend, wait for dip</div>
  </div>
  <div class="scard">
    <div class="scard-label">Data as of</div>
    <div class="scard-val" style="font-size:13px;margin-top:4px;">{last_updated.split(' at ')[0]}</div>
    <div class="scard-sub">auto-updates daily</div>
  </div>
</div>

<div class="legend">
  <strong>Grades:</strong>
  <span><strong style="color:#56d364">A</strong> = within 3% of rising MA — buy zone</span>
  <span><strong style="color:#e3b341">B</strong> = above MA, extended — wait for pullback</span>
  <span><strong style="color:#8b949e">C</strong> = flat MA or too extended — skip</span>
  <span><strong style="color:#f85149">D</strong> = below MA — avoid</span>
</div>

<!-- Desktop table -->
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Company</th><th>Ticker</th><th>Contracts Won</th>
        <th>#</th><th>Price</th><th>20-MA</th>
        <th>% from MA</th><th>MA</th><th>Grade</th><th>Action</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
</div>

<!-- Mobile cards -->
<div class="cards-grid">
{cards_html}
</div>

<div class="footer">
  Data: USAspending.gov · Prices: Yahoo Finance · Not financial advice.<br/>
  Grade A = pullback entry candidate, not a guaranteed buy signal. Always use a stop loss.
</div>

</body>
</html>"""


def main():
    print(f"Starting at {datetime.now().strftime('%H:%M:%S')}")
    data = build_data()
    last_updated = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")
    html = render_html(data, last_updated)

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w") as f:
        f.write(html)
    print(f"Done. Written to docs/index.html ({len(data)} companies)")


if __name__ == "__main__":
    main()
