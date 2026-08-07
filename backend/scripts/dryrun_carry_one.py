"""Read-only dry-run: for a given position code/id, show exactly what the
EOD carry (convert_intraday_to_carry) WOULD do — how much carries, how much
squares off, at what margin. Executes NOTHING.

    python -m scripts.dryrun_carry_one CL52765183
"""
import asyncio
import sys
from decimal import Decimal

from app.core.database import init_database as init_db
from app.models.position import Position, PositionStatus
from app.services import netting_service, wallet_router, market_data_service
from app.services.market_data_service import is_usd_quoted_segment, get_usd_inr_rate
from app.utils.decimal_utils import to_decimal, quantize_money


def D(x):
    return to_decimal(x)


async def main(code: str):
    await init_db()

    # Match by position_id, order code, or symbol contains.
    pos = None
    for q in (
        {"position_id": code},
        {"code": code},
        {"_id": code},
    ):
        try:
            pos = await Position.find_one(q)
        except Exception:
            pos = None
        if pos:
            break
    if pos is None:
        # brute: scan open positions, match any string field == code
        rows = await Position.find({"status": PositionStatus.OPEN.value}).to_list()
        for p in rows:
            for v in (getattr(p, "position_id", None), str(p.id)):
                if v and str(v) == code:
                    pos = p
                    break
            if pos:
                break
    if pos is None:
        print(f"NOT FOUND: {code}")
        print("Open crypto positions:")
        rows = await Position.find({"status": PositionStatus.OPEN.value}).to_list()
        for p in rows:
            if "CRYPTO" in (p.instrument.segment or "").upper():
                print(f"  id={p.id} pid={getattr(p,'position_id',None)} {p.instrument.symbol} qty={p.quantity} pt={p.product_type.value}")
        return

    print("=" * 70)
    print(f"POSITION  id={pos.id}  pid={getattr(pos,'position_id',None)}")
    print(f"  symbol={pos.instrument.symbol}  segment={pos.instrument.segment}  seg_type={pos.segment_type}")
    print(f"  qty={pos.quantity}  lot_size={pos.instrument.lot_size}  avg={pos.avg_price}  ltp(stored)={getattr(pos,'ltp',None)}")
    print(f"  product_type={pos.product_type.value}  margin_used(locked now)={pos.margin_used}")
    print(f"  user_id={pos.user_id}")

    _osym = (pos.instrument.symbol or "").upper()
    _otype = (
        ("CE" if _osym.endswith("CE") else "PE" if _osym.endswith("PE") else None)
        if len(_osym) >= 3 and _osym[-3].isdigit()
        else None
    )
    resolved = await netting_service.get_effective_settings(
        pos.user_id, pos.instrument.segment,
        action="BUY" if pos.quantity >= 0 else "SELL",
        option_type=_otype, product_type="NRML", symbol=pos.instrument.symbol,
    )
    s = resolved.get("settings") or {}
    print("-" * 70)
    print("EFFECTIVE OVERNIGHT SETTINGS:")
    for k in ("margin_calc_mode", "min_lot", "leverage", "overnight_leverage",
              "margin_percentage", "overnight_margin_percentage",
              "fixed_margin_per_lot", "overnight_fixed_margin_per_lot"):
        print(f"    {k} = {s.get(k)}")

    cur_avg = D(pos.avg_price)
    cur_qty_abs = D(abs(pos.quantity))
    notional = cur_avg * cur_qty_abs

    ovn_fixed = D(s.get("overnight_fixed_margin_per_lot") or 0)
    if s.get("margin_calc_mode") == "fixed" and ovn_fixed > 0:
        lot_size = max(1, int(pos.instrument.lot_size or 1))
        lots = cur_qty_abs / D(lot_size)
        new_margin = ovn_fixed * lots
    else:
        pct = D(s.get("overnight_margin_percentage") or 100.0) / D(100)
        lev = D(s.get("overnight_leverage") or 1.0) or D(1)
        new_margin = notional * pct / lev

    usd = is_usd_quoted_segment(pos.segment_type) or is_usd_quoted_segment(pos.instrument.segment)
    rate = D(get_usd_inr_rate()) if usd else D(1)
    if usd and not (s.get("margin_calc_mode") == "fixed" and ovn_fixed > 0):
        new_margin = new_margin * rate
    new_margin = quantize_money(new_margin)
    old_margin = D(pos.margin_used)
    delta = new_margin - old_margin

    _sign = D(1 if pos.quantity > 0 else -1)
    # Optional 2nd CLI arg = simulated LTP (to prove PnL moves the carry qty).
    _sim = sys.argv[2] if len(sys.argv) > 2 else None
    if _sim:
        ltp = D(_sim)
    else:
        try:
            ltp = D(await market_data_service.get_ltp(pos.instrument.token))
        except Exception:
            ltp = D(0)
        if ltp <= 0:
            ltp = D(getattr(pos, "ltp", None) or 0)
        if ltp <= 0:
            ltp = cur_avg
    unreal = (ltp - cur_avg) * cur_qty_abs * _sign
    if usd:
        unreal = unreal * rate

    wallet = await wallet_router.get(pos.user_id, pos.segment_type)
    avail = D(wallet.available_balance)
    credit = D(wallet.credit_limit)

    print("-" * 70)
    print(f"USD-quoted={usd}  USD_INR={rate}  live/mark LTP used={ltp}")
    print(f"  notional (USD)         = {notional}")
    print(f"  NEW overnight margin   = {new_margin}  (INR, whole position)")
    print(f"  OLD locked margin      = {old_margin}")
    print(f"  delta (extra needed)   = {delta}")
    print(f"  floating P&L (unreal)  = {unreal}  (INR)")
    print(f"  wallet available       = {avail}")
    print(f"  wallet credit_limit    = {credit}")

    affordable = (avail + credit + unreal) >= delta
    print("-" * 70)
    print(f"AFFORDABLE (carry WHOLE)? (avail + credit + unreal) >= delta")
    print(f"    ({avail} + {credit} + {unreal}) = {avail+credit+unreal}  >= {delta}  -> {affordable}")

    if not (delta > 0 and not affordable):
        print("=" * 70)
        print(">>> RESULT: FULL CARRY — poori 150 qty carry ho jayegi, kuch close nahi.")
        return

    # Partial carry math
    funds = avail + old_margin + unreal + credit
    lot_size = max(1, int(pos.instrument.lot_size or 1))
    step_lot = D(s.get("min_lot") or 1)
    if step_lot <= 0:
        step_lot = D(1)
    min_qty = quantize_money(step_lot * D(lot_size))

    carriable_qty = D(0)
    raw_lots = D(0)
    steps = 0
    if funds > 0 and new_margin > 0:
        raw_lots = (cur_qty_abs * funds / new_margin) / D(lot_size)
        steps = int(raw_lots / step_lot)
        carriable_qty = quantize_money(D(steps) * step_lot * D(lot_size))
        if carriable_qty > cur_qty_abs:
            carriable_qty = cur_qty_abs

    print("-" * 70)
    print("PARTIAL CARRY MATH:")
    print(f"    funds (avail + old_margin + unreal + credit) = {funds}")
    print(f"    step_lot(min_lot) = {step_lot}   lot_size = {lot_size}   min_qty = {min_qty}")
    print(f"    raw_lots = qty*funds/new_margin/lot_size = {raw_lots}")
    print(f"    steps (floored) = {steps}")
    print(f"    carriable_qty = {carriable_qty}")

    print("=" * 70)
    if carriable_qty < min_qty:
        print(f">>> RESULT: CARRY FAIL — 1 min-lot bhi afford nahi, POORI {cur_qty_abs} qty CLOSE.")
    else:
        square_qty = cur_qty_abs - carriable_qty
        carry_margin = quantize_money(new_margin * carriable_qty / cur_qty_abs)
        print(f">>> RESULT: PARTIAL CARRY")
        print(f"      CARRY forward : {carriable_qty} qty   (locks ~{carry_margin} INR overnight margin)")
        print(f"      CLOSE/square  : {square_qty} qty   @ ~{ltp} (last mark)")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
