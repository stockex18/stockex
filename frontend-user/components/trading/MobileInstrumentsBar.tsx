"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, Star, X } from "lucide-react";
import { PiArrowsDownUpBold, PiStarFill } from "react-icons/pi";
import { InstrumentAPI, MarketwatchAPI, SegmentSettingsAPI } from "@/lib/api";
import { useMarketStream } from "@/lib/useMarketStream";
import { usePriceFlash } from "@/lib/usePriceFlash";
import { cn, formatPrice } from "@/lib/utils";
import { MobileOptionChain } from "@/components/trading/MobileOptionChain";
import { SymbolAvatar } from "@/components/common/SymbolAvatar";

type SortKey = "symbol" | "ltp" | "change";

interface Props {
  activeToken: string | null;
  /** `seed` carries the row's last-known ltp/bid/ask + identity so the trade
   *  card paints a price AND a usable instrument instantly, instead of
   *  waiting ~5-7 s for its own fresh WS connection + REST fetches on first
   *  open (which left it at "0.00" / "Instrument not loaded"). */
  onSelect: (
    token: string,
    seed?: {
      ltp?: number | null;
      bid?: number | null;
      ask?: number | null;
      symbol?: string | null;
      exchange?: string | null;
      segment?: string | null;
    },
  ) => void;
  /** When set (Market page passes the user's PRIMARY wallet kind), the chip
   *  strip is filtered to only that wallet's segments and defaults to its
   *  first market. Unset (terminal) → all chips, unchanged behaviour. */
  walletKind?: string | null;
}

// Wallet kind → which chip buckets that trading wallet may browse. Favorites
// First market chip to land on per wallet (chips are ALL visible now, so we
// can't just pick "the first non-favorites chip" — that would land on some
// other segment). Mirrors WALLET_DEFAULT_BUCKET in InstrumentsPanel.
const WALLET_DEFAULT_BUCKET: Record<string, string> = {
  NSE_BSE: "nse_eq",
  MCX: "mcx_fut",
  CRYPTO: "crypto",
  FOREX: "forex",
};

type Bucket = {
  key: string;
  label: string;
  // "all" is the Zerodha catalogue: the search box reaches every Indian
  // segment at once instead of only the one under the selected chip.
  mode: "watchlist" | "filter" | "all";
  segments?: string[];
  adminRows?: string[];
  // Indian-segment chips are user-managed: list shows only what the
  // user has explicitly added (via search + "+"). Mirrors the desktop
  // InstrumentsPanel behaviour. Infoway-fed chips (Forex/Crypto/etc.)
  // stay non-managed — the entire small feed is shown.
  managed?: boolean;
};

// Bucket order: Favorites first, then every Indian-exchange-backed
// segment (NSE EQ / FUT / OPT, MCX FUT), then the international /
// Infoway-backed ones (Indices, Stocks, Commodities, Forex, Crypto) so
// a user reaching for "NIFTY FUT" doesn't have to scroll past five
// foreign-market chips first. Matches the user's request: Indian
// markets pehle, crypto/forex last.
const BUCKETS: Bucket[] = [
  { key: "favorites", label: "Favorites", mode: "watchlist" },
  // Everything, in one place. Without it there was no way to search across
  // segments on a phone at all: `searchScopeSegments` follows the selected
  // chip, Favorites searches only the starred rows, and every other chip is
  // a single segment — so finding an instrument meant already knowing which
  // segment it lived in. Operator: "fav ke side me All karke ek section de,
  // yahan se user ek baar me search kar paye." Mirrors the desktop
  // InstrumentsPanel, which has had this chip all along.
  { key: "all", label: "All", mode: "all" },
  // Indian segments — managed (user explicitly adds instruments)
  { key: "nse_eq", label: "NSE EQ", mode: "filter", segments: ["NSE_EQUITY"], adminRows: ["NSE_EQ"], managed: true },
  { key: "nse_fut", label: "NSE FUT", mode: "filter", segments: ["NSE_FUTURE", "NSE_INDEX_FUTURE"], adminRows: ["NSE_FUT"], managed: true },
  { key: "nse_opt", label: "NSE OPT", mode: "filter", segments: ["NSE_INDEX_OPTION_BUY", "NSE_INDEX_OPTION_SELL", "NSE_STOCK_OPTION_BUY", "NSE_STOCK_OPTION_SELL"], adminRows: ["NSE_OPT"], managed: true },
  { key: "bse_eq", label: "BSE EQ", mode: "filter", segments: ["BSE_EQUITY"], adminRows: ["BSE_EQ"], managed: true },
  { key: "bse_fut", label: "BSE FUT", mode: "filter", segments: ["BSE_FUTURE", "BSE_INDEX_FUTURE"], adminRows: ["BSE_FUT"], managed: true },
  { key: "bse_opt", label: "BSE OPT", mode: "filter", segments: ["BSE_OPTION_BUY", "BSE_OPTION_SELL"], adminRows: ["BSE_OPT"], managed: true },
  { key: "mcx_fut", label: "MCX FUT", mode: "filter", segments: ["MCX_FUTURE"], adminRows: ["MCX_FUT"], managed: true },
  // MCX OPT — was missing from this list (admin enables MCX_OPT but the
  // mobile chip strip never surfaced it, so users on phones couldn't
  // see commodity options at all). Same admin row + segment-set as the
  // desktop InstrumentsPanel.
  { key: "mcx_opt", label: "MCX OPT", mode: "filter", segments: ["MCX_OPTION_BUY", "MCX_OPTION_SELL"], adminRows: ["MCX_OPT"], managed: true },
  // Infoway-fed chips — non-managed (entire small feed visible)
  { key: "indices", label: "Indices", mode: "filter", segments: ["INDICES"], adminRows: ["INDICES"] },
  { key: "stocks", label: "Stocks", mode: "filter", segments: ["STOCKS"], adminRows: ["STOCKS"] },
  { key: "commodities", label: "Commodities", mode: "filter", segments: ["COMMODITIES"], adminRows: ["COMMODITIES"] },
  { key: "forex", label: "Forex", mode: "filter", segments: ["FOREX"], adminRows: ["FOREX"] },
  { key: "crypto", label: "Crypto", mode: "filter", segments: ["CRYPTO_PERPETUAL", "CRYPTO_SPOT", "CRYPTO_FUTURE"], adminRows: ["CRYPTO"] },
  { key: "crypto_opt", label: "Crypto OPT", mode: "filter", segments: ["CRYPTO_OPTION_BUY", "CRYPTO_OPTION_SELL"], adminRows: ["CRYPTO_OPT"] },
];

