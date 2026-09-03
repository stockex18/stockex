# Market data: how prices are stored and served

Everything a user sees comes out of what the feed already wrote. Nothing on a
user's request path ever calls the upstream broker.

This document is the design and the reasoning, written so it can be rebuilt in
another deployment. Every number in it was measured on production.

---

## 1. The one rule

> **The broker is touched in exactly one place — the writer. Everything else
> reads storage.**

```
                  ┌──────────────────────────────────────────┐
   Kite WS ──────▶│  FEED LEADER  (exactly one worker)       │
                  │  guards → memory → storage               │
                  └──────────────┬───────────────────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
      Redis mdlive        Mongo ticks_*        Mongo tick_snapshots
      (30 s, hot)         (2 days, raw)        (30 days, per minute)
             │
             ▼
   every worker · every user   ── never calls Kite ──
```

Why it matters: before this, a user's quote request could issue a Kite REST
call behind a 2 s timeout. Production logged **6,078 `zerodha_overlay_timeout`**
— two seconds of a two-core event loop, each, for a price the mirror already
held.

---

## 2. Three storage layers, three jobs

| Layer | Where | Holds | Retention | Read by |
|---|---|---|---|---|
| `mdlive:{token}` | Redis | ltp, bid, ask, O/H/L/C, volume, age | **30 s** | every live quote and chart |
| `ticks_YYYY_MM_DD` | Mongo | one row per token per second | **2 days** | "what did it print at 11:42:07" |
| `tick_snapshots` | Mongo | per-minute bid/ask + OHLC high-low | **30 days** | admin rate-history / disputes |

They are all filled from the **same tick**, so the number on screen and the
number in the record cannot disagree.

Live display reads Redis, not Mongo. Reading Mongo per request would be slower
under load and buys nothing — Mongo is the **record**, not the live source.

### Sizing (measured)

```
tick rate            0.67 ticks/sec/token   (Kite full mode)
~1,500 tokens        ~2 crore rows/day
row size             ~200 bytes with index
ticks_*              ~3-4 GB/day  ×  2 days  =  6-8 GB steady
tick_snapshots       ~5 MB/day    ×  30 days =  150 MB
```

On a 2-core / 15 GB / 465 GB box this is not close to any limit.

---

## 3. Search: a catalogue, not a feed

**Searching subscribes nothing and shows no price.**

```
user types "cru"
      │
      ▼
GET /api/v1/user/instruments/search        ← catalogue only, no price field
      │
      ▼
rows render:  CRUDEOIL26SEP8550CE
              26 Sep · 8,550 · Lot 100          ← contract detail, no price
                                    [ ADD ]
```

### Why

Every search hit used to be quoted **and** put on the websocket. Typing "cru"
put forty CRUDEOIL strikes on the live feed. Production carried the bill:

```
subscribedInstruments   1,500   (at the LRU cap)
  symbol-less leftovers 1,237   (82%)
  actual futures           77   (futures carry 541 of all orders)
```

The cap was being spent on rows nobody traded, so the LRU evicted the
instruments that mattered — visible in the pool log as `tokens_dropped`. A
resting order could then find no price at all.

### Implementation

The backend search endpoint was already price-free. The bug was in the
frontend: search results were being put into the token list that drives
`quotesBatch` and `useMarketStream`.

- [`MobileInstrumentsBar.tsx`](frontend-user/components/trading/MobileInstrumentsBar.tsx) — `tokensKey` returns `[]` while searching or browsing
- [`InstrumentsPanel.tsx`](frontend-user/components/trading/InstrumentsPanel.tsx) — same rule

A search row also **ignores the live quote map entirely**, even for an
instrument already added: the map can still hold that token from the view the
user was just on, and one priced row among unpriced ones reads as if the others
were broken.

Rows show `expiry · strike · lot` instead — enough to tell two strikes of one
underlying apart. Two empty dashes where a spread belongs reads as a dead feed.

**What still gets prices:** the watchlist, and managed-segment chips. Those
*are* the added instruments.

---

## 4. Add: the moment price and storage begin

```
[ ADD ]
   │
   ├─ instrument goes into the watchlist / segment
   │
   ├─ "subscribe this" published on Redis  ← the request RETURNS HERE
   │
   ▼  (feed leader, asynchronously)
resolve symbol + exchange from the catalog
   │
   ▼
Kite WS subscribe + FULL mode
   │
   ▼  ~1-2 seconds
ticks arrive → guards → mdlive + ticks_* + tick_snapshots
   │
   ▼
every user reading that instrument now gets it from storage
```

