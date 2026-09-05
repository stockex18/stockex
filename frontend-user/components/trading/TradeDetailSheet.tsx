"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowDownRight,
  ArrowUpRight,
  ArrowLeftRight,
  Info,
  LineChart,
  Layers,
  Minus,
  Plus,
  ShoppingBag,
  Target,
  Timer,
  Zap,
} from "lucide-react";
import { OptionChainPicker } from "@/components/trading/OptionChainPicker";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  AccountsAPI,
  InstrumentAPI,
  OrderAPI,
  PositionAPI,
  SegmentSettingsAPI,
  WalletAPI,
} from "@/lib/api";
import { playBuyTone, playSellTone } from "@/lib/trade-audio";
import { useMarketStream } from "@/lib/useMarketStream";
import { getIndexLotSize } from "@/lib/indexLots";
import { isInstrumentMarketOpen, marketLabel } from "@/lib/marketHours";
import { walletKindForSegment } from "@/lib/wallets";
import { cn, formatINR, formatIST, formatPercent, pnlColor } from "@/lib/utils";

interface Props {
  token: string | null;
  open: boolean;
  onClose: () => void;
  /**
   * Optional: when set + viewport is mobile, the in-sheet Option Chain
   * picker calls `onSwap(newToken)` instead of navigating to /terminal.
   * Parent updates its `token` state and this same sheet re-mounts with
   * the picked strike — the user stays inside the bottom-sheet flow
   * without ever bouncing to the chart route on a phone. Desktop keeps
   * the /terminal navigation since the full chart is more useful with
   * a wide viewport.
   */
  onSwap?: (token: string) => void;
  /** Preselect BUY or SELL when the card opens (e.g. from the chart's
   *  SELL / BUY strip). Defaults to BUY. */
  initialSide?: "BUY" | "SELL";
  /** Last-known price + identity from the list row the user tapped. Shown
   *  INSTANTLY so the card never sits at "0.00" / "Instrument not loaded"
   *  for the 5-7 s its own fresh WS connection + cold REST fetches take on
   *  first open. The live WS tick / REST detail take over the moment they
   *  arrive. `symbol/exchange/segment` seed the instrument so BUY/SELL work
   *  immediately instead of erroring with "Instrument not loaded". */
  seedQuote?: {
    ltp?: number | null;
    bid?: number | null;
    ask?: number | null;
    symbol?: string | null;
    exchange?: string | null;
    segment?: string | null;
  } | null;
}

/**
 * Slide-up trade card. Opens over the Markets page when a row is tapped.
 * Card-style modal (not a full route) so closing returns the trader to the
 * exact scroll position in the watchlist they left. All sections are wired
 * to live data: instrument detail, 1 s quote, segment-resolved margin %,
 * wallet summary for available balance, open-position count for the badge.
 *
 * Theme: uses the project's purple `primary` for accent CTAs (Market tab,
 * BUY-side preselect), `buy` (green) and `sell` (red) for direction, never
 * pulling in foreign colours from external mocks.
 */
export function TradeDetailSheet(props: Props) {
  // Lazy-mount: when the sheet is closed we render NOTHING. That tears down
  // every useQuery / useState / useMemo inside the inner component, which
  // matters because the marketwatch page mounts this sheet permanently —
  // without the early-return, the closed sheet still occupied React-tree
  // memory and ran a useMarketStream WS (via the React Query cache it
  // shares with the order panel), making the watchlist feel sluggish.
  if (!props.open || !props.token) return null;
  // KEYED ON THE TOKEN. Without this, switching instrument while the sheet is
  // OPEN — which is what `onSwap` and a second tap on the list both do — keeps
  // the same component instance alive, and every useState / useRef inside it
  // survives the change. The sticky price cells, the typed limit / SL / TP,
  // the seeded quote: all still the PREVIOUS instrument's, until the new one's
  // own quote lands a beat later.
  //
  // Reported exactly that way: "TCS pe tha, SBI pe gaya, SBI me TCS ka price
  // dikha — aur order us par lag gaya". The lazy-mount above only tears state
  // down when the sheet CLOSES, and swapping never closes it.
  //
  // A changed key makes React build a fresh instance, so nothing can carry
  // across. One line, and the whole class of stale-carry-over goes with it.
  return <TradeDetailSheetInner key={props.token} {...props} />;
}

