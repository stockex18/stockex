# Paste-ready prompt — implement circuit limits in another project

Self-contained on purpose: the target project won't have `circuit-limits.md`,
so the whole spec is inlined. Copy everything below the line.

---

Implement upper/lower circuit (daily price band) enforcement for stock/F&O
orders in this codebase, matching real exchange behaviour.

First explore the repo and tell me where things live before writing code:
the order-placement validation path, how instruments/exchanges are modelled,
where live LTP comes from, how open positions are looked up, whether there's
a broker feed exposing circuit limits, and which component renders the order
ticket (buy/sell buttons). Adapt everything below to the existing patterns —
do not introduce a new cache/HTTP/state library.

## What a circuit is

Every Indian-exchange scrip has a daily price band: a floor (lower circuit)
and ceiling (upper circuit). Price cannot trade outside it. When price hits an
edge the scrip is "circuit-locked" — and the lock is DIRECTIONAL, not a halt:

- At UPPER circuit: everyone wants to buy, nobody sells. Only SELL executes.
- At LOWER circuit: everyone wants to sell, nobody buys. Only BUY executes.

Blocking all trading on a locked scrip is wrong. Blocking the locked side
unconditionally is also wrong — see the exit exemption, which is the whole
point of this task.

## Where the band comes from

Do NOT compute it as previous_close × percentage. The band % depends on the
scrip's surveillance category, which is not in the instrument master; you will
be wrong on exactly the scrips that matter. Take it from the broker feed —
Zerodha's quote() returns `lower_circuit_limit` / `upper_circuit_limit`
(Angel One: `lowerCircuit` / `upperCircuit`).

Requirements for the fetch helper, returning `(lower, upper)` with either
possibly null:

1. Cache per instrument per day (band changes only at session start). Do not
   call the broker quote API on every order — it's slow and rate-limited.
2. Return "no band" immediately for exchanges that have none — crypto, forex,
   metals, anything fed from an international 24x7 provider. Allow-list the
   band exchanges (NSE, BSE, NFO, BFO, MCX, CDS).
3. FAIL OPEN. Quote throws, cache cold, feed session dead → return no band.
   A missing band must NEVER block trading. Fail-closed means one broker API
   hiccup halts the platform.
4. Normalise 0 to null. Feeds send 0 for "unknown", and `price >= 0` is true
   for every price — treating 0 as a real ceiling locks EVERY instrument at
   the upper circuit. This is the #1 bug here.

## The rules

Given lower/upper (either may be null), `cur` = live market price, and
`ref_price` = the limit price for LIMIT/SL orders or the side-appropriate
bid/ask for MARKET orders:

Rule 1 — directional lock:
  cur >= upper AND action == BUY  → reject (code UPPER_CIRCUIT_BUY)
  cur <= lower AND action == SELL → reject (code LOWER_CIRCUIT_SELL)

Rule 2 — price outside the band:
  ref_price > upper → reject (code UPPER_CIRCUIT)
  ref_price < lower → reject (code LOWER_CIRCUIT)
  (catches a LIMIT parked outside the band, which the exchange would reject
  at entry rather than letting it sit pending forever)

Rule 3 — EXITS ARE EXEMPT from rules 1 and 2. See below.

Guard every comparison on the limit being non-null AND on `cur > 0` /
`ref_price > 0`. Outside market hours LTP is frequently 0, and `0 <= lower`
is true — an unguarded lower check blocks every order the moment the feed
goes quiet.

Use distinct error codes: the UI renders a directional hint ("only SELL
allowed") differently from a price complaint ("your limit is above the
ceiling"). Same band, different fix for the user.

## The exit exemption — the critical part

A trader must ALWAYS be able to close a position. The band stops you OPENING
into a locked side; it must not become a trap.

Compute before the gate, and skip the entire gate when either is true:

    signed_held   = position.quantity / lot_size   (+ long, − short, 0 flat)
    delta         = +lots if BUY else -lots
    projected_net = signed_held + delta
    is_reducing   = abs(projected_net) < abs(signed_held)

    is_squareoff  = admin/risk-engine auto-flatten (margin call, stop-out).
                    This must bypass EVERY gate, circuit included.

Resulting matrix — the two starred rows are what a naive implementation
breaks, and they break SILENTLY (nobody reports it until someone is trapped):

    LONG  at upper circuit → close via SELL → allowed (unlocked side anyway)
    LONG  at lower circuit → close via SELL → allowed VIA EXEMPTION ONLY  ***
    SHORT at upper circuit → close via BUY  → allowed VIA EXEMPTION ONLY  ***
    SHORT at lower circuit → close via BUY  → allowed (unlocked side anyway)
    flat  at either        → opening into the locked side → rejected

CRITICAL: the position lookup keys in the validator must be IDENTICAL to the
keys your matching/execution engine uses to merge fills into a position. If
they differ (e.g. one filters by segment while the other filters by product
type), `signed_held` reads 0, `is_reducing` is always false, and the exemption
silently never fires. Verify this explicitly and tell me what you found.

Note if this is a B-book platform (orders fill internally at LTP rather than
routing to the exchange): honouring the exit is both correct and executable,
since there's no absent counterparty. On a real routing broker the exit order
would be accepted and queue unfilled. Either way — ACCEPT it, never reject.

## Enforcement points

Backend: one gate in the order validator, before margin is computed. This is
authoritative.

Frontend: mirror it in the order ticket so the user sees the lock BEFORE
tapping rather than as a rejection toast after. The mirror MUST include the
exit exemption — otherwise you rebuild the trap in the UI even though the
backend allows the order.

Expose the band on whatever per-instrument settings call the order ticket
already makes, so it costs no extra round-trip. In the UI: disable the submit
button, guard the submit handler with the same condition, and show a banner
naming the band and the allowed direction. When the order would reduce, say so
explicitly — "Closing your open position is still allowed" — otherwise a user
staring at a red banner won't try.

If the ticket reads positions from a cache another component already polls,
subscribe read-only (no refetch on mount, infinite stale time) so this check
doesn't introduce its own refetch and disturb any optimistic-update handling.

## Fail-open matrix — every one of these must resolve to TRADING ALLOWED

    broker feed disconnected / quote throws  → no band → no block
    cache layer down                         → no band → no block
    non-band exchange (crypto/forex/metals)  → no band → no block
    feed returns 0 for a limit               → that limit becomes null
    LTP is 0 (market closed / stale feed)    → cur > 0 guard fails → no block
    order is reducing or square-off          → exempt → no block

The ONLY blocking state: a real band, a real live price at or beyond it, and
a NEW order into the locked side.

## Tests — write these, and run 5/6/8 through the UI, not just the API

     1. flat, at upper circuit, BUY  → rejected UPPER_CIRCUIT_BUY
     2. flat, at upper circuit, SELL → accepted
     3. flat, at lower circuit, SELL → rejected LOWER_CIRCUIT_SELL
     4. flat, at lower circuit, BUY  → accepted
     5. holding SHORT, at upper circuit, BUY to cover → ACCEPTED
     6. holding LONG,  at lower circuit, SELL to exit → ACCEPTED
     7. partial close of 5/6 → accepted (is_reducing is true for partials)
     8. holding LONG at upper circuit, BUY MORE → rejected (adds, not reduces)
     9. LIMIT priced above upper → rejected UPPER_CIRCUIT
    10. risk-engine stop-out at either circuit → executes (is_squareoff)
    11. band unavailable (kill the feed) → all orders pass
    12. crypto/forex instrument → gate never engages

Report honestly which tests you actually ran versus reasoned about, and don't
claim the UI cases pass unless you drove the UI.