The user's request never waits on Kite. The row shows "loading" for a moment,
then fills.

### One subscription serves everyone

| | 1 user | 50 users |
|---|---|---|
| Kite subscriptions | **1** | **1** |
| ticks processed | 1/sec | 1/sec |
| Redis writes | 1/sec | 1/sec |
| Mongo rows | 1/sec | 1/sec |
| Redis reads | 1 | 50 (cheap) |

**Feed cost does not grow with users.** Only reads do, and those are Redis.

Live updates fan out through one Redis publish per tick
(`market:tick:{token}`) which `MarketTickHub` pattern-subscribes to and routes
to every attached websocket.

### The symbol trap

A non-leader worker can only put **tokens** on the subscribe channel. The
leader used to re-subscribe them with no symbol, and the service then stored
`symbol = str(token)`, `exchange = "NSE"`. Three things broke silently:

1. Dual-account routing keys off `exchange` — MCX contracts marked NSE never
   moved to the second account
2. FULL mode is re-asserted by symbol — without it **no OHLC arrives**, so the
   day high/low the order gates read stayed 0
3. The admin panel showed a wall of bare numbers

Fixed by resolving symbol + exchange from the catalog in one batched query
before subscribing — `_sym_map_for` in
[`market_data_service.py`](backend/app/services/market_data_service.py).

---

## 5. Always-on core

Three index option chains are held permanently rather than subscribed per
viewer — nothing about their strikes is per-user and they are wanted every
session.

```
NIFTY · BANKNIFTY · SENSEX
   nearest live expiry
   ATM ± 6 strikes, both CE and PE
   ranked by distance from the money
   re-warmed every 5 minutes          ← the money moves during the day
```

52 tokens on the first production pass. A ladder warmed at 09:15 around 24,000
is the wrong ladder by afternoon if the index has travelled, hence the timer.

A guard refuses to warm anything if the ladder comes back far larger than
expected (>200) — silently subscribing hundreds of strikes would recreate the
flood this exists to end.

[`core_feed_warm.py`](backend/app/services/core_feed_warm.py)

---

## 6. Tick storage

[`tick_store.py`](backend/app/services/tick_store.py)

```
ticks_2026_09_03
   token · ts · ets · ltp · bid · ask · open · high · low · prev_close · volume
```

| Field | Meaning |
|---|---|
| `ts` | when **we** saw it |
| `ets` | the **exchange's** own clock — the column that settles a fill dispute |
| `prev_close` | Kite's `ohlc.close` is the PREVIOUS session's close; every change% is measured from it. Named as it arrives so nobody reads it as today's. |

### Four decisions worth keeping

**One collection per IST day.** Retention is then a `drop()` — instant however
many rows. A `deleteMany` over a few million documents is minutes of disk on
two cores, and near market hours it would take the feed down with it. Named by
IST because a dispute is phrased in the trading day it happened on; a UTC name
splits one session across two collections after 05:30 IST.

**Two days, not one.** A dispute arrives the morning after. One day's retention
throws the answer away before the question.

**Buffered, never per-tick.** `record()` is a list append and nothing else, so
the tick loop never waits on Mongo. A separate loop writes once a second in one
bulk insert. Unbuffered this is a few hundred inserts a second competing with
the feed for the same two cores.

**Raw motor, not the ODM.** Building a Document per row costs more than the
write at this volume, and these rows have no behaviour worth modelling.

### Safety details

- the buffer is **detached before the await**, so ticks arriving mid-write land
  in the next batch instead of vanishing with the list being inserted
- `insert_many(ordered=False)` — one rejected row cannot discard the batch
- `_MAX_BUFFER` drops the oldest rows if the writer stalls; being OOM-killed
  with the feed inside the process is worse
- a zero price is **skipped, not written** — a zero row reads back as a real
  print of zero, which is worse than a gap
- the `(token, ts)` index is created on an **empty** collection; adding it
  later to millions of rows would be an outage
- retention only touches names starting with the collection prefix — that check
  is the only thing between it and dropping `orders`

---

## 7. Read path

`_overlay_all(token, base, *, allow_rest)` in
[`market_data_service.py`](backend/app/services/market_data_service.py).

