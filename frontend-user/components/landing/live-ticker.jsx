"use client";

import { TrendingUp, TrendingDown } from "lucide-react";
import { usePublicMarketFeed } from "@/lib/usePublicMarketFeed";

// Live quotes, not a sample array. This used to ship a hardcoded
// TICKER_DATA constant with a note saying to wire it up "once a public
// (unauthenticated) quotes endpoint exists" — that endpoint now exists at
// GET /api/v1/market/snapshot, and `usePublicMarketFeed` layers the
// public /ws/marketdata socket on top of it for realtime ticks.
//
// There is deliberately NO static fallback. Showing invented prices on a
// broker's marketing page is worse than showing nothing, so when the feed
// is unavailable the strip renders nothing at all and the hero simply
// meets the next section.

function formatPrice(price) {
  return price.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function LiveTicker() {
  const { rows, failed } = usePublicMarketFeed();

  const displayItems = rows.map((q) => ({
    label: q.label,
    price: q.ltp,
    changePercent: q.change_pct,
    isUp: q.change_pct >= 0,
  }));

  const row = (item, index) => {
    const up = item.isUp;
    // Up/down are DATA, not decoration — they keep a colour signal. Lime
    // for up (the page's one accent), a muted red for down. Deliberately
    // not the neon green/red pair: this strip sits under the nav all the
    // way down the page and must stay quiet.
    const priceColor = up ? "text-[#4D94E6]" : "text-[#E05C5C]";
    const sign = item.changePercent >= 0 ? "+" : "";
    return (
      <div
        key={`${item.label}-${index}`}
        className="flex items-center gap-2.5 px-5 py-2 whitespace-nowrap"
      >
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-white/45">
          {item.label}
        </span>
        <span className="text-[12px] font-medium tabular-nums text-white/90">
          {formatPrice(item.price)}
        </span>
        <span className={`flex items-center gap-0.5 text-[12px] font-medium tabular-nums ${priceColor}`}>
          {up ? <TrendingUp className="w-3 h-3 shrink-0" /> : <TrendingDown className="w-3 h-3 shrink-0" />}
          {sign}
          {item.changePercent.toFixed(2)}%
        </span>
      </div>
    );
  };

  // Nothing to say → say nothing. Also covers first paint, so the strip
  // never flashes an empty dark band before the snapshot lands.
  if (failed || displayItems.length === 0) return null;

  return (
    <div className="bg-[#0C0E0C] border-b border-white/[0.06] overflow-hidden">
      <div className="flex animate-ticker">
        {[...displayItems, ...displayItems].map((item, index) => row(item, index))}
      </div>
    </div>
  );
}
