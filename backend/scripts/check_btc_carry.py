import asyncio
from app.core.database import init_database
from app.models.position import Position


async def m():
    await init_database()
    rows = await Position.find_all().to_list()
    print("total rows:", len(rows))
    for p in rows:
        if (p.instrument.symbol or "") == "BTCUSD":
            print(
                p.status.value,
                "qty=", p.quantity,
                "pt=", p.product_type.value,
                "avg=", p.avg_price,
                "mgn=", p.margin_used,
                "realized=", getattr(p, "realized_pnl", None),
                "cr=", getattr(p, "close_reason", None),
                "upd=", getattr(p, "updated_at", None),
            )


asyncio.run(m())
