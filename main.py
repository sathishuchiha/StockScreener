from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import numpy as np
import math

app = FastAPI()

# -----------------------------
# CORS (FIXED FOR VERCEL)
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # safest for now (fix later if needed)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# SAFE UTILITIES
# -----------------------------

def safe_float(value):
    """
    Converts NaN / inf / None → None
    Ensures JSON serialization never fails
    """
    if value is None:
        return None

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None

    try:
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            return None
        return round(val, 2)
    except:
        return None


def calculate_zone(val_position):
    if val_position is None:
        return "Unknown"

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


def calculate_rsi(prices, period=14):
    """Calculates standard 14-day Relative Strength Index"""
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        if down == 0:
            rsi[i] = 100
        else:
            rs = up / down
            rsi[i] = 100. - 100. / (1. + rs)
    return safe_float(rsi[-1])


# -----------------------------
# CORE ANALYSIS
# -----------------------------

def analyze_stock(symbol, lookback_years=5):

    try:
        ticker_name = symbol + ".NS"
        ticker = yf.Ticker(ticker_name)
        ticker_info = ticker.info

        # 🟢 REAL EPS CHECK
        real_eps = ticker_info.get("trailingEps", None)
        if real_eps is None or real_eps <= 0:
            return {
                "symbol": symbol,
                "error": f"Invalid or negative TTM EPS ({real_eps}). Check skipped."
            }

        df = ticker.history(period=f"{lookback_years}y")

        # ❌ HANDLE EMPTY DATA
        if df is None or df.empty or len(df) < 30:
            return {
                "symbol": symbol,
                "error": "No data found or insufficient history"
            }

        df = df.dropna()

        # 🟢 COMPUTE HISTORICAL PE USING REAL EPS
        df["PE"] = df["Close"] / real_eps

        # CLEAN PE SERIES
        df["PE"] = df["PE"].replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=["PE"])

        if len(df) == 0:
            return {
                "symbol": symbol,
                "error": "Invalid PE data"
            }

        current_pe = safe_float(df["PE"].iloc[-1])
        avg_pe = safe_float(df["PE"].mean())

        # VALUATION POSITION
        val_position = safe_float((df["PE"] < df["PE"].iloc[-1]).mean() * 100)
        zone = calculate_zone(val_position)

        # 🟢 TRENDLYNE-STYLE EXTRA METRICS
        rsi = calculate_rsi(df["Close"].to_numpy())
        current_ratio = safe_float(ticker_info.get("currentRatio"))
        roe = safe_float(ticker_info.get("returnOnEquity"))
        if roe is not None:
            roe = safe_float(roe * 100)  # Convert fraction to percentage

        # 🟢 AGGREGATED BUY FACTOR SCORE CALCULATION
        score = 0
        max_possible_score = 0

        # Valuation Metric
        if val_position is not None:
            max_possible_score += 2
            if val_position <= 30:
                score += 2
            elif val_position <= 60:
                score += 1

        # Momentum Metric
        if rsi is not None:
            max_possible_score += 1
            if rsi < 40:
                score += 1
            elif rsi > 70:
                score -= 1

        # Return Efficiency Metric
        if roe is not None:
            max_possible_score += 1
            if roe >= 15.0:
                score += 1

        # Liquidity Metric
        if current_ratio is not None:
            max_possible_score += 1
            if current_ratio >= 1.25:
                score += 1

        buy_factor_pct = round((max(0, score) / max_possible_score) * 100, 1) if max_possible_score > 0 else 0

        return {
            "symbol": symbol,
            "real_eps": safe_float(real_eps),
            "current_pe": current_pe,
            "average_pe": avg_pe,
            "valuation_position": val_position,
            "zone": zone,
            "rsi": rsi,
            "current_ratio": current_ratio,
            "roe": roe,
            "buy_factor_score": f"{buy_factor_pct}%"
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "error": str(e)
        }


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
        "Strong Sell": 0,
        "Unknown": 0
    }

    for s in symbols[:20]:

        r = analyze_stock(s.strip(), lookback_years)

        zone = r.get("zone", "Unknown")

        if zone in summary:
            summary[zone] += 1
        else:
            summary["Unknown"] += 1

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

    md = "# 📊 Advanced Stock Screener (Trendlyne Multi-Metric Model)\n\n"

    md += "## 📘 TRENDLYNE FACTOR CHECKS\n"
    md += "- PE: Price / Earnings ratio (Calculated using TTM Real EPS)\n"
    md += "- Valuation Position: relative position vs historical PE\n"
    md += "- RSI (14D): Technical Momentum (<30 Oversold, >70 Overbought)\n"
    md += "- ROE (%): Return on Equity. Management efficiency (>15% is healthy)\n"
    md += "- Current Ratio: Short-term liquidity buffer (>1.25 shows strong solvency)\n"
    md += "- Aggregated Buy Factor: Overall score across Fundamentals, Health & Momentum\n\n"

    md += "---\n\n"

    for r in results:

        if "error" in r:
            md += f"## {r['symbol']}\n❌ {r['error']}\n\n---\n\n"
            continue

        md += f"""## {r['symbol']}  👉  **Overall Buy Factor: {r.get('buy_factor_score')}**

- Real TTM EPS: {r.get('real_eps')}
- Valuation Zone: {r.get('zone')} (Current P/E: {r.get('current_pe')} vs 5Y Avg: {r.get('average_pe')})
- Valuation Position: {r.get('valuation_position')}%
- Technical Momentum (RSI): {r.get('rsi')}
- Profitability (ROE): {f"{r.get('roe')}%" if r.get('roe') else 'N/A'}
- Liquidity Buffer (Current Ratio): {r.get('current_ratio')}

📌 Interpretation:
{get_interpretation(r.get('zone'))}

---

"""

    md += "## 📌 SUMMARY\n\n"

    for k, v in summary.items():
        md += f"- {k}: {v}\n"

    return md


def get_interpretation(zone):

    if zone == "Strong Buy":
        return "Stock is significantly undervalued vs history."
    elif zone == "Buy":
        return "Stock is moderately undervalued."
    elif zone == "Fair Value":
        return "Stock is fairly valued."
    elif zone == "Sell":
        return "Stock is slightly overvalued."
    elif zone == "Strong Sell":
        return "Stock is highly overvalued."
    else:
        return "Insufficient data for interpretation."
