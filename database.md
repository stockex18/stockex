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

---

# 14. Prompt — hand this to Claude in the new project

Everything above describes a finished system. This section is the *instruction*
that produces it. Paste it into a fresh session in the target repo. It assumes
no knowledge of this deployment.

Read it once before pasting: the diagnostics in step 0 decide how much of it
applies. A codebase that already reads prices from storage needs only parts.

---

````text
I run a trading platform. Prices come from a broker websocket (Kite Connect /
Zerodha, or a similar tick feed). I want the market-data layer rebuilt so that:

  THE ONE RULE: the broker is called in exactly ONE place — the process that
  writes prices into storage. Nothing on a user's request path ever calls it.
  Every user reads what the feed already stored.

Work through this in order. Each step ships and is verified SEPARATELY — money
moves through this system, so if something breaks it has to be obvious which
change did it. Do not batch them.

------------------------------------------------------------------------
STEP 0 — MEASURE FIRST. Change nothing yet.

Report real numbers from MY codebase and MY production logs before proposing
any edit. I want to know which of these problems I actually have:

  a) Does a user's quote request ever call the broker over HTTP? Trace the
     read path from the quote endpoint down. Count request/overlay timeouts
     in the logs.

  b) How many instruments are subscribed on the websocket right now, and what
     is the cap? How many of those carry a real symbol, and how many carry
     only a token number? Group them by exchange.

  c) Does SEARCHING or BROWSING the instrument list cause a subscription?
     Count on-demand subscribe events in the logs.

  d) Does the tick loop iterate a bounded set? Find the set it walks and
     compare its size to the websocket cap. If a trim exists, check whether it
     trims BOTH the websocket list and the loop's iteration set.

  e) Can a tick with a zero or missing price overwrite a good cached price?
     Read the websocket tick handler line by line.

  f) Is there any filter on an impossible tick-to-tick price jump?

  g) What price history is persisted, and for how long?

Show me the numbers. Then we decide what to build.

------------------------------------------------------------------------
STEP 1 — Bound the tick loop's iteration set

Cheapest fix, biggest immediate effect. If the LRU trim caps the websocket
subscription but does not trim the sets the tick loop actually walks, those
sets grow all session as users browse. The loop then overlays every one of them
per pass on one core and EVERY published price goes seconds stale. Users report
this as "the rates freeze". It is not a dead feed — it is a loop that cannot
finish its lap.

Trim both sets to the same keep-set, from BOTH exits of the trim function —
including the early return when the list is already within budget. That one is
easy to miss and leaves the sets bloated forever.

------------------------------------------------------------------------
STEP 2 — Stop bad ticks at the source

Two guards, both in the websocket tick handler, before anything is cached.

(a) A FRAME WITH NO PRICE IS NOT A PRICE UPDATE.
    Broker frames are not uniform — a short LTP-only packet carries no OHLC
    block at all, and a frame can arrive with no last price. If every field is
    built as float(x or 0) and the whole cached payload is replaced, a thin
    frame writes hard zeros over good live values.

    Carry forward: last price, book, OHLC, AND the exchange timestamps.
    Holding the stamps matters — restamping a price you did not observe makes a
    dead feed look freshly observed to any staleness gate. Keep advancing the
    frame-arrival time, because that answers "is the socket alive".

    A token that has NEVER had a price stays at zero, so zero keeps meaning "no
    live price" and nothing fills against it.

(b) SPIKE FILTER. Reject a tick whose price jumps more than 50% from the last
    good one, UNLESS that last good one is older than 30 seconds. Drop the tick
    entirely so the previous price holds.

    50% tick-to-tick is impossible for a real instrument. A junk price reaches
    the risk engine within a second: the stop-out fires, the position closes at
    that price, and phantom P&L is booked before anyone can look.

    30 seconds, not 5: feeds reconnect and illiquid contracts tick sparsely, so
    a short window lets garbage right after a reconnect through as "a real
    move". A genuine move that persists past the window is accepted, so a price
    can never get permanently stuck.

------------------------------------------------------------------------
STEP 3 — Searching is browsing a catalogue, not watching an instrument

A search result must subscribe NOTHING and show NO price.

