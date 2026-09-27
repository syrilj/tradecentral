# Auction Market Theory — trading choppy markets

## Why this exists

Almost every loss in a choppy market is one of two mistakes:

1. A **trend tactic applied inside balance** — buying a breakout that was really
   the top of a rotation, getting stopped as price returns to the middle.
2. A **balance tactic applied to a breakout** — fading a move that was the
   market genuinely relocating value, and averaging into it.

Both mistakes come from the same missing input: nobody told you which regime you
were in. Auction Market Theory (Steidlmayer's Market Profile, formalised by Jim
Dalton in *Mind Over Markets* and *Markets in Profile*) exists to answer exactly
that question, and to say where the edges are once you know.

This module computes that answer from OHLCV bars. It does not predict. It
classifies the current auction and hands you the levels that follow from the
classification.

## The one idea

A market is a two-way auction whose only job is to advertise prices to find
buyers and sellers. It does this by rotating up until buying dries up, then down
until selling dries up. Where it spends the most time and volume is what the
market currently believes is **fair value**.

- **In balance**, the auction is rotating around an agreed fair value. Price at
  the top of that range is expensive, price at the bottom is cheap, and the
  edge trade is *responsive*: fade the extreme back toward the middle.
- **Out of balance**, one side is in control and the auction is travelling to
  find a new fair value somewhere else. The edge trade is *initiative*: go with
  it, or stand aside. Fading here is how accounts die.

Everything below is machinery for deciding which of those two sentences applies
right now.

## The vocabulary

| Term | What it is | Why you care |
|---|---|---|
| **POC** (point of control) | The price with the most volume traded | The magnet. Rotations inside balance target it. |
| **Value area** (VAH / VAL) | The band holding 70% of volume around the POC | Its edges are where responsive traders act. |
| **HVN** (high-volume node) | A secondary volume shelf | Price slows down here. Targets and stalls. |
| **LVN** (low-volume node) | A volume trough | Price moves fast through here. The market rejected it once and will again. |
| **Excess** | Single prints at an extreme — a sharp tail | The auction there is *finished*. It does not get revisited casually. |
| **Poor high / low** | A flat, multi-bar extreme with no tail | The auction there is *unfinished*. It acts as a magnet and usually gets revisited. |
| **Acceptance** | Consecutive closes outside value | The difference between a probe and a real relocation. |
| **Rotation factor** | Sum of ±1 per higher/lower high and low | Near zero means highs and lows are alternating: chop. |

## How the regime is decided

The `BALANCE` / `TRANSITION` / `IMBALANCE` verdict is a weighted score of five
independent measurements, not one indicator. Each is on a 0..1 scale where 1
means "more balanced".

| Component | Weight | What it measures |
|---|---|---|
| Value-area overlap | 0.30 | How much consecutive sessions' value areas share. Overlapping value is balance; migrating value is trend. |
| Close containment | 0.20 | What share of recent closes sit inside the value area. |
| Choppiness index | 0.20 | Dreiss' CHOP: path length versus net range. 61.8 is pure chop, 38.2 is pure trend. |
| Efficiency ratio | 0.15 | Kaufman: net move divided by total distance travelled. Low means rotation. |
| Rotation factor | 0.15 | Alternating highs and lows versus consistently higher or lower ones. |

Score at or above 0.60 is `BALANCE`. At or below 0.40 is `IMBALANCE`. Between
them is `TRANSITION`, which means the market is deciding and you should size
down or wait.

A component that cannot be computed from the bars available is reported as null
and dropped from the weighting, rather than being filled with a default. The
score always says which components it was built from.

### The balance window

The profile is built on the **current** balance, not the whole lookback. The
engine walks backward from the most recent session and keeps extending the
window while consecutive value areas keep overlapping; it stops where value
migrated, because that is a different balance and mixing the two produces a
value area price left months ago. The response reports the window it chose and
whether it was truncated.

## The setups

### 1. Responsive fade at the value-area edge

The bread-and-butter chop trade. Requires regime `BALANCE`.

