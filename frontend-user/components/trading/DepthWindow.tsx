"use client";

/**
 * Market depth — the top 5 buyers and sellers for one instrument.
 *
 * Desktop: a depth icon in the order tray header opens `MarketDepthPopup`, a
 * floating window over the chart beside the tray. Mobile: a Depth button on
 * the trade sheet opens `MarketDepthSheet`, a panel that slides up from the
 * bottom. Both render `MarketDepthContent`. On the mobile Positions page a
 * tapped position opens `PositionDepthSheet` — depth only, no order form
 * (client requirement).
 *
 * Data is the quote the screen already polls (`/instruments/{token}/quote`,
 * every 2.5 s): `depth.bids` / `depth.asks` are Zerodha's 5-level book. The
 * book is the EXCHANGE's — the admin spread only moves our bid / ask, so the
 * BUY / SELL buttons can sit a little outside it; the panel says "Exchange
 * depth" for that reason.
 *
 * Clicking a price fills a LIMIT order at it: a buyer's price (bid) sets
 * SELL, a seller's price (ask) sets BUY.
 */

import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { InstrumentAPI } from "@/lib/api";
import { cn } from "@/lib/utils";

export type DepthPick = { price: number; side: "BUY" | "SELL" };

type Level = { price: number; qty: number; orders: number };

function levels(raw: unknown): Level[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((l: any) => ({
      price: Number(l?.price ?? 0),
      qty: Number(l?.qty ?? l?.quantity ?? 0),
      orders: Number(l?.orders ?? 0),
    }))
    .filter((l) => l.price > 0)
    .slice(0, 5);
}

const qty = (n: number) => (n > 0 ? Math.round(n).toLocaleString("en-IN") : "—");