Typing three letters used to put dozens of option strikes on the live feed. The
subscription list fills to its cap with rows nobody trades, the LRU then evicts
the instruments that carry the actual order flow, and a resting order can find
no price at all.

  - the search endpoint returns catalogue fields only (symbol, expiry, strike,
    lot size). Check whether it already includes a price.
  - the FRONTEND is usually where the bug is: search results get put into the
    token list that drives batch quotes and the websocket stream. Take them
    out. Browse and segment listings too — same reasoning.
  - a search row must ALSO ignore the live quote map entirely, even for an
    instrument already added. The map can still hold that token from the view
    the user was just on, and one priced row among unpriced ones reads as if
    the others were broken.
  - show expiry, strike and lot size where the price was. Two empty dashes
    where a spread belongs reads as a dead feed.
  - the add control should say "ADD", not show a plus glyph. Adding is now what
    starts the price and the storage for that instrument.

WHAT MUST KEEP ITS PRICES: the user's watchlist, and any list of instruments
they explicitly added. Those ARE the added ones. Write a test that pins this —
breaking it blanks the user's own watchlist.

------------------------------------------------------------------------
STEP 4 — Resolve the symbol on the subscribe path

If the app runs more than one worker, a non-leader can usually only put TOKEN
NUMBERS on the internal subscribe channel. The leader then subscribes them with
no symbol and stores symbol = str(token) with a default exchange.

Three things break silently, with no error anywhere:
  - any routing that keys off exchange sends those tokens to the wrong place
  - FULL/depth mode is re-asserted BY SYMBOL — without it NO OHLC ARRIVES, so
    the day high/low that order gates read stays zero
  - the admin panel shows a wall of bare numbers

Resolve symbol + exchange from the instrument catalog in ONE batched query
before subscribing. Skip anything the catalog cannot name rather than faking
it. A lookup failure must never block the subscribe — a held position with no
price is worse than a slow one.

ALSO: check whether the catalog ITSELF holds rows whose symbol is their own
token number. If an earlier version mirrored the broken subscription list into
the catalog, the resolver looks a token up and "resolves" it to itself. Clean
those rows — but never one held in an open position, sitting in a watchlist, or
with a resting order against it.

------------------------------------------------------------------------
STEP 5 — Per-minute price history

One row per instrument per minute: bid high/low, ask high/low, OHLC, volume.
30-day retention. Costs a few MB a day.

This is what answers "the rate was wrong at 11:42". Bid and ask are in no
candle feed anywhere, so once the minute passes it is gone forever. Without it
neither side of that argument can be settled.

Fold it in the tick loop with a synchronous, allocation-light call; persist
completed minutes from a separate loop. Never write the minute still filling —
a partial range stored as a whole minute is worse than no row at all.

------------------------------------------------------------------------
STEP 6 — Raw tick store, short retention

Only once everything above is stable.

  one collection PER DAY, named for the LOCAL trading day
  fields: token, our timestamp, EXCHANGE timestamp, ltp, bid, ask,
          open, high, low, previous close, volume
  retention: 2 days

Every one of those is load-bearing:

  - ONE COLLECTION PER DAY, because retention is then a DROP: instant however
    many million rows. A bulk delete over millions of documents is minutes of
    disk, and anywhere near market hours it takes the feed down with it.
  - LOCAL trading day in the name, because a dispute is phrased in the day it
    happened. A UTC name splits one session across two collections.
  - TWO DAYS, because a dispute arrives the MORNING AFTER. One day's retention
    throws the answer away before the question arrives.
  - THE EXCHANGE TIMESTAMP as its own column. Your server clock does not settle
    an argument about a fill; the exchange's clock does.
  - PREVIOUS CLOSE named as such. The broker's ohlc.close is the PREVIOUS
    session's close and every change% is measured from it. Calling it "close"
    in a row stamped with today's date is how someone reads it as today's.

Write path: buffer in memory (a list append and nothing else — the tick loop
must never wait on the database), flush once a second in one bulk insert.

  - detach the buffer BEFORE the await, so ticks arriving mid-write land in the
    next batch instead of vanishing with the list being inserted
  - unordered insert, so one rejected row cannot discard the batch
  - cap the buffer and drop the oldest if the writer stalls. Being killed for
    memory with the feed inside the process is worse than losing some rows.
  - SKIP a zero price, never store it. A zero row reads back as a real print of
    zero, which is worse than a gap.
  - create the index on the EMPTY collection. Adding it later to millions of
    rows is an outage.
  - retention must only touch collections matching its own name prefix. That
    check is the only thing standing between it and your orders collection.

------------------------------------------------------------------------
STEP 7 — Take the broker off the read path

Do this near market close. Every quote in the system goes through it.

Give the overlay function an explicit flag. The feed loop passes true — warming
a newly added instrument is its job. Every user-facing quote path passes false.