- **Long** at the value-area low, **short** at the value-area high.
- **Stop** beyond the *range* extreme plus half an ATR — not a fixed distance
  from your fill. The invalidation is acceptance beyond the range, not a wick.
- **First target** the POC. Second target the opposite value-area edge, and only
  if the rotation is moving fast.

### 2. Look above and fail (and its mirror)

The strongest setup in the whole framework, and the one that pays for the chop.

Price pushes through the value-area high, triggers every breakout buyer, then
closes back inside value. Those buyers are now trapped and their stops are fuel.
Sell it, stop above the failed high, target the POC. Mirror for a failed low.

The engine flags this as `location.failed_auction`.

### 3. No trade: inside value

When price is near the POC you have no edge — that is the price both sides
agree on. The engine returns bias `NEUTRAL / WAIT` and publishes the resting
bracket to work instead of inventing a direction.

### 4. No trade: acceptance outside value

Two or more consecutive closes outside the value area means the market is
relocating. The balance playbook is suspended. The engine refuses to emit a
responsive plan and gives the measured-move target for the break instead.

## On the "80% rule"

Folklore says that if the market opens outside value and then trades back into
it and stays for two consecutive periods, it fills the value area about 80% of
the time. That number is quoted constantly and sourced almost never.

This module does not quote it. Instead it *measures* the rotation hit-rate for
the symbol, timeframe and window you actually loaded: how often a touch of the
prior session's value-area edge rotated back to the prior POC. If there are
fewer than five attempts in the window it reports `null` and tells you the
sample is too small, rather than showing a number you might size a position on.

That rate is descriptive of the window you loaded. It is not a forecast, and it
is not a general statistic about markets.

## Data honesty

Every field is computed from the bars handed in. There are no placeholder
constants anywhere in the engine. When something is not derivable:

- The field is `null`.
- A sibling field states the reason.
- The UI renders an em dash and prints the reason.

Specifically, `trade_plan.risk_reward` is null whenever entry, stop and target
are not all derivable, or when reward-to-risk falls below 1.0, and
`risk_reward_unavailable_reason` says which. A risk-reward ratio you cannot
trace to three real levels is worse than no ratio at all.

The served timeframe is always reported in `bars_meta`. If the requested
timeframe had no bars on disk and a coarser one was substituted, `downgraded` is
true and the reason is stated. The UI shows this as a banner. You will never be
shown daily bars under a 15-minute label.

## Limits worth knowing

- **No intraday tape.** There is no minute or tick data in this repo, so volume
  is distributed uniformly across each bar's high-low range. That is the
  standard assumption when intra-bar prints are unavailable, and it is the same
  one the VPA engine makes, but a real Market Profile built from ticks will
  differ at the margins.
- **Initiative versus responsive activity is a proxy.** Without a tape, activity
  is classified from where each bar closed relative to value and to its own
  range, not from trades lifting the offer or hitting the bid.
- **TPO counts are per bar, not per 30-minute bracket.** On daily bars a "TPO"
  is a day. The shape reading still holds; the letter-by-letter Steidlmayer
  chart does not.
- **This is analysis, not advice.** The engine classifies an auction and
  computes levels. Position sizing, and whether to take the trade at all, is
  yours.

## Using it

Dashboard route `/amt`. Pick a symbol, a timeframe, and a lookback.

Read it in this order:

1. **Regime banner.** If it does not say `BALANCE`, the fade setups are off.
2. **Profile chart.** Where is price relative to the value area, and is the
   shape telling you value is being built high (P) or low (b) in the range?
3. **Location.** Is there a failed auction? That is your entry.
4. **Trade plan.** Entry, stop, targets, and the invalidation that voids it.
5. **Rotation statistics.** How often this actually worked in the loaded window.

API: `GET /api/amt/analyze?symbol=SPY&timeframe=1D&lookback=250`, plus
`/api/amt/health` for timeframe availability and `/api/amt/playbook` for the
rules and current thresholds.

Engine: `research/amt_engine.py`. Thresholds are all in one dict, `AMT_THRESHOLDS`.