/** Lakh / crore volume, the way Indian terminals print it. */
function bigNum(n: number | null | undefined): string {
  const v = Number(n ?? 0);
  if (!(v > 0)) return "—";
  if (v >= 1e7) return `${+(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `${+(v / 1e5).toFixed(2)}L`;
  return Math.round(v).toLocaleString("en-IN");
}

// Whether the trader left the desktop window open — kept per browser so it
// stays open across instruments and reloads. Storage can be blocked
// (private mode), so every access is guarded.
const OPEN_KEY = "nb.depthOpen";

export function readDepthOpen(): boolean {
  try {
    return window.localStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeDepthOpen(open: boolean): void {
  try {
    window.localStorage.setItem(OPEN_KEY, open ? "1" : "0");
  } catch {
    /* storage blocked — the window still works, it just won't be remembered */
  }
}

/** The depth glyph: two stacked ladders, one per side. */
export function DepthIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      aria-hidden="true"
      className={className}
    >
      <path d="M4 6h7M4 12h10M4 18h5" />
      <path d="M20 6h-4M20 12h-2M20 18h-6" />
    </svg>
  );
}

export function MarketDepthContent({
  quote,
  symbol,
  exchange,
  decimals = 2,
  onPick,
  pickHint = "Click a price to place a limit order there",
}: {
  quote: any;
  symbol?: string | null;
  exchange?: string | null;
  decimals?: number;
  onPick?: (p: DepthPick) => void;
  pickHint?: string;
}) {
  const px = (n: number | null | undefined) =>
    Number(n ?? 0) > 0
      ? Number(n).toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
      : "—";

  const bids = levels(quote?.depth?.bids);
  const asks = levels(quote?.depth?.asks);
  const rows = Math.max(bids.length, asks.length);
  const hasBook = rows > 0;

  const ltp = Number(quote?.ltp || quote?.last_ltp || 0);
  const change = Number(quote?.change ?? 0);
  const changePct = Number(quote?.change_pct ?? 0);
  const down = change < 0;

  // The exchange's own totals cover the WHOLE book; the 5 rows are a slice of
  // it. Fall back to the rows only when the feed sends no totals.
  const totalBuy = Number(quote?.total_buy_qty ?? 0) || bids.reduce((s, l) => s + l.qty, 0);
  const totalSell = Number(quote?.total_sell_qty ?? 0) || asks.reduce((s, l) => s + l.qty, 0);
  const buyPct = totalBuy + totalSell > 0 ? (totalBuy / (totalBuy + totalSell)) * 100 : 50;

  const pickable = !!onPick;
  const pick = (price: number, side: "BUY" | "SELL") => onPick?.({ price, side });
  const onKey = (e: React.KeyboardEvent, price: number, side: "BUY" | "SELL") => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pick(price, side);
    }
  };

  return (
    <div className="text-xs">
      {/* Symbol, price, change */}
      <div className="flex items-baseline justify-between gap-2 px-3 pt-2.5">
        <div className="min-w-0 truncate">
          <span className="text-sm font-semibold">{symbol ?? "—"}</span>
          {exchange ? <span className="ml-1.5 text-[10px] text-muted-foreground">{exchange}</span> : null}
        </div>
        <div className={cn("shrink-0 font-tabular font-semibold", down ? "text-sell" : "text-buy")}>
          {px(ltp)} {down ? "▼" : "▲"}{" "}
          <span className="text-[10px] font-normal text-muted-foreground">
            {change >= 0 ? "+" : ""}
            {change.toFixed(decimals)} ({changePct >= 0 ? "+" : ""}
            {changePct.toFixed(2)}%)
          </span>
        </div>
      </div>

      {/* O · H · L · C — the same one-line row as the order tray. C is the
          previous close, as on the tray. */}
      <div className="flex flex-wrap gap-x-3.5 gap-y-0.5 border-b border-border px-3 pb-2 pt-1 text-[11px] text-muted-foreground">
        <span>
          O <span className="font-tabular font-semibold text-foreground">{px(quote?.open)}</span>
        </span>
        <span>
          H <span className="font-tabular font-semibold text-buy">{px(quote?.high)}</span>
        </span>
        <span>
          L <span className="font-tabular font-semibold text-sell">{px(quote?.low)}</span>
        </span>
        <span>
          C <span className="font-tabular font-semibold text-foreground">{px(quote?.prev_close)}</span>
        </span>
      </div>

      <div className="flex items-center justify-between px-3 pb-1 pt-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5 font-semibold text-foreground">
          <span className={cn("size-1.5 rounded-full", hasBook && !quote?.stale ? "bg-buy" : "bg-muted-foreground")} />
          Exchange depth
        </span>
        <span>top 5</span>
      </div>

      {hasBook ? (
        <>
          <table className="w-full border-collapse font-tabular text-[11.5px] tabular-nums">
            <thead>
              <tr className="text-[10px] text-muted-foreground">
                <th className="bg-buy/10 px-1.5 py-1.5 text-right font-semibold">Qty.</th>
                <th className="bg-buy/10 px-1.5 py-1.5 text-right font-semibold">Orders</th>
                <th className="bg-buy/10 px-1.5 py-1.5 text-right font-semibold">Buy price</th>
                <th className="bg-sell/10 px-1.5 py-1.5 text-left font-semibold">Sell price</th>
                <th className="bg-sell/10 px-1.5 py-1.5 text-right font-semibold">Orders</th>
                <th className="bg-sell/10 px-1.5 py-1.5 text-right font-semibold">Qty.</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: rows }).map((_, i) => {
                const b = bids[i];
                const a = asks[i];
                return (
                  <tr key={i} className="border-t border-border">
                    <td className="px-1.5 py-1 text-right">{b ? qty(b.qty) : ""}</td>
                    <td className="px-1.5 py-1 text-right text-muted-foreground">{b ? b.orders || "—" : ""}</td>
                    <td
                      className={cn(
                        "px-1.5 py-1 text-right font-semibold text-buy",
                        b && pickable && "cursor-pointer hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
                      )}
                      tabIndex={b && pickable ? 0 : undefined}
                      role={b && pickable ? "button" : undefined}
                      aria-label={b && pickable ? `Sell limit at ${px(b.price)}` : undefined}
                      onClick={b && pickable ? () => pick(b.price, "SELL") : undefined}
                      onKeyDown={b && pickable ? (e) => onKey(e, b.price, "SELL") : undefined}
                    >
                      {b ? px(b.price) : ""}
                    </td>
                    <td
                      className={cn(
                        "border-l border-border px-1.5 py-1 text-left font-semibold text-sell",
                        a && pickable && "cursor-pointer hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
                      )}
                      tabIndex={a && pickable ? 0 : undefined}
                      role={a && pickable ? "button" : undefined}
                      aria-label={a && pickable ? `Buy limit at ${px(a.price)}` : undefined}
                      onClick={a && pickable ? () => pick(a.price, "BUY") : undefined}
                      onKeyDown={a && pickable ? (e) => onKey(e, a.price, "BUY") : undefined}
                    >
                      {a ? px(a.price) : ""}
                    </td>
                    <td className="px-1.5 py-1 text-right text-muted-foreground">{a ? a.orders || "—" : ""}</td>
                    <td className="px-1.5 py-1 text-right">{a ? qty(a.qty) : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="mx-3 mt-2.5 flex h-1.5 overflow-hidden rounded-full bg-muted">
            <span className="block bg-buy transition-[width] duration-500" style={{ width: `${buyPct}%` }} />
            <span className="block flex-1 bg-sell" />
          </div>
          <div className="flex justify-between px-3 pb-2 pt-1 font-tabular text-[11px]">
            <span className="text-buy">{qty(totalBuy)}</span>
            <span className="font-sans text-muted-foreground">Total quantity</span>
            <span className="text-sell">{qty(totalSell)}</span>
          </div>
        </>
      ) : (
        <p className="px-3 py-6 text-center text-muted-foreground">
          Depth not available for this instrument right now.
        </p>
      )}

      <div className="grid grid-cols-4 gap-1 border-t border-border px-3 py-2 text-[10px] text-muted-foreground">
        <div>
          Avg price
          <div className="font-tabular text-xs font-semibold text-foreground">{px(quote?.avg_price)}</div>
        </div>
        <div>
          Prev close
          <div className="font-tabular text-xs font-semibold text-foreground">{px(quote?.prev_close)}</div>
        </div>
        <div>
          Volume
          <div className="font-tabular text-xs font-semibold text-foreground">{bigNum(quote?.volume)}</div>
        </div>
        <div>
          OI
          <div className="font-tabular text-xs font-semibold text-foreground">{bigNum(quote?.oi)}</div>
        </div>
      </div>
      {hasBook && pickable && <p className="px-3 pb-2.5 text-[10px] text-muted-foreground">{pickHint}</p>}
    </div>
  );
}

const POPUP_WIDTH = 380;

/** Desktop: a floating window to the LEFT of the order tray (over the chart),
 *  so the order form stays visible while it is open. Falls back to covering
 *  the tray when there is no room on the left. Closes on ✕, Esc, or a click
 *  outside it (the toggle button is excluded, so it can close it itself). */
export function MarketDepthPopup({
  open,
  onClose,
  anchorRef,
  toggleRef,
  ...content
}: {
  open: boolean;
  onClose: () => void;
  /** The order tray; the window is placed beside it. */
  anchorRef: RefObject<HTMLElement | null>;
  /** The depth icon — clicks on it are left to its own handler. */
  toggleRef?: RefObject<HTMLElement | null>;
} & Parameters<typeof MarketDepthContent>[0]) {
  const [box, setBox] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);
  const [el, setEl] = useState<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = anchorRef.current?.getBoundingClientRect();
      if (!r) return;
      const roomLeft = r.left >= POPUP_WIDTH + 16;
      const top = roomLeft ? r.top + 8 : r.top + 44;
      setBox({
        top,
        left: roomLeft ? r.left - POPUP_WIDTH - 8 : r.left + 8,
        width: roomLeft ? POPUP_WIDTH : Math.max(260, r.width - 16),
        maxHeight: window.innerHeight - top - 12,
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (el?.contains(t) || toggleRef?.current?.contains(t)) return;
      // Clicks inside the order tray keep it open: the trader is ordering
      // with the book in view, which is the point of the window.
      if (anchorRef.current?.contains(t)) return;
      onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, onClose, el, toggleRef, anchorRef]);

  if (!open || !box || typeof document === "undefined") return null;
  return createPortal(
    <div
      ref={setEl}
      role="dialog"
      aria-modal="false"
      aria-label="Market depth"
      className="fixed z-50 overflow-y-auto rounded-xl border border-border bg-card text-foreground shadow-2xl"
      style={{ top: box.top, left: box.left, width: box.width, maxHeight: box.maxHeight }}
    >
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-[13px] font-semibold">Market depth</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close market depth"
          className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-muted/40 hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>
      <MarketDepthContent {...content} />
    </div>,
    document.body,
  );
}

/** Mobile: a panel that slides up from the bottom of the trade sheet. It
 *  covers the order form, so the host closes it after a price is picked.
 *
 *  It is positioned inside the sheet's dialog, so the host must keep that
 *  dialog scrolled to the top (and not scrollable) while it is open, and
 *  route Esc to `onClose` through the dialog's `onEscapeKeyDown` — otherwise
 *  Esc would close the whole trade sheet. */
export function MarketDepthSheet({
  open,
  onClose,
  ...content
}: { open: boolean; onClose: () => void } & Parameters<typeof MarketDepthContent>[0]) {
  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "absolute inset-0 z-30 bg-black/55 transition-opacity duration-200 motion-reduce:transition-none",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Market depth"
        aria-hidden={!open}
        className={cn(
          "absolute inset-x-0 bottom-0 z-40 max-h-[82%] overflow-y-auto rounded-t-2xl border-t border-border bg-card shadow-2xl transition-transform duration-200 motion-reduce:transition-none",
          open ? "translate-y-0" : "pointer-events-none translate-y-full",
        )}
      >
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-muted" aria-hidden="true" />
        <div className="flex items-center justify-between px-3 pb-1 pt-1.5">
          <span className="text-sm font-semibold">Market depth</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close market depth"
            className="grid size-7 place-items-center rounded-full bg-muted/50 text-muted-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
        {open && <MarketDepthContent {...content} />}
      </div>
    </>
  );
}

/** Mobile Positions page: market depth on its own, with no order form.
 *
 *  Client requirement (20 Nov 2026): tapping a position card on the phone's
 *  Positions page should open ONLY the depth panel, not the BUY / SELL trade
 *  sheet, and it must be closable. So this is a standalone bottom panel: it
 *  fetches its own instrument + quote (same query keys as the trade sheet, so
 *  the cache is shared) and shows the book read-only — there is no order form
 *  here for a tapped price to fill. Close via ✕, a tap on the dark area, or
 *  Esc. */
export function PositionDepthSheet({
  token,
  onClose,
}: {
  token: string | null;
  onClose: () => void;
}) {
  const open = !!token;
  const { data: instrument } = useQuery({
    queryKey: ["instrument", token],
    queryFn: () => InstrumentAPI.detail(token!),
    enabled: open,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  const { data: quote } = useQuery({
    queryKey: ["quote", token],
    queryFn: () => InstrumentAPI.quote(token!),
    enabled: open,
    refetchInterval: 1500,
    staleTime: 1000,
  });

  // Same price precision as the trade sheet: forex quotes to 4 places.
  const seg = String(instrument?.segment ?? "").toUpperCase();
  const exch = String(instrument?.exchange ?? "").toUpperCase();
  const decimals = seg.includes("FOREX") || seg.includes("FX") || exch === "CDS" ? 4 : 2;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/55 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed inset-x-0 bottom-0 z-50 max-h-[82vh] overflow-y-auto overscroll-contain rounded-t-2xl border-t border-border bg-card pb-[env(safe-area-inset-bottom)] shadow-2xl data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom"
        >
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-muted" aria-hidden="true" />
          <div className="flex items-center justify-between px-3 pb-1 pt-1.5">
            <DialogPrimitive.Title className="text-sm font-semibold">Market depth</DialogPrimitive.Title>
            <DialogPrimitive.Close
              aria-label="Close market depth"
              className="grid size-7 place-items-center rounded-full bg-muted/50 text-muted-foreground"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <MarketDepthContent
            quote={quote}
            symbol={instrument?.symbol}
            exchange={instrument?.exchange}
            decimals={decimals}
          />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