A request then resolves from the hot cache, in-process state, the tick cache,
and a last-known-price fallback. None of those is a broker call.

Keep the last-known price for DISPLAY only, clearly labelled ("last close" or
similar). The API should still report a zero live price when there is no live
session, and the order gate should still refuse to fill against it. Showing a
remembered price is fine. Filling at one is not.

------------------------------------------------------------------------
STEP 8 — A morning cycle on the clock

  07:30 local   rebuild: re-warm the always-on instruments, re-assert every
                token held in an open position
  08:00 local   sweep: drop tick collections past retention

Both before the earliest market opens.

ON THE CLOCK, NOT ON THE BROKER TOKEN RENEWAL. This matters more than it
sounds. Our access token failed to renew 484 times in a row, and on the days it
worked it landed as late as three minutes before the open. Hanging the daily
reset off an event that unreliable means the reset either never happens or
happens mid-session. A clock always fires.

Run each job at most once per local day, inside a window wide enough (~20 min)
that a restart on the mark does not skip the day.

FAILING SAFE IS THE POINT: a rebuild that throws must leave yesterday's
subscriptions exactly where they are. An empty universe is not a degraded
platform, it is a stopped one — every open position unpriced and the risk
engine blind. Nothing in the rebuild path may unsubscribe anything.

------------------------------------------------------------------------
STEP 9 — Hold the instruments everyone opens

The two or three index option chains every user opens do not need to be
subscribed per viewer. Warm them and hold them:

  nearest live expiry, ATM +/- 6 strikes, both sides
  ranked BY DISTANCE FROM THE MONEY, not by whatever sorts first
  keep STRIKES, not rows, or a call-heavy ladder crowds out the puts
  re-warm every 5 minutes — a ladder warmed at the open is the wrong ladder by
  afternoon if the index has travelled

Guard it: if the ladder comes back far larger than expected, warm NOTHING
rather than quietly subscribing hundreds of strikes and recreating the flood
this exists to end.

------------------------------------------------------------------------
CROSS-CUTTING RULES

  - Every background loop lives in the ONE process holding the feed-leader
    lock, because they read or steer that process's in-memory price state.
    Anywhere else they are silent no-ops. Verify by checking the process id in
    the logs, not by assuming.
  - Never swallow a failure at debug level in a path that writes data. A
    silently swallowed flush error is invisible data loss: the loop keeps
    running, buffers keep filling and dropping, and nothing anywhere says the
    history stopped being written. Log it at warning.
  - Every non-trivial change leaves ONE runnable check behind that fails if the
    logic breaks. Pin the things that would otherwise be silent: the watchlist
    still gets prices, retention never drops today, the zero guard still holds.
  - Tell me honestly what a change does NOT fix. I would rather know a risk
    remains than be told everything is perfect.

------------------------------------------------------------------------
HOW TO VERIFY, ON A LIVE SESSION

Run these during market hours and show me the output:

  1. count rows in today's tick collection, and distinct instruments in it
  2. print the newest row in full — is every field populated?
  3. across live broker tokens: how many have a zero price, a zero high/low, or
     a zero bid/ask? All three should be ZERO.
  4. subscription count, and how many carry only a token as their symbol
  5. rows written to the per-minute history in the last ten minutes
  6. search for something in the UI — does the on-demand subscribe count stay
     flat? It must.
  7. add one instrument — does its price appear within a couple of seconds?
  8. open a watchlist and a position — do both still show live prices?

If any number surprises you, say so before moving on.
````

---

## Using this on an existing codebase

The steps assume the problems are present. Step 0 tells you which are. Skip
what does not apply — but read the reasoning first, because several of these
fail *silently*: no error, no log line, just wrong prices or a gate that has
quietly stopped applying. Step 4 in particular breaks two unrelated things with
no symptom pointing at it.

## What this prompt will NOT give you

- **A second broker account.** Step 8's reasoning explains why the daily token
  is unreliable, but redundancy needs a second paid account. That is a business
  decision, and until it exists one dead token is still a dead feed.
- **Correct prices from an incorrect broker.** The store is a faithful record,
  not an oracle. The guards catch the realistic failure modes — a zero, a
  thin frame, an impossible jump — but a plausible-looking wrong price will be
  stored faithfully as what the broker said.
- **Sub-second granularity**, if ticks are sampled at the tick loop's cadence.
  That is usually the right trade (most feeds publish about once a second
  anyway), but say so out loud rather than implying every print is captured.