| Caller | `allow_rest` | Why |
|---|---|---|
| `get_quote` | **False** | user request |
| `get_quotes` | **False** | user request |
| `tick_loop` | **True** | warming a new instrument is the feed's job |

A request resolves in this order, none of which is a broker call:

```
mdlive (Redis)  →  _state (in-process)  →  ticks cache  →  mdlast (last known)
```

`mdlast` carries `last_ltp` — the last real price — for **display only**. The
API still sends `ltp: 0` when there is no live session, and the order gate
still refuses to fill against it. The UI labels it **"last close"** so a
remembered price is never mistaken for a live one.

---

## 8. The morning cycle

[`daily_feed_cycle.py`](backend/app/services/daily_feed_cycle.py)

```
07:30 IST   rebuild   core ladders re-warmed, held positions re-asserted
08:00 IST   sweep     tick collections past retention dropped
09:00 IST   MCX opens
09:15 IST   NSE opens
```

**On the clock, not on the broker token renewal.** That is not a style
preference: on this deployment the access token has failed to renew 484 times
in a row, and on the days it works it has landed as late as 09:12 — three
minutes before the open. Hanging the daily reset off an event that unreliable
means the reset either never happens or happens mid-session.

Each job runs at most once per IST day, inside a 20-minute window so a restart
on the mark does not skip the day.

**Failing safe:** a rebuild that throws leaves yesterday's subscriptions exactly
where they are. An empty universe is not a degraded platform, it is a stopped
one — every open position unpriced and the risk enforcer blind. Nothing in the
rebuild path can unsubscribe anything.

---

## 9. The guards that keep bad data out

These are what make "the database is correct" mean something.

### Thin-frame carry-forward
`zerodha_service._handle_parsed_ticks`

Broker frames are not uniform: an 8-byte LTP packet carries no OHLC block at
all, and a frame can arrive with no `last_price`. Every field is built as
`float(... or 0)`, so replacing the whole cached payload wrote hard zeros over
good live values.

A frame with no price is **not a price update**: hold the last real price, its
book, and its **exchange stamps**. Holding the stamps matters — restamping a
price we did not observe would make a dead feed look freshly observed to the
2-second order gate. `received_at` still advances, because that answers "is the
socket alive". A cold token with no price stays at 0, so 0 keeps meaning "no
live price".

This was the whole of *"rate goes to 0 for a second"* and *"high/low shows
wrong"* — never bad exchange data, only a thinner frame overwriting a fuller
one.

### Bad-tick spike filter
`_MAX_TICK_SPIKE_PCT = 0.5`, `_SPIKE_STALE_SEC = 30`

A >50% tick-to-tick jump is impossible for any real instrument, and a junk
price reaches the risk enforcer within a second: the stop-out fires, the
position closes at that price, and the phantom P&L is booked before anyone can
look. The tick is **dropped entirely**, so the previous price holds.

30 seconds, not 5: the feed reconnects periodically and illiquid contracts tick
sparsely, so a short window let a garbage tick right after a reconnect slip
through as "a real move". A genuine move that persists past the window is
accepted, so a price can never get permanently stuck.

### Bounded iteration sets
`prune_subscribed_numeric`

The LRU trim capped the websocket subscription but never touched `_subscribed`
/ `_state` — and **those** are the sets `tick_loop` walks. They grew all session
as traders browsed option chains, the loop overlaid every one per pass on one
core, and every published price went seconds stale. *"Rates freeze"* was a loop
that could not finish its lap, not a dead feed.

### Freshness
`_QUOTE_STALE_SEC = 2.0` from the **exchange** stamp, not our own.

Deliberately not `ts`: the tick loop rewrites that every second whether or not
the price moved, which is precisely why a frozen quote looked live.

Note: illiquid contracts legitimately exceed 2 s between prints. On production
this marked ~23 of 59 tokens stale — NICKEL at 68 s, VEDL at 35 s. That is
correct behaviour, but the threshold is worth tuning per exchange.

### Day-range order gate
`order_validator.day_range_block`

```
low <= price <= high   →  reject      (bounds inclusive)
```

And the hole that was closed: the rule used to **stand aside silently** when
high/low was 0, which is why it applied to some contracts and not others. Now,
if the session is demonstrably live (`stale is False`) and the range is still
missing, the order is **refused** rather than guessed at.

### Resting-order watermark
`Order.range_ref_high` / `range_ref_low`

