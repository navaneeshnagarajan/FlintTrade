---
name: earnings_options_strategy
category: strategy
description: Pre-earnings straddle timing, post-earnings IV crush fade, earnings calendar patterns, and sector earnings clusters for Indian listed companies
---
# Earnings Options Strategy

## The Earnings IV Cycle

IV expands as earnings approach and crushes immediately after the announcement — regardless of whether the result is good or bad. This is the foundational insight for all earnings options plays.

```
IV behaviour:
  Weeks before → Steady rise in IV
  3-5 days before → Accelerated IV expansion
  Announcement day → Peak IV
  Day after open → IV crush (often 30–50% drop in IV)
```

## Strategy 1 — Pre-Earnings Straddle Buy

**Objective:** Capture IV expansion before the event; exit before the announcement.

**Timing:** Enter 5–7 trading days before the result date.

**Setup:** Buy ATM straddle (call + put at the same strike, same expiry just after earnings).

**Exit:** Close the position 1 session before the earnings announcement. Do NOT hold through the earnings — IV crush will offset directional gains unless the move is extraordinary (> 2× the implied move).

**Expected P&L:** If IV rises 15–25% over the week before earnings, the straddle premium typically increases 20–35% even without the underlying moving much. That is the profit window.

**Selection criteria:**
- Use this only for large-cap, liquid option stocks: Infosys, TCS, Reliance, HDFC Bank, etc.
- Open interest in the option should be > 50,000 contracts (ensures tight spreads)
- Current IVP should be < 60 at entry — if IVP is already > 70, the expansion is partially priced in

## Strategy 2 — Post-Earnings IV Crush Fade (Premium Sell)

**Objective:** Study inflated premium immediately after the announcement and how IV collapse affects payoff.

**Timing example:** First 5–10 minutes after market opens following the earnings release.

**Structure:** Short ATM straddle or 1-strike OTM strangle, expiry = nearest weekly/monthly.

**Exit:** Close when 40–50% of the credit is earned (usually within 2–3 sessions as IV normalises).

**Risk:** If the stock has a surprise that causes continued large moves for multiple sessions, the short premium suffers. Protect with OTM wings (convert to short iron fly or strangle with defined risk).

**Historical IV crush magnitude (India):**
- Large-cap IT (TCS, Infosys): IV drops 35–50% on the session after results
- Banking (HDFC Bank, ICICI Bank): IV drops 25–40%
- Mid-cap stocks: Less predictable; IV can stay elevated if the result surprises

## Earnings Calendar Timing

**NSE Earnings calendar pattern (India):**
- Q1 results (April–June quarter): Announced July–August
- Q2 results (July–September quarter): Announced October–November
- Q3 results (October–December quarter): Announced January–February
- Q4 results (January–March quarter, full year): Announced April–May

**Sector clusters:**
- IT sector always reports in the first 2 weeks of the quarter-end month (Infosys often first, sets the tone)
- Banking sector reports in weeks 2–4
- Auto, FMCG, pharma in weeks 3–6

**Quarterly planning:** Build a rolling 8-week calendar of major upcoming earnings. Mark positions where the earnings date falls within the options expiry week.

## Implied Move Calculation

The options market prices in an expected move. Calculate it as:

```
Implied move (%) = (ATM straddle price / underlying spot price) × 100
```

Example: Nifty at 22,000, ATM straddle costs ₹300 total (₹150 call + ₹150 put).
Implied move = (300 / 22,000) × 100 = 1.36%

If you expect the actual move will be larger than 1.36%, buy the straddle. If you expect the move will be smaller, sell the straddle (after the announcement, not before).

## Sector Earnings Clusters — Contagion Effect

When a sector heavyweight reports, it moves the entire sector:
- **Infosys earnings:** Directly impacts TCS, Wipro, HCL Tech options even before their results
- **HDFC Bank earnings:** Affects Axis Bank, Kotak, ICICI Bank option IVs
- **Reliance Industries earnings:** Impacts ONGC, BPCL, IOC

Opportunity: Buy straddles in the second-tier sector stocks 2–3 days before the sector leader reports. The IV expansion in the leader often pulls up IV in related stocks.

## Risk Management

- Maximum premium deployed in pre-earnings straddle: 1% of capital per position
- Maximum number of concurrent earnings plays: 3 (to avoid earnings-week concentration)
- If the stock moves against you by > 1.5× the implied move before earnings, exit immediately — something unexpected has happened