function TradeDetailSheetInner({ token, open, onClose, onSwap, initialSide, seedQuote }: Props) {
  const qc = useQueryClient();

  // ── Live data ─────────────────────────────────────────────────────
  // Instrument detail is essentially static — cache for 5 min, no refetch
  // on focus / mount (the Markets page already loaded most of these).
  const { data: instrument } = useQuery({
    queryKey: ["instrument", token],
    queryFn: () => InstrumentAPI.detail(token!),
    enabled: !!token,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    // Seed a minimal instrument from the tapped list row so the card is
    // immediately usable (symbol/segment render, BUY/SELL no longer hit the
    // "Instrument not loaded" guard) while the full detail loads. The real
    // detail — with the authoritative lot_size etc. — replaces this within
    // ~1 s; we deliberately DON'T fake a lot_size here so the lotSize chain
    // keeps falling back correctly until the true value lands.
    placeholderData:
      token && seedQuote?.symbol
        ? {
            instrument_token: token,
            token,
            symbol: seedQuote.symbol,
            exchange: seedQuote.exchange ?? undefined,
            segment: seedQuote.segment ?? undefined,
          }
        : undefined,
  });

  // 1.5 s quote — slightly slower than the OrderPanel's 1 s but a sheet that
  // ticks every second on a busy phone re-renders heavily and starves the
  // chart paint loop. 1.5 s still feels live, costs 33 % fewer requests.
  const { data: quote } = useQuery({
    queryKey: ["quote", token],
    queryFn: () => InstrumentAPI.quote(token!),
    enabled: !!token,
    refetchInterval: 1500,
    staleTime: 1000,
  });

  // ── Instant price via the live WS stream ──────────────────────────
  // The REST `/quote` above does a cold fetch when the sheet opens — and
  // when the tapped token isn't already on Zerodha's WS pool it falls back
  // to a Kite REST snapshot that can take ~2-3 s, so the card sat at
  // "0.00" until it landed (user-flagged). The WS sends a SNAPSHOT the
  // instant we subscribe (the token is almost always already streaming —
  // the user tapped it from a price-showing list), so this paints the LTP
  // / bid / ask in ~100-300 ms. We OVERLAY it on top of the REST quote
  // (which still supplies change%, OHLC, depth). The sheet is lazy-mounted
  // (renders nothing while closed), so this WS only runs while it's open.
  const liveQuotes = useMarketStream(token ? [String(token)] : []);
  const liveTick = token ? liveQuotes.get(String(token)) : undefined;

  const { data: walletSummary } = useQuery({
    queryKey: ["wallet", "summary"],
    queryFn: () => WalletAPI.summary(),
    refetchInterval: 10_000,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });

  // Multi-wallet: the order debits the SEGMENT wallet for this instrument, not
  // Main. Fetch per-wallet balances so the margin gauge + insufficient-funds
  // pre-check test the same wallet the server does.
  const { data: mwAccounts } = useQuery<any>({
    queryKey: ["accounts"],
    queryFn: () => AccountsAPI.list(),
    staleTime: 5_000,
  });

  const { data: openPositions } = useQuery({
    queryKey: ["positions", "open"],
    queryFn: () => PositionAPI.open(),
    refetchInterval: 6_000,
    staleTime: 3_000,
    refetchOnWindowFocus: false,
  });

  // Live unrealised P&L across ALL open positions — used to compute Equity
  // (= total balance + open unrealised) for the wallet strip below.
  const { data: pnlSummary } = useQuery({
    queryKey: ["positions", "pnl-summary"],
    queryFn: () => PositionAPI.pnlSummary(),
    refetchInterval: 5_000,
    staleTime: 2_000,
    refetchOnWindowFocus: false,
  });

  // ── Local UI state — reset whenever the sheet opens a fresh token ─
  const [side, setSide] = useState<"BUY" | "SELL">(initialSide ?? "BUY");
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [slTpEnabled, setSlTpEnabled] = useState(false);
  const [stopLoss, setStopLoss] = useState<string>("");
  const [target, setTarget] = useState<string>("");
  const [limitPrice, setLimitPrice] = useState<string>("");
  const [unit, setUnit] = useState<"LOTS" | "QTY">("LOTS");
  const [lots, setLots] = useState<number>(1);
  // Local string buffer for the stepper input. Lets the user clear the
  // field, type intermediate states ("0." while typing "0.5"), or wipe
  // and retype freely without the controlled-input bouncing back to the
  // committed `lots` value on every keystroke. Committed to `lots` on
  // blur / Enter, and mirrored back here whenever `lots` changes via
  // the +/− buttons or external resets.
  const [lotInput, setLotInput] = useState<string>("");
  const [submitting, setSubmitting] = useState<"BUY" | "SELL" | null>(null);
  // Option-chain picker open state. Only meaningful for Indian
  // equity/index/future rows (see `showOptionChain` below).
  const [optionChainOpen, setOptionChainOpen] = useState(false);
  const [showScriptInfo, setShowScriptInfo] = useState(false);
  // True for ~250 ms while the in-sheet OptionChainPicker is swapping
  // the parent's `token` to a freshly-picked strike. Used by the outer
  // Dialog's `onOpenChange` below to ignore the spurious close event
  // that the inner picker's Radix Dialog dismisses up the tree on
  // some Android viewports (mobile tap-through on the stacked
  // overlays). Without it, picking a strike in the sheet's option
  // chain would call onClose() → parent setTradeToken(null) → outer
  // sheet unmounts before the new token's setSheetToken can reach the
  // parent. User-flagged: "marketwatch se stock open karne ke baad
  // option chain me strike click karne par card open nahi hota,
  // sheet band ho jata".
  const swappingRef = useRef(false);
  const router = useRouter();

  // ── Segment + product ─────────────────────────────────────────────
  const seg = (instrument?.segment ?? "").toUpperCase();
  const exch = (instrument?.exchange ?? "").toUpperCase();
  const isCrypto = seg.includes("CRYPTO") || exch === "CRYPTO";
  const isForex = seg.includes("FOREX") || seg.includes("FX") || exch === "CDS";
  const isFno = seg.includes("FUTURE") || seg.includes("OPTION");
  // Indian equity / index / future rows expose an Option Chain shortcut
  // — tapping it opens the strike grid for THIS underlying (NIFTY,
  // RELIANCE, SENSEX…) like Zerodha Kite. Hidden on Infoway-fed rows
  // (forex / crypto / metals / energy / international equities, since
  // those don't trade options on this platform) and on option rows
  // themselves (the user is already inside an option contract).
  const isIndianExch = ["NSE", "BSE", "NFO", "BFO", "MCX"].includes(exch);
  const isOptionRow = seg.includes("OPTION");
  const showOptionChain = isIndianExch && !isOptionRow;
  // Infoway-fed instruments (forex / crypto / spot metals / energy /
  // international equities + indices) settle in 24×5 or 24×7 mode — they
  // don't have a separate carry-forward margin tier the way Indian F&O
  // does. The margin posted at fill IS the margin held overnight, so we
  // collapse the Intraday/Holding tile pair into a single "Margin" tile
  // for these rows. Indian segments still show both because admin can
  // configure different intraday-vs-overnight requirements there.
  const isInfowaySeg =
    /CRYPTO|FOREX|FX|CDS|STOCKS|INDICES|COMMODITIES/.test(seg) ||
    exch === "CDS" ||
    exch === "CRYPTO";
  // FX conversion is disabled platform-wide — Infoway feed numbers are
  // INR by convention now. Keeping the variable so the margin formula and
  // currency-prefix logic below don't fork; both naturally fall into the
  // "treat as INR" branch.
  const isUsdQuoted = false;
  const productType: "MIS" | "NRML" | "CNC" =
    isCrypto || isForex ? "NRML" : "MIS";

  // ── Segment settings ──────────────────────────────────────────────
  // Admin's margin %/lot caps change rarely — 30 s refetch is plenty, and
  // a generous staleTime keeps the BUY ↔ SELL flip instant (was hitting
  // network on every toggle because the queryKey embeds `side`).
  const { data: effSettings } = useQuery({
    queryKey: ["segment-settings", token, side, productType],
    queryFn: () => SegmentSettingsAPI.effective(token!, side, productType),
    enabled: !!token,
    refetchInterval: 30_000,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });

  // ── Lot resolution (matches OrderPanel) ───────────────────────────
  const minLot =
    Number(effSettings?.min_lot ?? (isCrypto ? 0.001 : isForex ? 0.01 : 1)) || 1;
  const maxLotPerOrder = Number(effSettings?.order_lot ?? 0) || 0;
  const maxLotTotal = Number(effSettings?.max_lot ?? 0) || 0;
  const lotStep = minLot < 1 ? +minLot.toFixed(3) : 1;
  const canonicalLot =
    isCrypto || isForex
      ? null
      : getIndexLotSize(instrument?.symbol, instrument?.name, instrument?.trading_symbol);
  const lotSize = canonicalLot ?? effSettings?.lot_size ?? instrument?.lot_size ?? 1;

  // `liveLots` mirrors the committed `lots` until the trader starts
  // editing the lot field, at which point it tracks the unsubmitted
  // string so margin / qty / total-value tiles update on every
  // keystroke (matches desktop OrderPanel's behaviour where the
  // stepper writes straight into `lots`). Falls back to `lots` when
  // the buffer is empty or a mid-edit intermediate like "0." parses
  // to NaN. The actual order body still goes through `lotsToUse` in
  // submit() — that path also reads `lotInput` so a tap-BUY-before-
  // blur fires with the visible value, not the stale state.
  const liveLots = (() => {
    const n = Number(lotInput);
    if (!Number.isFinite(n) || n <= 0) return lots;
    return unit === "LOTS" ? n : n / Math.max(1, lotSize);
  })();
  const liveQty = +(liveLots * Math.max(1, lotSize)).toFixed(3);

  // Reset form state whenever the sheet (re)opens for a different token.
  // Dep is intentionally just `[token, open]` — including `minLot` would
  // reset the user's mid-trade lot input whenever effSettings refetches
  // (every 30 s) and the resolver re-emitted the same min value with a
  // different Number reference, which manifested as "I can't change the
  // lots on mobile".
  // Indian exchanges always open at 1 lot (operator preference);
  // forex / crypto fall back to the fractional segment minimum.
  const isIndianExchange =
    exch === "NSE" || exch === "BSE" || exch === "MCX" || exch === "NFO" || exch === "BFO";
  const defaultLot = isIndianExchange ? Math.max(1, minLot) : minLot;

  useEffect(() => {
    if (!open) return;
    setLots(defaultLot);
    setStopLoss("");
    setTarget("");
    setLimitPrice("");
    setSide(initialSide ?? "BUY");
    setOrderType("MARKET");
    setSlTpEnabled(false);
    setUnit("LOTS");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, open, initialSide]);

  // ── Pricing ───────────────────────────────────────────────────────
  // Prefer the live WS tick (arrives in ~100-300 ms) over the cold REST
  // quote (~2-3 s on first open). Each field falls back independently so a
  // partial tick (ltp but no bid yet) still shows a price immediately.
  // `last_ltp` is the LAST REAL PRICE the feed saw, kept by the server when
  // the live one goes to 0 (market closed, a contract that has not ticked
  // yet, a token only just subscribed). Without it the sheet showed
  // "LTP 0.00" and "BUY 0.00" while the O/H/L/C row right underneath printed
  // real numbers from the same payload — which reads as broken, not as shut.
  //
  // Display and the margin PREVIEW use it. Execution does not: the server
  // sends `ltp: 0` for these and the order gate refuses to fill against a
  // price with no live session behind it, exactly as before.
  const ltp = Number(
    liveTick?.ltp || quote?.ltp || seedQuote?.ltp || quote?.last_ltp || 0,
  );
  /** True when the number on screen is a remembered price, not a live one. */
  const isLastKnown =
    !(liveTick?.ltp || quote?.ltp || seedQuote?.ltp) && Number(quote?.last_ltp) > 0;
  const bid = Number(
    liveTick?.bid || quote?.bid || quote?.depth?.bids?.[0]?.price || seedQuote?.bid || ltp,
  );
  const ask = Number(
    liveTick?.ask || quote?.ask || quote?.depth?.asks?.[0]?.price || seedQuote?.ask || ltp,
  );
  const sellPrice = bid || ltp;
  const buyPrice = ask || ltp;
  const sideQuote = side === "BUY" ? buyPrice : sellPrice;
  const refPrice = orderType === "MARKET" ? sideQuote : Number(limitPrice || ltp);
  // fx_rate is intentionally not consumed — margin/notional run on the
  // raw feed number which we now interpret as INR.
  void quote?.fx_rate;
  const fxMultiplier = 1;

  // ── Margin ────────────────────────────────────────────────────────
  const serverMarginPct =
    effSettings?.margin_percentage != null
      ? Number(effSettings.margin_percentage) / 100
      : isFno
        ? 0.13
        : isCrypto
          ? 0.2
          : isForex
            ? 0.05
            : 1.0;
  const serverLeverage = Number(effSettings?.leverage ?? 1) || 1;
  const marginCalcMode = String(effSettings?.margin_calc_mode || "").toLowerCase();
  const fixedMarginPerLot = Number(effSettings?.fixed_margin_per_lot ?? 0);
  // Backend now returns dedicated carry-forward (overnight) margin params
  // so the frontend doesn't have to guess (the old `intraday × 1.4` was
  // wrong for every non-NSE-equity segment). For intraday-only segments
  // (Forex / Crypto / spot Commodity) the overnight numbers come back
  // equal to intraday, which folds into the same `marginPerLot` math.
  const serverOvernightMarginPct =
    effSettings?.overnight_margin_percentage != null
      ? Number(effSettings.overnight_margin_percentage) / 100
      : serverMarginPct;
  const serverOvernightLeverage =
    Number(effSettings?.overnight_leverage ?? serverLeverage) || serverLeverage;
  const overnightFixedMarginPerLot = Number(
    effSettings?.overnight_fixed_margin_per_lot ?? fixedMarginPerLot,
  );
  // Strike-based option-WRITING margin: strike × qty × rate. Mirrors the
  // backend validator's `strike_pct` branch, and the same branch the desktop
  // OrderPanel already had — this sheet is the mobile order ticket and never
  // got it, so selling a call or put here previewed the wrong number.
  //
  // Without the branch it does NOT fail loudly: in strike_pct mode the
  // resolver returns 100% / 1x, so the generic formula below collapses to
  // lot_size × price — the PREMIUM a buyer pays, not the strike a writer is
  // exposed to. COPPER26SEP1400CE showed ~28.83/lot against a real 1400 ×
  // 0.08 requirement.
  //
  // SELL only. Buying an option is genuinely premium-based and stays below.
  const strikeMarginRate = Number(effSettings?.strike_margin_rate ?? 0);
  const ovnStrikeMarginRate = Number(effSettings?.overnight_strike_margin_rate ?? 0);
  // The settings endpoint resolves the strike for THIS token and always
  // carries it; the instrument object handed in from search or the watchlist
  // often does not, which would fall the preview through to the premium
  // again. Same precedence the desktop panel uses.
  const instrumentStrike = Number(
    effSettings?.strike ?? (instrument as any)?.strike ?? 0,
  );

  const marginPerLot = useMemo(() => {
    if (
      marginCalcMode === "strike_pct" &&
      strikeMarginRate > 0 &&
      side === "SELL" &&
      instrumentStrike > 0
    ) {
      return +(instrumentStrike * lotSize * strikeMarginRate).toFixed(2);
    }
    if (marginCalcMode === "fixed" && fixedMarginPerLot > 0) {
      return +fixedMarginPerLot.toFixed(2);
    }
    return +(
      ((lotSize * (refPrice || ltp || 0) * serverMarginPct) / serverLeverage) *
      fxMultiplier
    ).toFixed(2);
  }, [marginCalcMode, strikeMarginRate, side, instrumentStrike, fixedMarginPerLot, lotSize, refPrice, ltp, serverMarginPct, serverLeverage, fxMultiplier]);

  // Carry-forward (overnight) per-lot margin — same formula as intraday
  // but with the overnight leverage / margin% the admin configured for
  // this segment. Falls back to intraday math when the backend hasn't
  // populated the overnight fields yet (older deploys).
  const overnightMarginPerLot = useMemo(() => {
    if (
      marginCalcMode === "strike_pct" &&
      ovnStrikeMarginRate > 0 &&
      side === "SELL" &&
      instrumentStrike > 0
    ) {
      return +(instrumentStrike * lotSize * ovnStrikeMarginRate).toFixed(2);
    }
    if (marginCalcMode === "fixed" && overnightFixedMarginPerLot > 0) {
      return +overnightFixedMarginPerLot.toFixed(2);
    }
    return +(
      ((lotSize * (refPrice || ltp || 0) * serverOvernightMarginPct) /
        serverOvernightLeverage) *
      fxMultiplier
    ).toFixed(2);
  }, [
    marginCalcMode,
    ovnStrikeMarginRate,
    side,
    instrumentStrike,
    overnightFixedMarginPerLot,
    lotSize,
    refPrice,
    ltp,
    serverOvernightMarginPct,
    serverOvernightLeverage,
    fxMultiplier,
  ]);

  // Margin tile updates LIVE off `liveLots` so the trader sees the
  // posted-margin number react on every keystroke, just like the
  // desktop OrderPanel where typing into the stepper writes straight
  // into `lots`. submit() still uses `lotsToUse` for the actual order.
  const intradayMargin = +(marginPerLot * liveLots).toFixed(2);
  const carryforwardMargin = +(overnightMarginPerLot * liveLots).toFixed(2);
  // Resolve the segment wallet backing this instrument (crypto → CRYPTO, etc.).
  // Its available_balance + credit_limit is what the server checks; use it for
  // the gauge + pre-check. Fall back to Main only when there's no segment
  // wallet (legacy single-wallet mode).
  const _segWallet = (() => {
    const kind = walletKindForSegment((instrument as any)?.segment as string | undefined);
    if (!kind || kind === "MAIN") return null;
    return (mwAccounts?.wallets ?? []).find((w: any) => w.kind === kind) ?? null;
  })();
  const availableMargin = _segWallet
    ? Number(_segWallet.available_balance ?? 0) + Number(_segWallet.credit_limit ?? 0)
    : Number(walletSummary?.available_balance ?? 0) +
      Number(walletSummary?.credit_limit ?? 0);

  // Open-position count on THIS instrument — small badge by the symbol.
  const openPosCount = useMemo(() => {
    const tok = String(token ?? "");
    if (!tok) return 0;
    return (openPositions ?? []).filter(
      (p: any) => String(p?.instrument_token ?? p?.token ?? "") === tok,
    ).length;
  }, [openPositions, token]);

  // ── Formatters ────────────────────────────────────────────────────
  const priceDecimals = isCrypto ? 2 : isForex ? 4 : 2;
  const priceCcy = "";
  function fmtPrice(n: number | null | undefined): string {
    const v = Number(n ?? 0);
    if (!Number.isFinite(v)) return "—";
    return `${priceCcy}${v.toFixed(priceDecimals)}`;
  }
  function fmtLots(n: number) {
    return isCrypto || isForex ? n.toFixed(isCrypto ? 3 : 2) : String(n);
  }

  // INR formatter for the wallet KPI grid — user feedback was that the
  // abbreviated "K / L / Cr" suffixes hid the exact figure ("4.47 L" is
  // less actionable than "🪙4,47,000.00" when sizing a position). We now
  // render the full Indian-grouped number everywhere and let the card
  // width handle overflow (auto-shrink via `truncate`/CSS clamp).
  function formatINRCompact(value: number | null | undefined): string {
    // Whole rupees only (drop paise) so the full number fits the slim 3-up
    // margin cards without truncating — 🪙2,23,160 instead of 🪙2,23,160.00.
    const n = Math.round(Number(value ?? 0));
    return `${n < 0 ? "-" : ""}🪙${Math.abs(n).toLocaleString("en-IN")}`;
  }

  const expiryShort = useMemo(() => {
    const raw = instrument?.expiry;
    if (!raw) return "";
    const s = String(raw).slice(0, 10);
    const [y, m, d] = s.split("-");
    if (!y || !m || !d) return s;
    const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    const mi = Number(m) - 1;
    if (mi < 0 || mi > 11) return s;
    return `${d} ${months[mi]}`;
  }, [instrument?.expiry]);

  // ── Submit ────────────────────────────────────────────────────────
  async function submit(action: "BUY" | "SELL") {
    if (!instrument || !token) {
      toast.error("Instrument not loaded");
      return;
    }
    // Quote for the side ACTUALLY being submitted. The BUY/SELL buttons call
    // submit() directly and never touch `setSide`, so the `side` state stays
    // pinned at its initial value for the sheet's whole lifetime — reading
    // `sideQuote` here sent the ASK along with a SELL order. The backend
    // honours an expected_price within 1% (the spread is ~0.15%), so the
    // SELL filled at the BUY price: entry == exit, P&L 🪙0 bar charges.
    const actionQuote = action === "BUY" ? buyPrice : sellPrice;
    // Force-commit any pending lot input — the user can tap BUY/SELL
    // without first blurring the lot field on mobile, in which case
    // `lots` state still holds the previous value while `lotInput`
    // carries the new typed string. We parse `lotInput` and use the
    // result locally; the order body below also uses this local so a
    // typed 0.1 lot can't be silently replaced by the stale 1.
    let lotsToUse = lots;
    {
      const pending = Number(lotInput);
      if (Number.isFinite(pending) && pending > 0) {
        const asLots = unit === "LOTS" ? pending : pending / lotSize;
        const rounded = +asLots.toFixed(3);
        // DO NOT silently clamp to maxLotPerOrder here — the admin's
        // per-order cap must be surfaced as a clear rejection toast
        // (next block below), not as a silent reduction of the user's
        // typed quantity. Without this fix, typing 10 lots when the
        // admin cap is 5 used to silently submit 5 — the user thought
        // their full 10-lot order had been split / executed, when
        // really the platform had quietly truncated the request.
        lotsToUse = rounded;
        if (rounded !== lots) setLots(rounded);
      }
    }
    if (!lotsToUse || lotsToUse < minLot) {
      toast.error(`Lots must be at least ${minLot}`);
      return;
    }
    if (maxLotPerOrder > 0 && lotsToUse > maxLotPerOrder) {
      toast.error(`Maximum ${maxLotPerOrder} lot(s) per order`);
      return;
    }
    if (orderType === "LIMIT" && !Number(limitPrice)) {
      toast.error("Enter a limit price");
      return;
    }
    if (intradayMargin > 0 && availableMargin < intradayMargin) {
      toast.error(
        `Insufficient margin — need ${formatINR(intradayMargin)}, have ${formatINR(availableMargin)}`,
      );
      return;
    }
    // Market-closed pre-check — mirror the OrderPanel guard so the
    // mobile bottom-sheet path also fails fast outside trading hours.
    // Without it, the audio cue + synchronous success toast +
    // optimistic position row all fired before the backend rejection
    // came back, producing the "trade ek baar ko lag jaa rahi h fir
    // waps aa rha h" flicker the user reported.
    if (
      !isInstrumentMarketOpen(
        (instrument as any).segment as string | undefined,
        (instrument as any).exchange as string | undefined,
      )
    ) {
      const label = marketLabel(
        (instrument as any).segment as string | undefined,
        (instrument as any).exchange as string | undefined,
      );
      toast.error(
        `${label} market is closed. Try placing an AMO instead.`,
        { duration: 5000 },
      );
      return;
    }

    // 250 ms double-tap lockout (NOT a network wait — the request fires
    // immediately below). Releases by the time the sheet's close
    // animation completes, so a second order on the same instrument
    // becomes possible the moment the user re-opens the sheet.
    setSubmitting(action);
    setTimeout(() => setSubmitting(null), 250);

    // ── Fire-and-forget submission ────────────────────────────────────
    // Earlier the BUY/SELL handler `await`ed OrderAPI.place inside the
    // sheet — that pinned the buttons in a loading spinner for the full
    // 500 ms – 2 s round-trip while the user just stared at the same
    // sheet. The OrderPanel on desktop already uses an
    // optimistic-insert + fire-and-forget pattern that feels instant;
    // this mirrors it for the mobile sheet:
    //   1. validate sync (above)
    //   2. play audio cue (so the click is "felt" before the network)
    //   3. drop an optimistic Position row into the React Query cache
    //   4. close the sheet immediately — user returns to the watchlist
    //      with their position already visible
    //   5. fire the API call in the background; on rejection toast +
    //      roll the optimistic row back so the watchlist stays honest
    if (action === "BUY") playBuyTone();
    else playSellTone();

    // Instant feedback — fire the success toast on the SAME tick as the audio
    // cue, before the network leaves the device, so it feels as fast as the
    // sound. It carries an `id` so that IF the server rejects (market closed /
    // holiday) the `.catch()` REPLACES this toast in place — the one toast
    // morphs into the error instead of stacking a second "market closed" popup
    // under a false "placed". Best of both: instant + no double popup.
    const placedToastId = toast.success(
      `${action} ${fmtLots(lotsToUse)} ${instrument.symbol} placed`,
      { duration: 1500 },
    );

    const optimisticId = `optimistic_${Date.now()}`;
    const fillPrice = orderType === "MARKET" ? actionQuote : Number(limitPrice || ltp) || ltp;
    const signedQty = (action === "BUY" ? 1 : -1) * lotsToUse * lotSize;
    const isImmediate = orderType === "MARKET";

    if (isImmediate) {
      // Cancel any in-flight positions refetch FIRST so the network reply
      // (without our trade) can't overwrite the optimistic row before
      // the user sees it. Same anti-flicker pattern as OrderPanel.
      qc.cancelQueries({ queryKey: ["positions", "open"] });
      qc.setQueryData<any[]>(["positions", "open"], (old) => {
        const prev = Array.isArray(old) ? old : [];
        // Merge with existing position on same instrument + product so
        // pyramiding shows ONE merged row, not two stacked rows.
        const matchIdx = prev.findIndex(
          (p) => p && p.instrument_token === token && p.product_type === productType,
        );
        if (matchIdx < 0) {
          return [
            {
              id: optimisticId,
              _optimistic: true,
              symbol: instrument.symbol,
              exchange: instrument.exchange,
              segment_type: instrument.segment,
              product_type: productType,
              quantity: signedQty,
              lots: (action === "BUY" ? 1 : -1) * lotsToUse,
              lot_size: lotSize,
              avg_price: fillPrice,
              ltp: ltp || fillPrice,
              stop_loss: slTpEnabled && Number(stopLoss) > 0 ? Number(stopLoss) : null,
              target: slTpEnabled && Number(target) > 0 ? Number(target) : null,
              charges: 0,
              unrealized_pnl: 0,
              realized_pnl: 0,
              margin_used: intradayMargin,
              status: "OPEN",
              opened_at: new Date().toISOString(),
              instrument_token: token,
            },
            ...prev,
          ];
        }
        const existing = prev[matchIdx];
        const curQty = Number(existing.quantity) || 0;
        const curAvg = Number(existing.avg_price) || 0;
        const newQty = curQty + signedQty;
        let nextAvg = curAvg;
        if (newQty !== 0 && Math.sign(newQty) === Math.sign(curQty || signedQty)) {
          const totalAbs = Math.abs(curQty) + Math.abs(signedQty);
          nextAvg =
            totalAbs > 0
              ? (curAvg * Math.abs(curQty) + fillPrice * Math.abs(signedQty)) / totalAbs
              : fillPrice;
        }
        const merged = {
          ...existing,
          quantity: newQty,
          avg_price: nextAvg,
          ltp: ltp || existing.ltp,
          margin_used: (Number(existing.margin_used) || 0) + intradayMargin,
        };
        const next = prev.slice();
        if (newQty === 0) next.splice(matchIdx, 1);
        else next[matchIdx] = merged;
        return next;
      });

      // Mirror the fill into the Active-trades cache (per-fill, no merge) so
      // the Active tab shows it instantly instead of waiting for the 2-3 s
      // poll — the iOS Safari "trade lete hi position page 5-7 sec" lag.
      qc.cancelQueries({ queryKey: ["positions", "active-trades"] });
      qc.setQueryData<any[]>(["positions", "active-trades"], (old) => {
        const prev = Array.isArray(old) ? old : [];
        return [
          {
            id: optimisticId,
            _optimistic: true,
            symbol: instrument.symbol,
            exchange: instrument.exchange,
            segment: instrument.segment,
            currency_quote: (instrument as any).currency_quote,
            action,
            side: action,
            product_type: productType,
            quantity: Math.abs(signedQty),
            lots: lotsToUse,
            lot_size: lotSize,
            price: fillPrice,
            avg_price: fillPrice,
            ltp: ltp || fillPrice,
            margin: intradayMargin,
            used_margin: intradayMargin,
            margin_used: intradayMargin,
            stop_loss: slTpEnabled && Number(stopLoss) > 0 ? Number(stopLoss) : null,
            target: slTpEnabled && Number(target) > 0 ? Number(target) : null,
            token,
            instrument_token: token,
            status: "OPEN",
            opened_at: new Date().toISOString(),
          },
          ...prev,
        ];
      });
    } else {
      // LIMIT order — park an optimistic row in the orders cache so the
      // pending-orders panel reacts instantly. Shape mirrors backend
      // `_serialize`.
      qc.setQueryData<any[]>(["orders", "recent"], (old) => {
        const prev = Array.isArray(old) ? old : [];
        const limitPriceNum = Number(limitPrice || 0);
        return [
          {
            id: optimisticId,
            _optimistic: true,
            order_number: "—",
            symbol: instrument.symbol,
            exchange: instrument.exchange,
            segment: instrument.segment,
            token,
            instrument_token: token,
            action,
            order_type: orderType,
            product_type: productType,
            validity: "DAY",
            lots: lotsToUse,
            quantity: lotsToUse * lotSize,
            filled_quantity: 0,
            pending_quantity: lotsToUse * lotSize,
            price: String(limitPriceNum),
            trigger_price: "0",
            average_price: "0",
            status: "OPEN",
            rejection_reason: null,
            is_amo: false,
            margin_blocked: String(intradayMargin),
            brokerage: "0",
            other_charges: "0",
            bracket_stop_loss:
              slTpEnabled && Number(stopLoss) > 0 ? String(Number(stopLoss)) : null,
            bracket_target:
              slTpEnabled && Number(target) > 0 ? String(Number(target)) : null,
            created_at: new Date().toISOString(),
            executed_at: null,
          },
          ...prev,
        ];
      });
    }

    // Close the sheet right away — the user returns to the market list
    // with the optimistic position already visible. Toast confirms
    // when the server acks the trade.
    onClose();

    OrderAPI.place({
      token,
      action,
      order_type: orderType,
      product_type: productType,
      lots: lotsToUse,
      price: orderType === "MARKET" ? 0 : Number(limitPrice || 0),
      trigger_price: 0,
      validity: "DAY",
      is_amo: false,
      stop_loss: slTpEnabled && Number(stopLoss) > 0 ? Number(stopLoss) : null,
      target: slTpEnabled && Number(target) > 0 ? Number(target) : null,
      expected_price: orderType === "MARKET" ? actionQuote : null,
    })
      .then(() => {
        // Success toast already fired instantly above; just reconcile caches.
        qc.invalidateQueries({ queryKey: ["orders"] });
        qc.invalidateQueries({ queryKey: ["wallet"] });
        // A MARKET order can (partially) close an opposite open position —
        // refresh the Closed tab so the realised slice appears at once
        // instead of waiting for its 10 s poll / a manual refresh. The
        // delayed retry covers the brief Atlas read-replica lag where the
        // closing Trade isn't on the replica yet on the first refetch.
        if (isImmediate) {
          qc.invalidateQueries({ queryKey: ["positions", "closed"] });
          setTimeout(
            () => qc.invalidateQueries({ queryKey: ["positions", "closed"] }),
            1500,
          );
          // Reconcile the optimistic open + active rows to the REAL position
          // fast. Prod Mongo is single-node (committed by the time this POST
          // resolves), so a short ~600 ms delay swaps the placeholder for the
          // real row almost immediately — no need to wait ~1.8 s for a
          // hypothetical replica to catch up.
          setTimeout(() => {
            qc.invalidateQueries({ queryKey: ["positions", "open"] });
            qc.invalidateQueries({ queryKey: ["positions", "active-trades"] });
          }, 600);
        }
      })
      .catch((e: any) => {
        // Roll the optimistic row back so the watchlist stays honest.
        if (isImmediate) {
          qc.setQueryData<any[]>(["positions", "open"], (old) =>
            Array.isArray(old) ? old.filter((p) => p.id !== optimisticId) : [],
          );
          qc.setQueryData<any[]>(["positions", "active-trades"], (old) =>
            Array.isArray(old) ? old.filter((p) => p.id !== optimisticId) : [],
          );
        } else {
          qc.setQueryData<any[]>(["orders", "recent"], (old) =>
            Array.isArray(old) ? old.filter((o) => o.id !== optimisticId) : [],
          );
        }
        // Morph the instant "placed" toast into the error IN PLACE (same id)
        // → a reject shows ONE toast (placed → "market closed"), not two.
        toast.error(e?.message || "Order rejected", { id: placedToastId });
      });
  }

  // Qty ↔ Lots conversion. Stepper always stores `lots`.
  const qty = lots * lotSize;
  const displayValue = unit === "LOTS" ? fmtLots(lots) : String(qty);
  function bumpLots(delta: number) {
    const next = +(lots + delta).toFixed(3);
    const min = Math.max(minLot, next);
    const capped = maxLotPerOrder > 0 ? Math.min(maxLotPerOrder, min) : min;
    setLots(capped);
  }
  // Keep the stepper input in sync with the canonical `lots` whenever
  // it changes via +/− buttons, BUY/SELL flip, or sheet (re)open. Bail
  // when the user is mid-edit (their string parses to the same numeric
  // value) so a tap on the field doesn't get hijacked by this effect.
  useEffect(() => {
    const canonical = displayValue;
    if (Number(lotInput) !== Number(canonical)) setLotInput(canonical);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lots, unit, lotSize]);

  function commitLotInput() {
    // On blur / Enter: parse whatever's in the field, commit to `lots`.
    // Both lower (minLot) AND upper (maxLotPerOrder) bounds are
    // intentionally NOT clamped here. Two separate bugs we hit:
    //
    //   • Lower clamp used to bump "0.1 lot" entries back up to
    //     admin's min_lot (often 1), so the user saw their typed 0.1
    //     silently jump.
    //   • Upper clamp used to truncate "10 lots" down to admin's
    //     per-order cap (e.g. 5) without any indication — the user
    //     thought their 10-lot order had filled, but only 5 were
    //     actually sent. (The current bug fix.)
    //
    // The placement-time submit() check now rejects out-of-range
    // typed values with a clear toast, so the input can faithfully
    // reflect what the trader wrote and the conversion hint stays
    // accurate.
    const n = Number(lotInput);
    if (!Number.isFinite(n) || n <= 0) {
      setLots(minLot);
      setLotInput(fmtLots(minLot));
      return;
    }
    const asLots = unit === "LOTS" ? n : n / lotSize;
    const rounded = +asLots.toFixed(3);
    setLots(rounded);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (v) return;
        // In-sheet OptionChainPicker is in the middle of swapping the
        // parent's token to a new strike — ignore the close event the
        // inner picker bubbles up. Parent will re-evaluate `open`
        // against the new token in the next render and the sheet
        // stays mounted.
        if (swappingRef.current) return;
        // Picker is still open — the user tapped somewhere inside the
        // picker's stack but didn't pick a strike. Don't tear down the
        // outer sheet just because the inner Dialog is animating
        // closed (mobile overlay stacking quirk).
        if (optionChainOpen) return;
        onClose();
      }}
    >
      <DialogContent className="flex max-h-[92vh] w-[calc(100%-1rem)] max-w-md flex-col gap-0 overflow-y-auto overscroll-contain p-0">
        <DialogTitle className="sr-only">
          Trade {instrument?.symbol ?? ""}
        </DialogTitle>

        {/* ── Header (sticky so price stays visible while the body scrolls) ── */}
        <div className="sticky top-0 z-20 shrink-0 border-b border-border bg-background px-4 py-3">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-lg font-bold">
                  {instrument?.symbol ?? "—"}
                </span>
                {openPosCount > 0 && (
                  <Link
                    href="/positions"
                    aria-label={`${openPosCount} open position${openPosCount === 1 ? "" : "s"}`}
                    className="flex h-5 items-center gap-1 rounded-full bg-primary/15 px-1.5 text-[10px] font-bold text-primary"
                  >
                    <ShoppingBag className="size-3" />
                    {openPosCount}
                  </Link>
                )}
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {expiryShort && <span className="mr-1.5">{expiryShort}</span>}
                LTP <span className="font-tabular tabular-nums">{fmtPrice(ltp)}</span>
                {/* Say so when the number is remembered rather than live —
                    showing a stale price unlabelled is how someone taps BUY
                    expecting that fill. The server refuses it either way. */}
                {isLastKnown && (
                  <span className="ml-1.5 rounded bg-muted px-1 py-px text-[10px] font-semibold uppercase tracking-wide">
                    last close
                  </span>
                )}
              </div>
            </div>
            <div className="pr-7 text-right">
              <div className="flex items-baseline gap-2 font-tabular text-base font-bold tabular-nums">
                <span className="text-sell">{fmtPrice(sellPrice)}</span>
                <span className="text-buy">{fmtPrice(buyPrice)}</span>
              </div>
              <div
                className={cn(
                  "mt-0.5 text-[11px] font-tabular tabular-nums",
                  pnlColor(quote?.change_pct ?? 0),
                )}
              >
                {quote?.change != null ? quote.change.toFixed(2) : "—"} (
                {formatPercent(quote?.change_pct ?? 0)})
              </div>
            </div>
          </div>

          {/* OHLC strip — full-width, 4 equal cells with vertical dividers.
              Replaces the old flex-wrap "O x H x L x C x" row that wrapped
              awkwardly onto multiple lines for long values (e.g. gold
              4218.56), which looked cramped/unprofessional. */}
          {(quote?.open > 0 ||
            quote?.high > 0 ||
            quote?.low > 0 ||
            quote?.prev_close > 0) && (
            <div className="mt-2.5 grid grid-cols-4 overflow-hidden rounded-lg border border-border">
              {[
                { k: "O", v: quote?.open, cls: "text-foreground" },
                { k: "H", v: quote?.high, cls: "text-buy" },
                { k: "L", v: quote?.low, cls: "text-sell" },
                { k: "C", v: quote?.prev_close, cls: "text-foreground" },
              ].map((c, i) => (
                <div
                  key={c.k}
                  className={cn(
                    "flex flex-col items-center justify-center py-1.5",
                    i > 0 && "border-l border-border",
                  )}
                >
                  <span className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {c.k}
                  </span>
                  <span className={cn("font-tabular tabular-nums text-xs", c.cls)}>
                    {c.v > 0 ? Number(c.v).toFixed(2) : "—"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Action row ──────────────────────────────────────────── */}
        <div className="flex items-center gap-2 px-4 pt-3">
          <Link
            href={`/terminal?token=${encodeURIComponent(token ?? "")}`}
            className="flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-medium hover:bg-muted/40"
          >
            <LineChart className="size-3.5" /> Charts
          </Link>
          {showOptionChain && (
            <button
              type="button"
              onClick={() => setOptionChainOpen(true)}
              className="flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-medium hover:bg-muted/40"
            >
              <Layers className="size-3.5" /> Option Chain
            </button>
          )}
          {/* BUY / SELL toggle removed from this row — the big BUY/SELL
              CTAs at the bottom of the sheet already drive direction
              (each carries its own live price label), and the duplicate
              header toggle just confused users who tapped it expecting
              to place a trade. */}
          <button
            type="button"
            onClick={() => setSlTpEnabled((v) => !v)}
            className="ml-auto flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium"
          >
            <Target className="size-3.5" /> SL · TP
            <span
              className={cn(
                "relative inline-block h-4 w-7 rounded-full transition-colors",
                slTpEnabled ? "bg-primary" : "bg-muted",
              )}
            >
              <span
                className={cn(
                  "absolute top-0.5 size-3 rounded-full bg-background transition-all",
                  slTpEnabled ? "left-3" : "left-0.5",
                )}
              />
            </span>
          </button>
        </div>

        {/* ── Stats grid ──────────────────────────────────────────── */}
        {/* LTP High / Low / Open / Last — hidden on mobile to keep
            the bottom-sheet compact so BUY/SELL stays on screen
            without scrolling. Desktop keeps the four-up summary. */}
        <div className="hidden grid-cols-4 gap-2 px-4 pt-4 text-[11px] sm:grid">
          {/* Render an em-dash when the feed hasn't delivered an OHLC
              field yet (typical for fresh subscribes / off-hours), so
              the user doesn't see a confusing "0.0000" placeholder. */}
          <Stat
            label="LTP High"
            value={Number(quote?.high ?? 0) > 0 ? fmtPrice(quote!.high) : "—"}
          />
          <Stat
            label="LTP Low"
            value={Number(quote?.low ?? 0) > 0 ? fmtPrice(quote!.low) : "—"}
          />
          <Stat
            label="Open"
            value={Number(quote?.open ?? 0) > 0 ? fmtPrice(quote!.open) : "—"}
          />
          <Stat
            label="Last Trade"
            value={quote?.timestamp ? formatIST(quote.timestamp, { withSeconds: false }) : "—"}
          />
        </div>

        <div className="my-3 h-px bg-border" />

        {/* ── Lot / script-info row ───────────────────────────────── */}
        <div className="flex items-end gap-2 px-4">
          <div className="flex flex-1 flex-wrap gap-x-4 gap-y-1 text-[11px]">
            <LotMeta label="Min Lots" value={minLot > 0 ? String(minLot) : "—"} />
            <LotMeta label="Max Lots" value={maxLotTotal > 0 ? String(maxLotTotal) : "—"} />
            <LotMeta label="Order Lots" value={maxLotPerOrder > 0 ? String(maxLotPerOrder) : "—"} />
            <LotMeta label="Lot Size" value={String(lotSize)} />
          </div>
          {/* Script info toggle — shows this instrument's trading limits */}
          <button
            type="button"
            onClick={() => setShowScriptInfo((v) => !v)}
            aria-label="Script info"
            aria-expanded={showScriptInfo}
            className={`flex size-8 items-center justify-center rounded-md border transition-colors ${
              showScriptInfo
                ? "border-mp-primary/50 bg-mp-primary/10 text-mp-primary"
                : "border-border bg-card text-muted-foreground hover:bg-muted/40"
            }`}
          >
            <Info className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => setUnit((u) => (u === "LOTS" ? "QTY" : "LOTS"))}
            className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-[11px] font-medium hover:bg-muted/40"
          >
            <ArrowLeftRight className="size-3" />
            {unit === "LOTS" ? "Qty" : "Lots"}
          </button>
        </div>

        {/* Script info — trading limits for THIS instrument (client-facing) */}
        {showScriptInfo && (
          <div className="mx-4 mt-2 rounded-lg border border-border bg-muted/20 p-3">
            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold text-foreground">
              <Info className="size-3.5 text-mp-primary" /> Script info
              <span className="truncate font-normal text-muted-foreground">· {instrument?.symbol}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              <ScriptInfoRow label="Min order" value={`${minLot} lot${minLot === 1 ? "" : "s"}`} />
              <ScriptInfoRow
                label="Max per order"
                value={maxLotPerOrder > 0 ? `${maxLotPerOrder} lots` : "No limit"}
              />
              <ScriptInfoRow
                label="Max lots / script"
                value={maxLotTotal > 0 ? `${maxLotTotal} lots` : "No limit"}
              />
              <ScriptInfoRow label="Lot size" value={`${lotSize} qty`} />
            </div>
          </div>
        )}

        {/* ── Price + Lot stepper ─────────────────────────────────── */}
        <div className="mt-3 grid grid-cols-2 gap-2 px-4">
          <div className="rounded-lg border border-border bg-card px-3 py-3 text-center">
            {orderType === "MARKET" ? (
              <>
                <div className="text-base font-semibold">Market</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Price
                </div>
              </>
            ) : (
              <>
                <input
                  inputMode="decimal"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  placeholder={fmtPrice(refPrice).replace(priceCcy, "")}
                  className="w-full bg-transparent text-center text-base font-semibold outline-none"
                />
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Limit Price
                </div>
              </>
            )}
          </div>
          <div className="flex flex-col items-stretch gap-1 rounded-lg border border-border bg-card px-2 py-2">
            <div className="flex items-center justify-between gap-1">
              <button
                type="button"
                onClick={() => bumpLots(-lotStep)}
                aria-label={unit === "LOTS" ? "Decrease lots" : "Decrease quantity"}
                className="grid size-9 place-items-center rounded-md hover:bg-muted/40"
              >
                <Minus className="size-4" />
              </button>
              <div className="text-center">
                <input
                  inputMode="decimal"
                  pattern="[0-9]*\.?[0-9]*"
                  value={lotInput}
                  onChange={(e) => {
                    // Mobile keyboards (especially Android with predictive
                    // text on) will happily inject letters here even with
                    // `inputMode="decimal"`. Filter to digits + a single
                    // decimal point so the field never lands in a state
                    // like "asdads" → NaN on commit → snap-back to minLot.
                    const cleaned = e.target.value
                      .replace(/[^0-9.]/g, "")
                      .replace(/(\..*)\./g, "$1");
                    setLotInput(cleaned);
                  }}
                  onFocus={(e) => {
                    // Only auto-select when the field still holds the
                    // unedited canonical value (so first-tap-to-replace
                    // works on mount). Once the user has typed anything
                    // custom we LEAVE the cursor where they tapped —
                    // earlier we always called `select()` on focus, so
                    // appending a digit (e.g. wanting to turn "2." into
                    // "2.5") wiped the field and the keystroke replaced
                    // the whole value. User complaint: "qty ko sahi se
                    // edit nahi kar pa raha".
                    if (lotInput === displayValue) {
                      e.currentTarget.select();
                    }
                  }}
                  onBlur={commitLotInput}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      commitLotInput();
                      (e.currentTarget as HTMLInputElement).blur();
                    }
                  }}
                  className="w-24 bg-transparent text-center font-tabular text-lg font-semibold tabular-nums outline-none"
                />
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  {unit === "LOTS" ? "Lot" : "Qty"}
                </div>
              </div>
              <button
                type="button"
                onClick={() => bumpLots(lotStep)}
                aria-label={unit === "LOTS" ? "Increase lots" : "Increase quantity"}
                className="grid size-9 place-items-center rounded-md hover:bg-muted/40"
              >
                <Plus className="size-4" />
              </button>
            </div>
            {/* Live bidirectional conversion hint — always visible so the
                trader doesn't have to flip the unit toggle to see the
                other side. Mirrors the desktop OrderPanel's "1 lot = N
                units · Total: M" pill but tuned tighter for the sheet. */}
            <div className="text-center text-[10px] text-muted-foreground">
              {unit === "LOTS" ? (
                <>= <span className="font-tabular text-foreground">{fmtLots(liveQty)}</span> Qty</>
              ) : (
                <>= <span className="font-tabular text-foreground">{fmtLots(liveLots)}</span> Lot</>
              )}
            </div>
          </div>
        </div>

        {/* ── Order type tabs ─────────────────────────────────────── */}
        <div className="mt-3 grid grid-cols-2 gap-2 px-4">
          <button
            type="button"
            onClick={() => setOrderType("MARKET")}
            className={cn(
              "flex h-10 items-center justify-center gap-1.5 rounded-md text-sm font-semibold transition-colors",
              orderType === "MARKET"
                ? "bg-primary text-primary-foreground"
                : "border border-border bg-card text-muted-foreground",
            )}
          >
            <Zap className="size-4" /> Market
          </button>
          <button
            type="button"
            onClick={() => setOrderType("LIMIT")}
            className={cn(
              "flex h-10 items-center justify-center gap-1.5 rounded-md text-sm font-semibold transition-colors",
              orderType === "LIMIT"
                ? "bg-primary text-primary-foreground"
                : "border border-border bg-card text-muted-foreground",
            )}
          >
            <Timer className="size-4" /> Limit
          </button>
        </div>

        {/* ── SL / TP inputs ──────────────────────────────────────── */}
        {slTpEnabled && (
          <div className="mt-3 grid grid-cols-2 gap-2 px-4">
            <div className="rounded-lg border border-border bg-card px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Stop Loss
              </div>
              <input
                inputMode="decimal"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
                placeholder="Optional"
                className="w-full bg-transparent text-base font-semibold outline-none"
              />
            </div>
            <div className="rounded-lg border border-border bg-card px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Take Profit
              </div>
              <input
                inputMode="decimal"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="Optional"
                className="w-full bg-transparent text-base font-semibold outline-none"
              />
            </div>
          </div>
        )}

        {/* ── Balance + margin (clean 3-up) ───────────────────────────
            Operator spec: show ONLY the three numbers a trader needs
            before placing an order —
              1. Available (equity)  — free balance to deploy
              2. Intraday            — this order's intraday margin
              3. Carry Fwd           — this order's overnight margin
            Replaces the old 5-tile layout (Total Balance / Equity / Used
            Margin / Margin / Available) that crowded the mobile sheet. */}
        {(() => {
          const walletUsed = Number(walletSummary?.used_margin ?? 0);
          const walletAvail = Number(walletSummary?.available_balance ?? 0);
          const openUnrl = Number(
            (pnlSummary as any)?.open_unrealised ?? (pnlSummary as any)?.unrealized_pnl ?? 0,
          );
          // Equity = total wallet (available + locked) + live open P/L.
          const equity = walletUsed + walletAvail + openUnrl;
          // Carry-forward = overnight margin. Infoway (crypto/forex) has no
          // separate carry tier — the posted margin is held forever — so it
          // equals the intraday figure there.
          const carryFwd = isInfowaySeg ? intradayMargin : carryforwardMargin;
          return (
            <div className="mt-4 grid grid-cols-3 gap-2 px-4 text-[11px]">
              <MarginCard
                label="Available"
                value={formatINRCompact(availableMargin)}
                fullValue={`${formatINR(availableMargin)} free · Equity ${formatINR(equity)}${
                  openUnrl !== 0 ? ` (open P/L ${openUnrl >= 0 ? "+" : ""}${formatINR(openUnrl)})` : ""
                }`}
                accent={availableMargin >= intradayMargin ? "ok" : "low"}
              />
              <MarginCard
                label="Intraday"
                value={formatINRCompact(intradayMargin)}
                fullValue={`Intraday margin · ${formatINR(intradayMargin)}`}
              />
              <MarginCard
                label="Carry Fwd"
                value={formatINRCompact(carryFwd)}
                fullValue={`Carry-forward (overnight) margin · ${formatINR(carryFwd)}`}
              />
            </div>
          );
        })()}

        {/* ── Big BUY / SELL — sticky footer, ALWAYS reachable (even with
            SL/TP fields open; the body above scrolls under it) ──────── */}
        <div className="sticky bottom-0 z-20 mt-auto grid shrink-0 grid-cols-2 gap-2 border-t border-border bg-background px-4 pb-4 pt-3">
          {/* `loading` removed — submit is fire-and-forget now and the
              sheet closes immediately on tap, so no spinner state is
              ever visible. `disabled` keeps the 250 ms double-tap
              lockout in case the close animation is slow. */}
          <Button
            type="button"
            disabled={submitting !== null}
            onClick={() => submit("BUY")}
            className="flex h-14 flex-col items-center justify-center gap-0 rounded-lg bg-buy text-buy-foreground hover:bg-buy/90"
          >
            <span className="flex items-center gap-1 text-sm font-bold">
              <ArrowUpRight className="size-4" /> BUY
            </span>
            <span className="font-tabular text-xs tabular-nums opacity-90">
              {fmtPrice(buyPrice)}
            </span>
          </Button>
          <Button
            type="button"
            disabled={submitting !== null}
            onClick={() => submit("SELL")}
            className="flex h-14 flex-col items-center justify-center gap-0 rounded-lg bg-sell text-sell-foreground hover:bg-sell/90"
          >
            <span className="flex items-center gap-1 text-sm font-bold">
              <ArrowDownRight className="size-4" /> SELL
            </span>
            <span className="font-tabular text-xs tabular-nums opacity-90">
              {fmtPrice(sellPrice)}
            </span>
          </Button>
        </div>
      </DialogContent>
      {/* Option chain picker — only mounted for Indian rows. On pick we
          close the sheet AND navigate to terminal so the trader lands
          on the full chart + order panel for that strike, matching the
          Zerodha flow ("Tap a strike → terminal opens"). Keep this
          OUTSIDE DialogContent so the picker dialog can stack over it. */}
      {showOptionChain && (
        <OptionChainPicker
          open={optionChainOpen}
          onOpenChange={setOptionChainOpen}
          initialUnderlying={instrument?.symbol ?? null}
          onPick={(tok) => {
            // Guard against empty/falsy tokens — calling onSwap("") would
            // null-out the parent's sheetToken and the lazy-mount wrapper
            // would unmount the entire sheet, looking to the user like
            // "card hi nahi khula".
            if (!tok) return;
            if (onSwap) {
              // ORDER MATTERS — set the swap flag and update the
              // parent's token FIRST, dismiss the picker SECOND. This
              // way:
              //  • swappingRef stops the outer Dialog's onOpenChange
              //    from honouring the inner picker's close event,
              //  • parent's setTradeToken(newToken) runs in the same
              //    React batch, so the outer Dialog's `open` prop
              //    stays truthy across the commit (`open = !!token`),
              //  • setOptionChainOpen(false) tears down the picker
              //    after both of the above have already landed.
              // The 250 ms timeout covers React's commit phase plus
              // Radix's overlay dismiss animation — anything longer
              // and a deliberate user tap to close the sheet would
              // start failing.
              swappingRef.current = true;
              onSwap(String(tok));
              setOptionChainOpen(false);
              window.setTimeout(() => {
                swappingRef.current = false;
              }, 250);
              return;
            }
            // No onSwap → not a sheet-driven flow; close + navigate to
            // /terminal so the picker still does something useful on
            // pages that mount it without the swap callback.
            setOptionChainOpen(false);
            onClose();
            router.push(`/terminal?token=${encodeURIComponent(tok)}`);
          }}
        />
      )}
    </Dialog>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className="font-tabular text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function LotMeta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className="font-tabular text-base font-bold tabular-nums">{value}</div>
    </div>
  );
}

function ScriptInfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="font-tabular text-[11px] font-bold tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function MarginCard({
  label,
  value,
  fullValue,
  accent,
}: {
  label: string;
  value: string;
  fullValue?: string;
  accent?: "ok" | "low";
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-2 py-2">
      <div className="truncate text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        title={fullValue}
        className={cn(
          "truncate font-tabular text-[12px] font-bold tabular-nums",
          accent === "ok" && "text-buy",
          accent === "low" && "text-sell",
        )}
      >
        {value}
      </div>
    </div>
  );
}