The poller fires a parked order when the session extreme reaches its level —
that catches a level the tape traded through with no LTP tick on the far side.
But an extreme made **before** the order existed is history. Without a
watermark, a BUY LIMIT parked under a low the day had already printed filled
the instant it was accepted:

```
DIVISLAB   BUY LIMIT 9200.25   filled with the tape at 9308    (day low 9155)
BAJAJ-AUTO BUY LIMIT 12230     filled with the tape at 12462   (day low 12152)
```

23 of 28 production fires were this, from the same handful of accounts. The
order now carries the range it was parked against, and the extreme must have
moved **beyond** it.

---

## 10. File map

| File | Role |
|---|---|
| `backend/app/services/zerodha_service.py` | WS pool, tick parsing, spike filter, carry-forward, dual-account routing |
| `backend/app/services/market_data_service.py` | overlay, `_state`, mdlive mirror, tick loop, subscribe plumbing, prune |
| `backend/app/services/tick_store.py` | 2-day raw tick storage + retention |
| `backend/app/services/tick_aggregator.py` | 30-day per-minute bid/ask history |
| `backend/app/services/core_feed_warm.py` | the three index chains, held |
| `backend/app/services/daily_feed_cycle.py` | 07:30 rebuild, 08:00 sweep |
| `backend/app/services/order_validator.py` | day-range gate, freshness gate, affordability |
| `backend/app/services/matching_engine.py` | resting-order poller + watermark |
| `backend/app/models/zerodha_feed_routing.py` | dual-account routing config |
| `frontend-user/components/trading/MobileInstrumentsBar.tsx` | mobile search / watchlist |
| `frontend-user/components/trading/InstrumentsPanel.tsx` | desktop equivalent |

### Loops, all leader-gated

| Loop | Interval |
|---|---|
| `tick_loop` | 1 s |
| `tick_store_flush_loop` | 1 s (retention sweep hourly) |
| `tick_aggregator_flush_loop` | 60 s |
| `core_feed_warm_loop` | 5 min |
| `daily_feed_cycle_loop` | 60 s |
| `open_position_subscription_loop` | 2 min |
| `feed_failover_loop` | 3 s |

All live in the worker holding the `leader:feed` lock, because they read or
steer that worker's in-process price state. Anywhere else they are silent
no-ops.

---

## 11. Verified on production

Measured during a live session, 09:53 IST:

```
ticks_2026_09_03        18,04,739 rows · 63 instruments
zerodha live tokens     59
  zero LTP               0
  zero high/low          0
  zero bid/ask           0
tick_snapshots          488 rows / 10 min
subscriptions           256   (NFO 119 · BFO 64 · NSE 51 · MCX 22)
```

Before the work:

```
on-demand subscribes    41,251
subscriptions           1,500 (at cap) · 1,237 symbol-less · tokens_dropped
overlay REST timeouts   6,078
```

---

## 12. Rebuilding this elsewhere — order of work

1. **Bounded iteration sets** — cheapest fix, biggest immediate effect on
   staleness
2. **Spike filter and thin-frame carry-forward** — stops bad data reaching the
   risk engine
3. **Search decoupled from price and subscription** — stops the list filling
4. **Symbol resolution on the subscribe path** — without it, routing and FULL
   mode are both silently broken
5. **Per-minute history** — cheap, and it is what answers a dispute
6. **Raw tick store** — only once the above are stable
7. **Read path off the broker** — do this near market close, every quote goes
   through it
8. **Morning cycle**
9. **Second broker account + failover** — a business decision, not code

Each step ships and is verified separately. Money is moving through this; if
something breaks, it has to be obvious which change did it.

## 13. Known limits

- **Sampling.** Ticks are captured at the tick loop's 1 s cadence, where the
  feed is already overlaid and is what the user actually saw. Kite publishes at
  roughly that rate anyway (measured 0.67/sec/token). For sub-second
  granularity, hook the websocket handler instead and keep the buffer/flush
  unchanged.
- **Crypto options carry no OHLC.** Binance does not send it, so high/low are 0
  on those (147 of 148 tokens). Deliberately left alone.
- **The store is a faithful record, not an oracle.** It is filled by the feed.
  A wrong price that passes the spike filter is stored wrongly. The guards
  catch the realistic failure modes; they cannot make the broker correct.
- **One broker account is a single point of failure.** The token expires daily
  and must be renewed. Dual-account failover is implemented and tested but
  inert until a second account is configured.
