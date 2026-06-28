---
name: expiry_day_trading
category: strategy
description: Thursday expiry dynamics, 0DTE option strategies, gamma risk, time decay acceleration, pin risk, and rolling positions
---
# Expiry Day Trading

## The Expiry Calendar (India NSE)

- **Weekly Nifty 50:** Every Thursday (or Wednesday if Thursday is a holiday)
- **Weekly BankNifty:** Every Wednesday
- **Monthly contracts:** Last Thursday of the month
- Expiry time: 3:30 PM IST (options stop trading at 3:30 PM; settlement at 3:30 PM)

## Gamma Dynamics on Expiry Day

On the day of expiry, ATM options have the highest gamma of their entire life. This means:

- A 50-point move in Nifty can turn a worthless OTM option into a significant ITM one in minutes.
- Delta of ATM options swings between 0 and 1 rapidly — positions change value non-linearly.
- **For sellers:** A brief move against you can wipe premium collected over multiple weeks.
- **For buyers:** Small capital can produce large absolute returns if directional move happens.

**Gamma risk rule:** Never hold naked short ATM options on expiry day past 12:00 PM without a hedge.

## 0DTE Option Strategies

**1. Expiry Day Short Straddle Example (with defined risk)**
- Time window example: 9:20–9:25 IST
- Structure: short ATM straddle + long wings 100–150 points away (iron butterfly)
- Profit: Net credit collected; max profit if Nifty pins near strike at 3:30
- Exit: 50% of premium collected OR at 14:00 IST, whichever comes first

**2. Long Gamma Scalp**
- Buy ATM straddle at open (IVP < 50 required — cheap premium on expiry day is rare but possible on quiet weeks)
- Scalp delta: sell the calls when net delta is +0.5, buy back on pullback
- Exit entire position by 14:30 IST — theta kills remaining value rapidly

**3. OTM Lottery**
- Buy deep OTM options (50–100 points OTM) at sub-₹10 premium in the expected direction
- Position size: max 1% of capital total premium
- Catch a 100+ point breakout for 5–10× return

## Time Decay Acceleration (Theta)

Theta is not linear — it accelerates sharply in the last few hours of an expiry day.

| Time (IST) | Approximate Theta Rate |
|------------|----------------------|
| 09:15 | 1× baseline |
| 11:00 | 1.5× |
| 13:00 | 2.5× |
| 14:30 | 4× |
| 15:00 | 8× |

Options with < 4 hours to expiry lose value faster than at any other point in their life. Sellers benefit; buyers must move fast.

## Pin Risk

Pin risk occurs when the underlying settles exactly at or near the short strike. At expiry:
- An option that is ₹1 ITM at 3:30 PM will be auto-exercised (long) or assigned (short)
- Unexpected assignment leaves a large unhedged position overnight

**Rules to manage pin risk:**
- Close any short strikes within 100 points of spot price by 14:00 IST on expiry day
- Do not wait for zero value — the assignment risk exceeds the ₹2–5 remaining premium
- If you cannot monitor, set a 14:00 IST time-based exit order

## Rolling Positions Before Expiry

Rolling = closing the expiring contract and opening the next week/month.

- **When to roll:** When the expiring position has < 20% of original premium remaining and you want to maintain the position
- **Roll cost:** Bid-ask spread of closing leg + bid-ask spread of opening leg
- **Best time to roll:** Tuesday or Wednesday, before expiry-day liquidity rush in the near contract
- For monthly → monthly rolls: roll 3–5 trading days before expiry (last Thursday − 3 days)
- Use `optionsmultiorder` in OpenAlgo to execute both legs simultaneously and reduce slippage

## Risk Limits on Expiry Day

- Reduce position size to 50% of normal on expiry day if holding short gamma
- Set hard stop at 2× premium collected for any short option strategy
- Keep 40% of capital free as margin buffer — intraday margin spikes are common
