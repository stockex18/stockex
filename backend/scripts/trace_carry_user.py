"""Read-only: trace one client's MCX carry-forward flow. Shows every MCX
order + open/closed position in time order so we can see EXACTLY how the EOD
rollover split each position (carried qty vs squared qty, at what price).

    python -m scripts.trace_carry_user CL29368663 MCX
"""
import asyncio
import sys

from app.core.database import init_database
from app.models.user import User
from app.models.order import Order
from app.models.position import Position


def f(x):
    try:
        return f"{float(str(getattr(x, 'to_decimal', lambda: x)())):,.2f}" if x is not None else "-"
    except Exception:
        return str(x)


def ist(dt):
    if not dt:
        return "-"
    # stored UTC → +5:30
    from datetime import timedelta
    return (dt + timedelta(hours=5, minutes=30)).strftime("%d-%b %H:%M:%S")


async def main(code: str, seg_prefix: str):
    await init_database()
    user = await User.find_one({"user_code": code})
    if not user:
        print(f"NO USER {code}")
        return
    print(f"USER {code}  id={user.id}  {user.full_name}")

    # Orders in this segment group
    orders = await Order.find({"user_id": user.id}).to_list()
    orders = [o for o in orders if seg_prefix.upper() in (o.instrument.segment or "").upper()]
    orders.sort(key=lambda o: o.created_at or o.id.generation_time)

    print("\n" + "=" * 100)
    print("ORDERS (time order):")
    print(f"{'time IST':<16}{'sym':<20}{'act':<5}{'type':<8}{'pt':<5}{'qty':>10}{'fill':>10}{'avgpx':>11}  flags")
    for o in orders:
        flags = []
        if o.is_squareoff:
            flags.append("SQUAREOFF")
        if o.placed_from:
            flags.append(o.placed_from)
        if o.close_reason:
            flags.append(f"reason={o.close_reason}")
        print(
            f"{ist(o.created_at):<16}{(o.instrument.symbol or '')[:19]:<20}"
            f"{o.action.value:<5}{o.order_type.value:<8}"
            f"{(o.product_type.value if o.product_type else '-'):<5}"
            f"{o.quantity:>10}{o.filled_quantity:>10}{f(o.average_price):>11}  {' '.join(flags)}"
        )

    # Positions in this segment group
    poss = await Position.find({"user_id": user.id}).to_list()
    poss = [p for p in poss if seg_prefix.upper() in (p.instrument.segment or "").upper()]
    poss.sort(key=lambda p: (p.opened_at or p.id.generation_time))

    print("\n" + "=" * 100)
    print("POSITIONS:")
    for p in poss:
        st = p.status.value if hasattr(p.status, "value") else p.status
        print(
            f"[{st:<6}] {(p.instrument.symbol or '')[:19]:<20} pt={p.product_type.value:<5} "
            f"qty={p.quantity:>10}  avg={f(p.avg_price):>11} "
            f"close={f(getattr(p,'close_price',None)):>11}  "
            f"open={ist(p.opened_at)} closed={ist(getattr(p,'closed_at',None))} "
            f"reason={getattr(p,'close_reason',None)}  margin={f(p.margin_used)}"
        )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "MCX"))
