---
name: intermarket_analysis
category: analysis
description: US market SGX Nifty overnight impact, crude oil sector correlations, dollar index and IT sector, gold and jewellery stocks, bond yields and banking
---
# Intermarket Analysis for Indian Markets

## US Markets and SGX Nifty Overnight Influence

Indian markets open with a gap based on global overnight cues. The primary signals to check before 09:15 IST:

| Signal | Where to Track | Gap Influence |
|--------|---------------|---------------|
| SGX/GIFT Nifty futures | NSE IFSC (Gandhinagar) | Direct Nifty open proxy; ±50 pts = mild, ±150 pts = significant |
| S&P 500 / Nasdaq close | US close at 01:30–02:00 IST | IT, pharma sector correlation > 0.7 |
| Dow Jones | US close | General market sentiment |
| CBOE VIX (US) | US session | > 25 = global risk-off; typically negative for Nifty open |

**Rule:** If GIFT Nifty is up ≥ 0.5% and global VIX is below 20, expect a gap-up open. Buy the dip on the first 15-min pullback. If GIFT Nifty is down ≥ 0.5% on rising VIX, wait for the opening range to form before entering.

## Crude Oil and Energy/Refining Sector

India imports ~85% of its crude oil requirements. Brent crude is the relevant benchmark.

| Crude Move | Market Impact |
|-----------|--------------|
| Brent +5% | Positive: ONGC, Oil India (upstream producers); Negative: paint cos (Berger, Asian Paints), aviation (IndiGo) |
| Brent −5% | Positive: paint, aviation, OMCs (once price pass-through occurs); Negative: ONGC, Oil India |
| Crude > $100/barrel | Negative macro: current account deficit widens → rupee pressure → FPI outflows |
| Crude < $70/barrel | Positive macro: fiscal comfort, lower inflation → RBI rate cut potential |

**Reliance Industries** is unique: it benefits from both high crude (upstream/E&P) and refining spreads. Monitor GRM (Gross Refining Margin) separately.

## Dollar Index (DXY) and Indian IT Sector

India's IT sector earns 60–80% of revenue in USD. DXY strength (USD appreciation) directly boosts reported INR earnings.

- **DXY rises 1%:** IT sector typically outperforms Nifty by 0.5–1% on the next session open
- **DXY falls sharply (>1%):** IT sector underperforms; budget for rupee appreciation impact on earnings
- **Rupee appreciation of 2–3% over a quarter:** Typically 2–5% EPS reduction for major IT companies in INR terms

Watch Infosys, TCS, Wipro, HCL Tech — the four largest determine Nifty IT index direction.

**For trading:** When DXY is in a sustained uptrend (weekly chart) and rupee is weakening, IT sector ETF (Nifty IT) is a structural long trade.

## Gold and Related Sectors

Gold prices affect jewellery, lending, and mining stocks differently.

| Gold Move | Sector Impact |
|-----------|--------------|
| Gold +5% | Positive: Titan (jewellery division), Kalyan, Senco Gold, Muthoot Finance, Manappuram (gold loan books appreciate) |
| Gold −5% | Negative for gold loan NBFCs (LTV compression); jewellery retailers see demand pickup on price softness |
| Gold > ₹80,000/10g | Demand destruction; luxury jewellery impact vs wedding jewellery |
| Global gold rally in risk-off | Positive for gold ETFs; gold miners (not many listed in India) |

Gold in India is also a currency hedge — when INR weakens, gold in rupee terms rises even if dollar gold is flat. This amplifies gold loan book growth for NBFCs.

## Bond Yields and Banking Sector

The 10-year G-Sec yield is India's benchmark. Monitor it as a signal for banking sector health.

| 10Y G-Sec Yield | Banking Sector Impact |
|-----------------|----------------------|
| Rising rapidly (>10 bps/week) | Mark-to-market losses on bond portfolios → PSU banks hit harder (larger HTM books) |
| Falling | Bond portfolio gains; NIM expansion if deposit rates fall faster than lending rates |
| Yield > 7.5% | RBI tightening concern; bank NIMs under pressure |
| Yield spread (10Y − Repo) < 50 bps | Unusual compression; market pricing in future cuts → rally in bond-heavy banks |

**Banking sub-sector differentiation:**
- **PSU banks (SBI, PNB):** Higher sensitivity to government borrowing, G-Sec yields
- **Private banks (HDFC Bank, ICICI Bank):** More retail-driven NIM; less G-Sec exposure
- **NBFCs (Bajaj Finance, Chola):** Wholesale funding cost rises with yields; watch cost of funds

## Pre-Market Intermarket Checklist (08:45–09:10 IST)

1. GIFT Nifty: direction and magnitude
2. Brent crude: any overnight move > 1.5%
3. DXY: overnight move > 0.5%
4. Gold: any move > 1%
5. US 10Y yield: direction (proxy for global risk appetite)
6. Asia markets: Nikkei, Hang Seng, SGX Strait Times (risk sentiment)

Build this into the AI advisor's pre-market briefing using the `/ft-api/v1/` data endpoints.