/**
 * Mobile-only instruments bar that sits at the top of the terminal page.
 * Mirrors the InstrumentsPanel's search + bucket model but in a flatter
 * horizontal layout — chips strip + search row + scrollable picks. Tapping
 * a row fires `onSelect(token)` which the terminal page maps onto the
 * existing `selectedToken` state — no navigation, the chart and order panel
 * below just swap.
 */
export function MobileInstrumentsBar({ activeToken, onSelect, walletKind }: Props) {
  const qc = useQueryClient();
  // Always expanded — the collapse chevron was removed (operator: "iski
  // zarurat nahi"). Kept as a const so the existing `expanded &&` query
  // gates below stay valid without a wider refactor.
  const [expanded] = useState(true);
  // Top-level view toggle: the existing watchlist (default, unchanged) and
  // the new Groww-style Options chain. The watchlist logic/queries below are
  // untouched — the Options branch is purely additive.
  const [view, setView] = useState<"watchlist" | "options">("watchlist");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [bucketKey, setBucketKey] = useState<string>("favorites");
  // Column sort: tap a header for ascending, again for descending, a third
  // time for the list's own order.
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);
  const cycleSort = (key: SortKey) =>
    setSort((cur) => (cur?.key !== key ? { key, dir: 1 } : cur.dir === 1 ? { key, dir: -1 } : null));
  // Optimistic favorite toggle — tracks tokens the user just starred /
  // unstarred so the star icon flips before the network round-trip lands.
  // Reset whenever the source watchlist refetches.
  const [pendingFav, setPendingFav] = useState<Map<string, boolean>>(new Map());

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 180);
    return () => clearTimeout(t);
  }, [search]);

  const { data: inactiveRows } = useQuery({
    queryKey: ["segment-settings", "inactive"],
    queryFn: () => SegmentSettingsAPI.inactive(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  });
  const inactiveSet = useMemo(() => new Set(inactiveRows ?? []), [inactiveRows]);
  const visibleBuckets = useMemo(() => {
    return BUCKETS.filter((b) => {
      // ALL segments browseable from ANY wallet — every instrument shows at
      // once regardless of the open wallet. The wallet only decides which one
      // the ORDER debits, never what's visible. We still LAND on the wallet's
      // own market chip first (effect below) but every chip stays visible.
      const rows = b.adminRows ?? [];
      if (rows.length === 0) return true;
      return rows.some((r) => !inactiveSet.has(r));
    });
  }, [inactiveSet]);
  useEffect(() => {
    if (!visibleBuckets.find((b) => b.key === bucketKey)) setBucketKey("favorites");
  }, [visibleBuckets, bucketKey]);
  // When a primary wallet is enforced, land on its first MARKET chip (not
  // favorites) so the user sees that wallet's instruments right away.
  useEffect(() => {
    if (!walletKind) return;
    const target = WALLET_DEFAULT_BUCKET[walletKind];
    if (target && visibleBuckets.find((b) => b.key === target)) setBucketKey(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walletKind]);

  // Smooth-scroll the active chip into view when the bucket changes.
  // `block: nearest` keeps vertical position; `inline: center` slides the
  // chip into the middle of the strip so the user always sees adjacent
  // buckets on both sides — far better than the previous `snap-start`
  // jump that left the active chip pinned to the left edge.
  const chipsScrollerRef = useRef<HTMLDivElement | null>(null);
  const chipRefs = useRef<Record<string, HTMLButtonElement>>({});
  useEffect(() => {
    const el = chipRefs.current[bucketKey];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [bucketKey]);

  const bucket = visibleBuckets.find((b) => b.key === bucketKey) ?? visibleBuckets[0];

  const { data: watchlists } = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => MarketwatchAPI.list(),
    staleTime: 30_000,
  });
  const activeWl = watchlists?.[0];

  // Token → item-id map for the active watchlist so a tap on the star can
  // resolve the item id needed for `removeItem` without a second round-trip.
  const favItemByToken = useMemo(() => {
    const map = new Map<string, string>();
    for (const it of activeWl?.items ?? []) {
      if (it?.instrument_token && it?.id) map.set(String(it.instrument_token), String(it.id));
    }
    return map;
  }, [activeWl]);

  // Clear the optimistic-flip overlay once the server-side list catches up
  // — otherwise repeated stars on the same token would stay "pending" forever.
  useEffect(() => {
    if (pendingFav.size === 0) return;
    setPendingFav((prev) => {
      const next = new Map(prev);
      for (const [tok, wantStarred] of prev) {
        const isStarred = favItemByToken.has(tok);
        if (isStarred === wantStarred) next.delete(tok);
      }
      return next;
    });
  }, [favItemByToken, pendingFav]);

  function isFav(token: string): boolean {
    const tok = String(token);
    if (pendingFav.has(tok)) return pendingFav.get(tok)!;
    return favItemByToken.has(tok);
  }

  async function toggleFavorite(token: string) {
    const tok = String(token);
    if (!activeWl?.id) {
      toast.error("No watchlist available");
      return;
    }
    const currentlyFav = isFav(tok);
    // Flip the star instantly — server reconciliation happens in the
    // invalidate below.
    setPendingFav((prev) => new Map(prev).set(tok, !currentlyFav));
    try {
      if (currentlyFav) {
        const itemId = favItemByToken.get(tok);
        if (!itemId) throw new Error("Item not found in watchlist");
        await MarketwatchAPI.removeItem(activeWl.id, itemId);
      } else {
        await MarketwatchAPI.addItem(activeWl.id, tok);
      }
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      qc.invalidateQueries({ queryKey: ["watchlist-quotes"] });
    } catch (e: any) {
      // Roll back the optimistic flip on failure.
      setPendingFav((prev) => {
        const next = new Map(prev);
        next.delete(tok);
        return next;
      });
      toast.error(e?.message || (currentlyFav ? "Failed to remove" : "Failed to add"));
    }
  }
  const { data: wlQuotes } = useQuery({
    queryKey: ["watchlist-quotes", activeWl?.id],
    queryFn: () => MarketwatchAPI.quotes(activeWl!.id),
    // Stays enabled WHILE searching favorites too — the Favorites search is a
    // local filter over these rows (see `list` below), so we keep the live
    // quotes flowing instead of pausing them the moment the user types.
    enabled: !!activeWl?.id && bucketKey === "favorites" && expanded,
    refetchInterval: 3000,
    staleTime: 2000,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev,
  });

  // "All" is the Zerodha catalogue — every segment the managed chips cover
  // (NSE / BSE / MCX equity, futures, options) and nothing else. Crypto, forex,
  // indices, stocks and commodities are Infoway / Binance feeds with their own
  // chips and nothing to add, so they stay out of it. Operator: "Zerodha ke
  // liye bas banao All ko."
  //
  // Derived from the managed buckets rather than typed out, so a segment added
  // to a managed chip is in All without a second edit.
  const allSegments = useMemo(
    () =>
      BUCKETS.filter((b) => b.managed)
        .flatMap((b) => b.segments ?? [])
        .join(","),
    [],
  );
  const browseSegments =
    bucket?.mode === "filter"
      ? bucket.segments?.join(",")
      : bucket?.mode === "all"
        ? allSegments
        : undefined;
  const searchScopeSegments =
    bucket?.mode === "filter" || bucket?.mode === "all" ? browseSegments : undefined;

  // Managed-segment marker — Indian chips show only what the user
  // explicitly added. The admin row name (e.g. "NSE_EQ") is the
  // backend's segment key. Same flow as the desktop InstrumentsPanel.
  const managedSegmentName =
    bucket?.managed && bucket?.adminRows?.[0] ? bucket.adminRows[0] : null;

  const { data: segmentItems } = useQuery<any[]>({
    queryKey: ["segment-items", managedSegmentName],
    queryFn: () => MarketwatchAPI.segmentItems(managedSegmentName!),
    enabled: !!managedSegmentName && expanded,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
  const addedTokenSet = useMemo(() => {
    const s = new Set<string>();
    for (const it of segmentItems ?? []) {
      if (it?.instrument_token) s.add(String(it.instrument_token));
    }
    return s;
  }, [segmentItems]);

  // `row` is the segment to add to. On a managed chip that is the chip itself;
  // in "All" there is no chip, so the row carries its own (`managed_row`).
  async function addToSegment(token: string, symbol: string, row?: string | null) {
    const seg = row ?? managedSegmentName;
    if (!seg) return;
    try {
      await MarketwatchAPI.addSegmentItem(seg, token);
      qc.invalidateQueries({ queryKey: ["segment-items", seg] });
      toast.success(`Added ${symbol} to ${seg.replace("_", " ")}`, { duration: 1500 });
    } catch (e: any) {
      toast.error(e?.message || `Failed to add ${symbol}`);
    }
  }

  async function removeFromSegment(token: string, symbol: string) {
    if (!managedSegmentName) return;
    try {
      await MarketwatchAPI.removeSegmentItem(managedSegmentName, token);
      qc.invalidateQueries({ queryKey: ["segment-items", managedSegmentName] });
      toast.success(`Removed ${symbol}`, { duration: 1500 });
    } catch (e: any) {
      toast.error(e?.message || `Failed to remove ${symbol}`);
    }
  }

  const { data: searchHits } = useQuery({
    queryKey: ["mobile-instruments-search", debouncedSearch, searchScopeSegments],
    queryFn: () =>
      InstrumentAPI.search(debouncedSearch, undefined, searchScopeSegments, 30),
    // Favorites NEVER hits the global instrument search — searching the
    // Favorites tab filters the starred rows locally (user: "fav me sirf fav
    // vale search honge, all search nahi"). Only the segment/browse buckets
    // run this query, and managed Indian segments stay scoped to their own
    // segment via `searchScopeSegments`.
    enabled:
      debouncedSearch.trim().length > 0 &&
      expanded &&
      bucket?.mode !== "watchlist",
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev,
  });
  // Browse the bucket — cap at 40 (was 60). A bigger result set bloats the
  // WS subscribe list and the per-row quote map without the user actually
  // seeing past the first ~10 rows on screen.
  // Skipped for managed segments — those render `segmentItems` (user's
  // explicit additions) instead of the full Kite cache.
  const { data: bucketHits } = useQuery({
    queryKey: ["mobile-instruments-bucket", bucketKey, browseSegments],
    queryFn: () => InstrumentAPI.search(undefined, undefined, browseSegments, 40),
    enabled:
      search.trim().length === 0 &&
      bucket?.mode !== "watchlist" &&
      !!browseSegments &&
      expanded &&
      !managedSegmentName,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev,
  });

  // The All view has no single chip to read "what is already added" from, so
  // ask for each segment that actually appears in the results — not all eight.
  // Shares its cache key with the managed chips, so adding from either side
  // updates the other.
  const allViewRows = useMemo(() => {
    if (bucket?.mode !== "all") return [] as string[];
    const seen = new Set<string>();
    for (const h of [...(searchHits ?? []), ...(bucketHits ?? [])]) {
      if (h?.managed_row) seen.add(String(h.managed_row));
    }
    return [...seen].sort();
  }, [bucket?.mode, searchHits, bucketHits]);
  const allViewItems = useQueries({
    queries: allViewRows.map((r) => ({
      queryKey: ["segment-items", r],
      queryFn: () => MarketwatchAPI.segmentItems(r),
      enabled: expanded,
      staleTime: 30_000,
    })),
  });
  const addedInAllView = new Set<string>();
  for (const res of allViewItems) {
    for (const it of (res.data as any[] | undefined) ?? []) {
      if (it?.instrument_token) addedInAllView.add(String(it.instrument_token));
    }
  }


  // `tokensKey` (a stable string) is the dep — using the array itself
  // would invalidate the memo on every render even when the contents
  // matched, which in turn churned the WS subscribe / unsubscribe in
  // useMarketStream below.
  // Cap subscribed tokens to LIVE_TOKEN_CAP (top N of the filtered
  // list). Mirrors the same cap on the desktop InstrumentsPanel —
  // prevents the backend pump from refreshing 100+ overlays per cycle
  // when the user only sees 8-10 rows on a phone viewport. The
  // remaining rows render with the initial REST snapshot bid/ask which
  // is good enough until the user scrolls.
  const LIVE_TOKEN_CAP = 30;
  const tokensKey = useMemo<string>(() => {
    const all = (() => {
      // Searching and browsing subscribe NOTHING. A search result is a row in
      // a catalogue, not an instrument the user is watching — and every one of
      // them used to be quoted AND put on the websocket. Typing "cru" put
      // forty CRUDEOIL strikes on the live feed; in production 1,237 of the
      // 1,500 subscription slots were leftovers of exactly that, squeezing out
      // the futures that carry almost all the real trading. Price starts when
      // the user ADDS the instrument, which is also when it starts being
      // stored — see `addToSegment` / the watchlist star below.
      if (debouncedSearch.trim().length > 0 && bucket?.mode !== "watchlist") {
        return [];
      }
      if (bucket?.mode === "watchlist") {
        // Subscribe the FAVOURITE tokens to WS + batch quotes too. Without
        // this the Favorites tab got no live overlay — `quoteByToken` was
        // empty, so the enrich() below fell back to the /marketwatch/quotes
        // REST ltp, which is 0 for Infoway (crypto/forex/metals). Result:
        // those rows froze at 0.00 while every other bucket ticked live.
        // instrument_token == symbol for Infoway, so they stream fine.
        return (activeWl?.items ?? []).map((it: any) =>
          String(it.instrument_token ?? it.token),
        );
      }
      if (managedSegmentName) {
        // These ARE the added ones — the managed chip only ever lists what the
        // user explicitly put there. Prices belong here.
        return (segmentItems ?? []).map((it: any) => String(it.instrument_token));
      }
      // An unmanaged FILTER chip — Indices, Stocks, Commodities, Forex,
      // Crypto — is not a catalogue. It is the whole of a small feed, and
      // there is no "add" on these chips, so a bucket that does not
      // subscribe leaves every row on "—" forever. Mirrors the same change
      // on the desktop InstrumentsPanel; the cap below and the
      // search-subscribes-nothing rule above are both untouched.
      if (bucket?.mode === "filter") {
        return (bucketHits ?? []).map((it: any) => String(it.token));
      }
      return [];
    })();
    return all.slice(0, LIVE_TOKEN_CAP).join(",");
  }, [debouncedSearch, searchHits, bucketHits, bucket?.mode, managedSegmentName, segmentItems, activeWl?.items]);
  const visibleTokens = useMemo<string[]>(
    () => (tokensKey ? tokensKey.split(",") : []),
    [tokensKey],
  );

  const { data: liveQuotes } = useQuery<any[]>({
    queryKey: ["mobile-instruments-batch-seed", tokensKey],
    queryFn: () => InstrumentAPI.quotesBatch(visibleTokens),
    enabled: visibleTokens.length > 0 && expanded,
    staleTime: 60_000,
    refetchInterval: false,
    refetchOnWindowFocus: false,
  });
  // Skip WS subscription entirely when the bar is collapsed OR when the
  // Options tab is showing (that view runs its own per-strike stream) — the
  // user can't see the watchlist rows, no point burning sockets / handlers.
  const streamQuotes = useMarketStream(
    expanded && view === "watchlist" ? visibleTokens : [],
  );
  const quoteByToken = useMemo(() => {
    const map = new Map<string, any>();
    for (const q of liveQuotes ?? []) map.set(String(q.token), q);
    streamQuotes.forEach((q, tok) => map.set(tok, q));
    return map;
  }, [liveQuotes, streamQuotes]);

  const unsortedList = useMemo(() => {
    // A search result is a catalogue row. It carries NO price, even for an
    // instrument the user has already added — the live quote map can still be
    // holding that token from the watchlist view they were just on, and one
    // priced row among a list of unpriced ones reads as if the others were
    // broken. Price belongs on the watchlist, which is where an added
    // instrument lives.
    const searching = debouncedSearch.trim().length > 0 && bucket?.mode !== "watchlist";
    const enrich = (s: any) => {
      const live = searching ? undefined : quoteByToken.get(String(s.token));
      return {
        instrument_token: s.token,
        symbol: s.symbol,
        name: s.name ?? null,
        exchange: s.exchange,
        segment: s.segment ?? s.instrument_type,
        // What the row shows INSTEAD of a price when nothing is subscribed —
        // enough to tell two strikes of the same underlying apart.
        expiry: s.expiry ?? null,
        strike: s.strike ?? null,
        lot_size: s.lot_size ?? null,
        // Which user-managed chip this instrument is added to, if any. The All
        // view needs it: it has no chip selected to say where "Add" goes.
        managed_row: s.managed_row ?? null,
        bid: live?.bid ?? null,
        ask: live?.ask ?? null,
        ltp: live?.ltp ?? null,
        change_pct: live?.change_pct ?? null,
      };
    };
    // ── Favorites (watchlist) ──────────────────────────────────────────
    // ALWAYS renders the user's starred rows. A search term filters them
    // LOCALLY by symbol — it must NEVER fall through to the global
    // all-instruments search (user complaint: typing in Favorites was
    // searching every instrument instead of just the favorites). Live ticks
    // are overlaid onto the REST snapshot so prices stay fresh.
    if (bucket?.mode === "watchlist") {
      const rows = (wlQuotes ?? []).map((q: any) => {
        const tok = String(q.instrument_token ?? q.token ?? "");
        const live = quoteByToken.get(tok);
        return {
          ...q,
          bid: live?.bid ?? q.bid ?? null,
          ask: live?.ask ?? q.ask ?? null,
          ltp: live?.ltp ?? q.ltp ?? null,
          change_pct: live?.change_pct ?? q.change_pct ?? null,
        };
      });
      const needle = debouncedSearch.trim().toLowerCase();
      if (!needle) return rows;
      return rows.filter((r: any) =>
        String(r.symbol ?? "").toLowerCase().includes(needle),
      );
    }
    // ── Segment / browse buckets ────────────────────────────────────────
    // A search term shows segment-scoped search hits (managed Indian
    // segments stay scoped via `searchScopeSegments`); empty search browses.
    if (debouncedSearch.trim().length > 0) return (searchHits ?? []).map(enrich);
    if (managedSegmentName) {
      return (segmentItems ?? []).map((it: any) =>
        enrich({
          token: it.instrument_token,
          symbol: it.symbol,
          exchange: it.exchange,
          segment: null,
          instrument_type: null,
        }),
      );
    }
    return (bucketHits ?? []).map(enrich);
  }, [debouncedSearch, searchHits, wlQuotes, bucketHits, bucket, quoteByToken, managedSegmentName, segmentItems]);

  const list = useMemo(() => {
    if (!sort) return unsortedList;
    const val = (r: any): number | string =>
      sort.key === "symbol"
        ? String(r.symbol ?? "")
        : Number(sort.key === "ltp" ? r.ltp ?? r.bid ?? r.ask : r.change_pct);
    return [...unsortedList].sort((a: any, b: any) => {
      const x = val(a);
      const y = val(b);
      // Rows with no price yet always sink to the bottom, whichever way.
      if (typeof x === "number" && !Number.isFinite(x)) return 1;
      if (typeof y === "number" && !Number.isFinite(y)) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [unsortedList, sort]);
  const searchingNow = debouncedSearch.trim().length > 0 && bucket?.mode !== "watchlist";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background md:rounded-lg md:border md:border-border md:bg-card">
      {/* Header — mirrors the desktop InstrumentsPanel ("INSTRUMENTS"
          uppercase label + close on the right). The collapse chevron is
          kept so the user can shrink the strip on phones that have less
          vertical room. */}
      <div className="flex shrink-0 items-center gap-4 border-b border-border px-3 py-2">
        {(["watchlist", "options"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className="relative py-0.5"
          >
            <span
              className={cn(
                "text-sm font-bold transition-colors",
                view === v ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {v === "watchlist" ? "Watchlist" : "Options"}
            </span>
            {view === v && (
              <span className="absolute -bottom-[9px] left-0 right-0 h-0.5 rounded-full bg-foreground" />
            )}
          </button>
        ))}
      </div>

      {expanded && view === "options" && <MobileOptionChain onSelect={onSelect} />}

      {expanded && view === "watchlist" && (
        <>
          <div className="shrink-0 space-y-2 border-b border-border px-3 py-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search NIFTY, RELIANCE, TCS..."
                className="h-10 w-full rounded-xl border border-border bg-card pl-9 pr-8 text-[13px] font-semibold outline-none placeholder:font-medium placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                  className="absolute right-1 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>

            {/* Segment chips — horizontally scrollable strip. Hides the
                scrollbar entirely (touch-friendly), uses snap-x so a swipe
                lands the next chip cleanly aligned at the leading edge,
                and a fade-mask on the right indicates more chips are
                available off-screen. Larger touch target (h-7, px-3)
                makes the chips comfortable to tap on phones. `scroll-smooth`
                + `scrollIntoView` on the active chip below means a tap on
                a partially-clipped chip smoothly centres it instead of
                jumping abruptly to the snap point. */}
            <div
              ref={chipsScrollerRef}
              className="scroll-smooth -mx-3 overflow-x-auto overscroll-x-contain px-3 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
              style={{
                maskImage:
                  "linear-gradient(to right, black 0%, black calc(100% - 24px), transparent 100%)",
                WebkitMaskImage:
                  "linear-gradient(to right, black 0%, black calc(100% - 24px), transparent 100%)",
                WebkitOverflowScrolling: "touch",
              }}
            >
              <div className="flex snap-x gap-1.5">
                {visibleBuckets.map((b) => (
                  <button
                    key={b.key}
                    type="button"
                    ref={(el) => {
                      if (el) chipRefs.current[b.key] = el;
                      else delete chipRefs.current[b.key];
                    }}
                    onClick={() => setBucketKey(b.key)}
                    className={cn(
                      "inline-flex h-8 shrink-0 snap-center items-center gap-1 whitespace-nowrap rounded-full border px-3.5 text-[12px] font-bold transition-colors",
                      bucketKey === b.key
                        ? "border-primary bg-primary text-primary-foreground shadow-sm shadow-primary/30"
                        : "border-border bg-card text-foreground/75 hover:text-foreground",
                    )}
                  >
                    {b.key === "favorites" && (
                      <PiStarFill className={cn("size-3.5", bucketKey === b.key ? "" : "text-primary")} />
                    )}
                    {b.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div
            className="min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain scrollbar-thin"
            style={{ WebkitOverflowScrolling: "touch" }}
          >
            {list.length > 0 && !searchingNow && (
              <div className="sticky top-0 z-[1] flex items-center gap-1.5 border-b border-border/60 bg-background px-3 py-1.5 text-[10.5px] font-bold text-muted-foreground">
                <SortHeader label="Symbol" k="symbol" sort={sort} onSort={cycleSort} className="flex-1 justify-start" />
                <SortHeader label="LTP" k="ltp" sort={sort} onSort={cycleSort} className="w-[72px] justify-end" />
                <SortHeader label="Change" k="change" sort={sort} onSort={cycleSort} className="w-[60px] justify-end" />
                {managedSegmentName && <span className="w-6 shrink-0" />}
              </div>
            )}
            {list.length === 0 && (
              <div className="grid h-24 place-items-center px-4 text-center text-xs text-muted-foreground">
                {search.trim()
                  ? "No instruments match"
                  : managedSegmentName
                    ? `No instruments yet. Search above to add to ${bucket?.label}.`
                    : "Add instruments to your watchlist to see them here."}
              </div>
            )}
            {list.map((q: any) => {
              const token = String(q.instrument_token);
              const isActive = token === String(activeToken);
              const starred = isFav(token);
              const liveOverlay = quoteByToken.get(token);
              const bid = q.bid ?? liveOverlay?.bid ?? null;
              const ask = q.ask ?? liveOverlay?.ask ?? null;
              const ltp = q.ltp ?? liveOverlay?.ltp ?? null;
              const changePct = q.change_pct ?? liveOverlay?.change_pct ?? null;
              const inSearchMode = debouncedSearch.trim().length > 0;
              // The segment "Add" targets: the selected managed chip, or — in
              // All, where no chip is selected — the row's own.
              const rowSeg: string | null =
                managedSegmentName ??
                (bucket?.mode === "all" ? (q.managed_row ?? null) : null);
              const alreadyAdded = rowSeg
                ? managedSegmentName
                  ? addedTokenSet.has(token)
                  : addedInAllView.has(token)
                : false;
              // All is a catalogue like a search, so it offers Add / ✓ rather
              // than the browse-mode star + remove pair.
              const addMode = inSearchMode || bucket?.mode === "all";
              // Favourite star leads the row (as in the reference design);
              // the right edge keeps the one segment action: Add / ✓ in a
              // catalogue, remove-from-chip on a managed chip.
              const star = (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleFavorite(token);
                  }}
                  aria-label={starred ? `Remove ${q.symbol} from favorites` : `Add ${q.symbol} to favorites`}
                  title={starred ? "Remove from favorites" : "Add to favorites"}
                  className="-ml-1 grid size-7 shrink-0 place-items-center rounded-full hover:bg-muted/50"
                >
                  <Star
                    className={cn(
                      "size-[17px] transition-colors",
                      starred ? "fill-primary text-primary" : "text-muted-foreground/70",
                    )}
                  />
                </button>
              );
              let leading: React.ReactNode = star;
              let rightAction: React.ReactNode = null;
              if (rowSeg && addMode) {
                leading = null;
                rightAction = alreadyAdded ? (
                  <span
                    title="Already added"
                    className="grid size-7 shrink-0 place-items-center text-[12px] font-bold text-emerald-500"
                  >
                    ✓
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      addToSegment(token, q.symbol, rowSeg);
                    }}
                    aria-label={`Add ${q.symbol}`}
                    title={`Add to ${rowSeg.replace("_", " ")}`}
                    // A word, not a glyph. Adding is what starts the price for
                    // this instrument, so the control says what it does.
                    className="shrink-0 rounded-lg bg-primary px-3 py-1.5 text-[11px] font-extrabold uppercase tracking-wide text-primary-foreground shadow-sm shadow-primary/30 transition-transform active:scale-95"
                  >
                    Add
                  </button>
                );
              } else if (rowSeg) {
                rightAction = (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFromSegment(token, q.symbol);
                    }}
                    aria-label={`Remove ${q.symbol}`}
                    title={`Remove from ${bucket?.label}`}
                    className="grid size-6 shrink-0 place-items-center rounded-full text-muted-foreground/70 hover:bg-muted/50 hover:text-foreground"
                  >
                    <X className="size-3.5" />
                  </button>
                );
              }
              return (
                <InstrumentRow
                  key={token}
                  token={token}
                  symbol={q.symbol}
                  name={q.name ?? null}
                  exchange={q.exchange}
                  segment={q.segment}
                  bid={bid}
                  ask={ask}
                  ltp={ltp}
                  changePct={changePct}
                  expiry={q.expiry ?? null}
                  strike={q.strike ?? null}
                  lotSize={q.lot_size ?? null}
                  isActive={isActive}
                  onSelect={() =>
                    onSelect(token, {
                      ltp,
                      bid,
                      ask,
                      symbol: q.symbol,
                      exchange: q.exchange,
                      segment: q.segment ?? q.instrument_type,
                    })
                  }
                  leading={leading}
                  rightAction={rightAction}
                />
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Single row in the instruments list. Extracted as its own component so the
 * sticky-display hook for change% has a stable hook-call site — earlier
 * inlining it inside the `list.map()` callback violated the rules-of-hooks.
 * Receives every value pre-resolved by the parent so this stays a pure
 * presentational node. Card-level memoisation is intentionally NOT added:
 * each row depends on its own live ticks via the sticky hooks inside
 * FlashCell + useStickyNumber, so we want the row to repaint on every
 * change. Memoising on prop equality would defeat that.
 */
/** "2026-09-25" -> "25 Sep". The row has very little width and the year is
 *  never the thing that distinguishes two live contracts. */
function fmtExpiry(v: string): string {
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

function SortHeader({
  label,
  k,
  sort,
  onSort,
  className,
}: {
  label: string;
  k: SortKey;
  sort: { key: SortKey; dir: 1 | -1 } | null;
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  const on = sort?.key === k;
  return (
    <button
      type="button"
      onClick={() => onSort(k)}
      className={cn("inline-flex shrink-0 items-center gap-0.5", on && "text-primary", className)}
      aria-label={`Sort by ${label}`}
    >
      {label}
      <PiArrowsDownUpBold className={cn("size-3", on ? "opacity-100" : "opacity-60")} />
    </button>
  );
}

function InstrumentRow({
  token,
  symbol,
  name,
  exchange,
  segment,
  bid,
  ask,
  ltp,
  changePct,
  expiry,
  strike,
  lotSize,
  isActive,
  onSelect,
  leading,
  rightAction,
}: {
  token: string;
  symbol: string;
  name?: string | null;
  exchange?: string;
  segment?: string;
  bid: number | null;
  ask: number | null;
  ltp: number | null;
  changePct: number | null;
  /** Shown in place of the price on a row nothing is subscribed for. */
  expiry?: string | null;
  strike?: number | string | null;
  lotSize?: number | null;
  isActive: boolean;
  onSelect: () => void;
  leading: React.ReactNode;
  rightAction: React.ReactNode;
}) {
  const stickyChange = useStickyNumber(changePct);
  // One price column (LTP, falling back to the book when a feed sends no
  // last trade) and a change pill — the reference layout. Both columns are
  // a FIXED width, so a long symbol truncates instead of pushing into the
  // price: that overlap is what this layout exists to stop.
  const stickyLtp = useStickyNumber(ltp ?? (bid != null && ask != null ? (bid + ask) / 2 : bid ?? ask));
  const flash = usePriceFlash(stickyLtp);
  // Nothing subscribed for this row (a search result / a browse listing).
  // Dashes where the price belongs read as a broken feed, so the row shows
  // what it DOES know — the contract — and the price appears once added.
  const priceless = stickyLtp == null;
  const detail = [
    expiry ? fmtExpiry(expiry) : null,
    Number(strike) > 0 ? Number(strike).toLocaleString("en-IN") : null,
    lotSize && lotSize > 1 ? `Lot ${lotSize}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const cleanName = name && name.toUpperCase() !== String(symbol).toUpperCase() ? name : null;
  const subtitle = detail || cleanName || exchange || "";
  const up = (stickyChange ?? 0) >= 0;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "flex w-full cursor-pointer items-center gap-1.5 border-b border-border/50 px-3 py-2.5 transition-colors",
        isActive ? "bg-primary/10" : "hover:bg-muted/30 active:bg-muted/50",
      )}
    >
      {leading}
      <SymbolAvatar symbol={symbol} changePct={stickyChange} className="size-8 text-[10px]" />

      <div className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className={cn("truncate text-[13px] font-extrabold tracking-tight", isActive && "text-primary")}>
          {symbol}
        </span>
        {subtitle && (
          <span className="mt-0.5 truncate text-[10.5px] font-semibold text-muted-foreground">
            {titleCase(subtitle)}
          </span>
        )}
      </div>

      {!priceless && (
        <>
          <span
            className={cn(
              "w-[72px] shrink-0 truncate text-right font-tabular text-[13px] font-bold tabular-nums transition-colors duration-300",
              flash === "up" ? "text-emerald-500" : flash === "down" ? "text-red-500" : "text-foreground",
            )}
          >
            {formatPrice(stickyLtp, segment, exchange)}
          </span>
          <span
            className={cn(
              "w-[60px] shrink-0 rounded-md py-1 text-center font-tabular text-[11px] font-bold tabular-nums",
              stickyChange == null
                ? "bg-muted text-muted-foreground"
                : up
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                  : "bg-red-500/15 text-red-600 dark:text-red-400",
            )}
          >
            {stickyChange != null ? `${up ? "+" : ""}${stickyChange.toFixed(2)}%` : "—"}
          </span>
        </>
      )}

      {rightAction}
    </div>
  );
}

/** "RELIANCE INDUSTRIES" → "Reliance Industries"; leaves "NSE" and dates alone. */
function titleCase(s: string): string {
  return /[a-z]/.test(s) || s.length <= 4 ? s : s.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

/** Returns the latest non-null/non-zero value the cell has ever held.
 *  Use for the change% chip — same flicker reason as the price cells:
 *  during REST/WS hand-off it briefly becomes null and the percentage
 *  pill disappears. Sticky version keeps the last good % on screen. */
function useStickyNumber(value: number | null | undefined): number | null {
  const lastGoodRef = useRef<number | null>(null);
  if (value != null && Number.isFinite(value)) {
    lastGoodRef.current = value as number;
  }
  return lastGoodRef.current;
}
