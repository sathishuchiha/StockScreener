from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import numpy as np

app = FastAPI()

# Allow frontend access (important for mobile + hosting)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://stock-screener-frontend-phi.vercel.app",
        "http://localhost",
        "http://127.0.0.1"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# CORE LOGIC
# -----------------------------

def calculate_zone(val_position):
    if val_position <= 20:
        return "Strong Buy"
    elif val_position <= 40:
        return "Buy"
    elif val_position <= 60:
        return "Fair Value"
    elif val_position <= 80:
        return "Sell"
    else:
        return "Strong Sell"


def analyze_stock(symbol, lookback_years=5):

    try:
        df = yf.Ticker(symbol + ".NS").history(period=f"{lookback_years}y")

        if df.empty:
            return {"symbol": symbol, "error": "No data found"}

        # ⚠️ TEMP EPS (we will upgrade later to real EPS engine)
        eps = 20

        df["PE"] = df["Close"] / eps

        current_pe = float(df["PE"].iloc[-1])
        avg_pe = float(df["PE"].mean())

        # 🔥 KEY METRIC (renamed)
        val_position = (df["PE"] < current_pe).mean() * 100

        zone = calculate_zone(val_position)

        return {
            "symbol": symbol,
            "current_pe": round(current_pe, 2),
            "average_pe": round(avg_pe, 2),
            "valuation_position": round(val_position, 2),
            "zone": zone
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


# -----------------------------
# BULK API
# -----------------------------

@app.post("/bulk-analyze")
def bulk_analyze(payload: dict):

    symbols = payload.get("symbols", [])
    lookback_years = payload.get("lookback_years", 5)

    results = []
    summary = {
        "Strong Buy": 0,
        "Buy": 0,
        "Fair Value": 0,
        "Sell": 0,
        "Strong Sell": 0
    }

    for s in symbols[:20]:
        r = analyze_stock(s.strip(), lookback_years)

        if "zone" in r:
            summary[r["zone"]] += 1

        results.append(r)

    markdown = generate_markdown(results, summary)

    return {
        "results": results,
        "summary": summary,
        "markdown": markdown
    }


# -----------------------------
# MARKDOWN GENERATOR
# -----------------------------

def generate_markdown(results, summary):

    md = "# 📊 Stock Valuation Report\n\n"

    md += "## 📘 KEY DEFINITIONS\n\n"
    md += "- **PE**: Price / Earnings ratio\n"
    md += "- **Valuation Position**: % of time stock traded below current PE\n"
    md += "- **Zone**: Valuation classification based on history\n\n"

    md += "---\n\n"

    for r in results:

        if "error" in r:
            md += f"## {r['symbol']}\n❌ Data not available\n\n---\n\n"
            continue

        md += f"""## {r['symbol']}

- Current PE: {r['current_pe']}
- Average PE: {r['average_pe']}
- Valuation Position: {r['valuation_position']}%
- Zone: {r['zone']}

📌 Interpretation:
{get_interpretation(r['zone'])}

---

"""

    md += "## 📌 SUMMARY\n\n"

    for k, v in summary.items():
        md += f"- {k}: {v}\n"

    return md


def get_interpretation(zone):

    if zone == "Strong Buy":
        return "Stock is trading significantly below its historical valuation."
    elif zone == "Buy":
        return "Stock is undervalued compared to historical range."
    elif zone == "Fair Value":
        return "Stock is fairly valued."
    elif zone == "Sell":
        return "Stock is trading above typical valuation levels."
    else:
        return "Stock is highly expensive compared to historical range."
