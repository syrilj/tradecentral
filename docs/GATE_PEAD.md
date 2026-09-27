# GO/NO-GO Gate: Post-Earnings Announcement Drift & Catalyst Gap Engine (PEAD)

Pre-registered 2026-07-31.

## The Economic Hypothesis

Price-derived technical indicators (Alpha158) fail to predict discrete corporate events (earnings announcements, product catalysts). 

However, **Post-Earnings Announcement Drift (PEAD)** is an economically motivated market inefficiency: when a stock experiences a high-volume, significant earnings gap (> 2.5 std dev relative to 20-day ATR), institutional under-reaction and short covering cause sustained drift in the direction of the gap over 5 to 20 trading sessions.

---

## Data & Strategy Protocol

- **Universe**: Liquid US Equities (S&P 500 / Nasdaq 100 components).
- **Features**:
  - `gap_std`: Overnight gap percentage normalized by 20-day ATR (`(Open - PrevClose) / ATR_20d`).
  - `vol_surge`: 1-day volume relative to 20-day average volume (`Volume / Volume_20d_SMA`).
  - `short_pressure`: FINRA Short Volume ratio (`ShortVolume / TotalVolume`).
- **Signal Rule**: 
  - **Long Entry**: `gap_std > +2.0` AND `vol_surge > 2.0x`.
  - **Short Entry**: `gap_std < -2.0` AND `vol_surge > 2.0x`.
- **Holding Period**: 5 to 10 trading days.
- **Cost Model**: 10bp per side (20bp round-trip).

---

## Pre-Registered GO/NO-GO Criteria

| Metric | Required GO Threshold | Economic Motivation |
|---|---|---|
| **Mean Rank IC** | `> 0.040` | Strong directional rank correlation for catalyst continuation |
| **Rank ICIR** | `> 0.50` | Signal consistency across time |
| **Net Annual Return** | `> +8.0%` | Real return post 10bp trading costs |
| **Information Ratio (IR)** | `> 0.60` | Outperformance vs SPY benchmark |
| **Max Drawdown** | `< 15.0%` | Strict risk management |

If any criterion fails, the verdict is **NO-GO**.
