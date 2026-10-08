"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { IconType } from "react-icons";
import {
  PiArrowRightBold,
  PiArrowsLeftRightBold,
  PiCaretRightBold,
  PiChartBarFill,
  PiChartLineUpBold,
  PiCoinFill,
  PiCurrencyBtcBold,
  PiDropFill,
  PiEyeBold,
  PiEyeSlashBold,
  PiGameControllerFill,
  PiGlobeHemisphereWestFill,
  PiPlusBold,
  PiStar,
  PiStarFill,
  PiUploadSimpleBold,
  PiWalletFill,
} from "react-icons/pi";
import { cn, formatINR } from "@/lib/utils";
import { isDesktopWeb } from "@/lib/platform";
import { AccountsAPI, GamesAPI } from "@/lib/api";
import { WALLET_CODE, WALLET_LABEL, SEGMENT_KINDS, type WalletKind } from "@/lib/wallets";
import { TransferDialog } from "@/components/accounts/TransferDialog";
import { TransferDialog as GamesTransferDialog } from "@/components/games/TransferDialog";

// Per trading wallet: what it trades, its icon and its colour family.
const META: Record<
  Exclude<WalletKind, "MAIN">,
  { icon: IconType; sub: string; card: string; badge: string; iconBg: string; accent: string }
> = {
  NSE_BSE: {
    icon: PiChartBarFill,
    sub: "Equity, F&O, Currency",
    card: "border-emerald-500/25 from-emerald-500/[0.08] dark:from-emerald-500/[0.14]",
    badge: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
    iconBg: "from-emerald-400 to-emerald-600 shadow-emerald-500/30",
    accent: "text-emerald-500",
  },
  MCX: {
    icon: PiDropFill,
    sub: "Gold, Silver, Crude & more",
    card: "border-orange-500/25 from-orange-500/[0.08] dark:from-orange-500/[0.14]",
    badge: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
    iconBg: "from-orange-400 to-red-500 shadow-orange-500/30",
    accent: "text-orange-500",
  },
  CRYPTO: {
    icon: PiCurrencyBtcBold,
    sub: "BTC, ETH, USDT & more",
    card: "border-violet-500/25 from-violet-500/[0.08] dark:from-violet-500/[0.16]",
    badge: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
    iconBg: "from-violet-400 to-indigo-600 shadow-violet-500/30",
    accent: "text-violet-500",
  },
  FOREX: {
    icon: PiGlobeHemisphereWestFill,
    sub: "EUR/USD, GBP/USD & more",
    card: "border-sky-500/25 from-sky-500/[0.08] dark:from-sky-500/[0.14]",
    badge: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
    iconBg: "from-sky-400 to-blue-600 shadow-sky-500/30",
    accent: "text-sky-500",
  },
};

const money = (v: number | string | null | undefined) => formatINR(v, { withSymbol: false });

function Coin({ className }: { className?: string }) {
  return <PiCoinFill className={cn("shrink-0 text-amber-500 drop-shadow-sm", className)} aria-hidden />;
}

/** A few rising candles — decoration in the wallet's colour, not data. */
function Candles({ className }: { className?: string }) {
  const bars: [number, number, number, number, number][] = [
    // x, wick top, wick bottom, body top, body height
    [3, 19, 34, 23, 8],
    [15, 14, 31, 18, 9],
    [27, 17, 29, 20, 6],
    [39, 7, 25, 11, 11],
    [51, 1, 20, 5, 11],
  ];
  return (
    <svg viewBox="0 0 60 36" className={cn("h-9 w-[60px] shrink-0 opacity-80", className)} aria-hidden>
      {bars.map(([x, t, b, y, h]) => (
        <g key={x} fill="currentColor" stroke="currentColor">
          <line x1={x + 3} x2={x + 3} y1={t} y2={b} strokeWidth={1.2} />
          <rect x={x} y={y} width={6} height={h} rx={1} strokeWidth={0} />
        </g>
      ))}
    </svg>
  );
}

const btn =
  "inline-flex h-10 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl px-2 text-[12px] font-extrabold transition-transform active:scale-95 disabled:opacity-60";
const goldBtn = cn(btn, "bg-gradient-to-b from-yellow-300 to-amber-500 text-neutral-900 shadow-md shadow-amber-500/25");
const outlineBtn = cn(btn, "border border-border bg-card text-foreground hover:border-primary/50");

export default function AccountsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferFrom, setTransferFrom] = useState<WalletKind>("MAIN");
  const [transferTo, setTransferTo] = useState<WalletKind>("NSE_BSE");
  const [gamesTxIn, setGamesTxIn] = useState(false);
  const [gamesTxOut, setGamesTxOut] = useState(false);
  const [hide, setHide] = useState(false);

  const { data } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => AccountsAPI.list(),
    refetchInterval: 5000,
  });
  // Games wallet is a separate system (GamesAPI) — surfaced here as an account
  // so the user can fund it / see its balance from one place.
  const { data: gamesWallet } = useQuery({
    queryKey: ["games", "wallet"],
    queryFn: () => GamesAPI.wallet(),
    refetchInterval: 5000,
  });

  const setPrimary = useMutation({
    mutationFn: (kind: string) => AccountsAPI.setPrimary(kind),
    onSuccess: (_r, kind) => {
      toast.success(`${WALLET_LABEL[kind as WalletKind]} is now your primary account`);
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (e: any) => toast.error(e?.message || "Failed"),
  });

  // Always show ALL wallets (Main + the 4 trading wallets) even before the
  // API has created/returned them — merge API balances over the known set.
  const walletMap = new Map<string, any>((data?.wallets || []).map((w: any) => [w.kind, w]));
  const primary: string = data?.primary_wallet_kind || "NSE_BSE";
  const main = walletMap.get("MAIN") || { kind: "MAIN", available_balance: "0" };
  const segs = SEGMENT_KINDS.map(
    (k) => walletMap.get(k) || { kind: k, available_balance: "0", used_margin: "0", profit_blocked: false },
  );

  const openTransfer = (from: WalletKind, to?: WalletKind) => {
    setTransferFrom(from);
    setTransferTo(to ?? (from === "MAIN" ? "NSE_BSE" : "MAIN"));
    setTransferOpen(true);
  };

  const trade = (kind: WalletKind) => {
    if (primary !== kind) setPrimary.mutate(kind);
    // Surface-aware routing (user request):
    //  • Desktop WEB → the full Trading Terminal (its layout is desktop-first).
    //  • Mobile APP webview / phone → the Market (watchlist) page, the
    //    mobile-friendly trade flow.
    const w = encodeURIComponent(kind);
    router.push(isDesktopWeb() ? `/terminal?wallet=${w}` : `/marketwatch?wallet=${w}`);
  };

  return (
    <div className="mx-auto w-full max-w-screen-lg space-y-5">
      <header className="flex items-center gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-primary/15 text-primary">
          <PiWalletFill className="size-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-xl font-extrabold tracking-tight">My Accounts</h1>
          <p className="text-[12px] font-semibold text-muted-foreground">Manage your trading wallets and funds</p>
        </div>
      </header>

      {/* ── Main (cash) wallet ─────────────────────────────────────────── */}
      <section className="relative overflow-hidden rounded-3xl border border-primary/40 bg-gradient-to-br from-amber-100/70 via-card to-card p-5 shadow-sm dark:from-amber-500/20 dark:via-card dark:to-card">
        <span aria-hidden className="pointer-events-none absolute -right-10 -top-10 size-48 rounded-full bg-primary/25 blur-3xl" />
        {/* The coin art sits on a white square; a round frame crops it to the coin. */}
        <span
          aria-hidden
          className="pointer-events-none absolute -right-2 top-5 size-24 rotate-12 overflow-hidden rounded-full shadow-xl shadow-amber-500/30 sm:size-28"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/app_new_icon.png" alt="" className="size-full scale-[1.08] object-cover" />
        </span>
        <div className="relative">
          <div className="flex items-center gap-2 text-[14px] font-extrabold">
            Main Wallet (Cash)
            <button
              type="button"
              onClick={() => setHide((v) => !v)}
              aria-label={hide ? "Show balance" : "Hide balance"}
              className="grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-muted"
            >
              {hide ? <PiEyeSlashBold className="size-4" /> : <PiEyeBold className="size-4" />}
            </button>
          </div>
          <div className="mt-1 flex items-center gap-2 pr-20 font-tabular text-[30px] font-extrabold leading-tight tabular-nums">
            <Coin className="size-7" />
            {hide ? "••••••" : money(main?.available_balance ?? 0)}
          </div>
          <p className="mt-1 max-w-[230px] text-[12px] font-semibold text-muted-foreground">
            Deposit funds to trade, withdraw, or move to other wallets.
          </p>
          <div className="mt-4 grid max-w-sm grid-cols-2 gap-2.5">
            <Link href="/wallet?action=deposit" className={goldBtn}>
              <PiPlusBold className="size-4" /> Add Funds
            </Link>
            <Link href="/wallet?action=withdraw" className={outlineBtn}>
              <PiUploadSimpleBold className="size-4" /> Withdraw
            </Link>
          </div>
        </div>
      </section>

      {/* ── Trading wallets ────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-2.5 text-[16px] font-extrabold tracking-tight">Trading Wallets</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {segs.map((w) => {
            const kind = w.kind as Exclude<WalletKind, "MAIN">;
            const m = META[kind];
            const Icon = m.icon;
            const isPrimary = primary === kind;
            return (
              <article
                key={kind}
                className={cn(
                  "relative overflow-hidden rounded-2xl border bg-gradient-to-br via-card to-card p-4 shadow-sm",
                  m.card,
                  isPrimary && "ring-1 ring-primary/50",
                )}
              >
                <button type="button" onClick={() => trade(kind)} className="flex w-full items-start gap-3 text-left">
                  <span className={cn("grid size-11 shrink-0 place-items-center rounded-full bg-gradient-to-br text-white shadow-md", m.iconBg)}>
                    <Icon className="size-6" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={cn("rounded-md px-1.5 py-0.5 text-[10px] font-extrabold uppercase tracking-wider", m.badge)}>
                        {WALLET_CODE[kind]}
                      </span>
                      {isPrimary && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] font-extrabold text-primary">
                          <PiStarFill className="size-3" /> Primary
                        </span>
                      )}
                      {w.profit_blocked && <span className="text-[10px] font-extrabold text-sell">Blocked</span>}
                    </div>
                    <div className="mt-1 truncate text-[16px] font-extrabold tracking-tight">{WALLET_LABEL[kind]}</div>
                    <div className="truncate text-[11px] font-semibold text-muted-foreground">{m.sub}</div>
                  </div>
                  <Candles className={m.accent} />
                  <PiCaretRightBold className={cn("mt-3 size-4 shrink-0", m.accent)} />
                </button>

                <div className="mt-3 grid grid-cols-2 divide-x divide-border">
                  <div className="pr-3">
                    <div className="text-[11px] font-semibold text-muted-foreground">Balance</div>
                    <div className="mt-0.5 flex items-center gap-1.5 font-tabular text-[17px] font-extrabold tabular-nums">
                      <Coin className="size-4" />
                      {hide ? "••••" : money(w.available_balance)}
                    </div>
                  </div>
                  <div className="pl-4">
                    <div className="text-[11px] font-semibold text-muted-foreground">Used Margin</div>
                    <div className="mt-0.5 flex items-center gap-1.5 font-tabular text-[17px] font-extrabold tabular-nums">
                      <Coin className="size-4" />
                      {hide ? "••••" : money(w.used_margin)}
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-[1.3fr_1.1fr_0.8fr] gap-2">
                  <button type="button" onClick={() => trade(kind)} className={goldBtn}>
                    <PiChartLineUpBold className="size-4" /> Trade Now <PiArrowRightBold className="size-3" />
                  </button>
                  <button
                    type="button"
                    disabled={isPrimary || setPrimary.isPending}
                    onClick={() => setPrimary.mutate(kind)}
                    className={outlineBtn}
                  >
                    {isPrimary ? <PiStarFill className="size-4 text-primary" /> : <PiStar className="size-4 text-primary" />}
                    {isPrimary ? "Primary" : "Set Primary"}
                  </button>
                  <button type="button" onClick={() => openTransfer("MAIN", kind)} className={outlineBtn}>
                    <PiArrowsLeftRightBold className="size-4" /> Move
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      {/* ── Games wallet — separate system, funded from Main ───────────── */}
      <section>
        <h2 className="mb-2.5 text-[16px] font-extrabold tracking-tight">Games Wallet</h2>
        <article className="relative overflow-hidden rounded-2xl border border-primary/30 bg-gradient-to-br from-primary/[0.08] via-card to-card p-4 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="grid size-11 shrink-0 place-items-center rounded-full bg-gradient-to-br from-yellow-300 to-amber-500 text-neutral-900 shadow-md shadow-amber-500/30">
              <PiGameControllerFill className="size-6" />
            </span>
            <div className="min-w-0 flex-1">
              <span className="rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] font-extrabold uppercase tracking-wider text-primary">GAMES</span>
              <div className="mt-1 text-[16px] font-extrabold tracking-tight">Games</div>
              <div className="text-[11px] font-semibold text-muted-foreground">Play market games &amp; win coins</div>
            </div>
          </div>
          <div className="mt-3">
            <div className="text-[11px] font-semibold text-muted-foreground">Balance</div>
            <div className="mt-0.5 flex items-center gap-1.5 font-tabular text-[20px] font-extrabold tabular-nums text-primary">
              <Coin className="size-5" />
              {hide ? "••••" : money(gamesWallet?.balance ?? 0)}
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <button type="button" onClick={() => router.push("/games")} className={goldBtn}>
              <PiGameControllerFill className="size-4" /> Play
            </button>
            <button type="button" onClick={() => setGamesTxIn(true)} className={outlineBtn}>
              <PiPlusBold className="size-4" /> Add Coins
            </button>
            <button type="button" onClick={() => setGamesTxOut(true)} className={outlineBtn}>
              <PiArrowsLeftRightBold className="size-4" /> To Main
            </button>
          </div>
        </article>
      </section>

      <p className="flex items-start gap-1.5 text-xs font-semibold text-muted-foreground">
        <PiStarFill className="mt-0.5 size-3.5 shrink-0 text-primary" />
        <span>
          Your <b className="text-foreground">primary</b> wallet decides which market &amp; instruments you trade. Default: NSE / BSE.
        </span>
      </p>

      <TransferDialog open={transferOpen} onOpenChange={setTransferOpen} defaultFrom={transferFrom} defaultTo={transferTo} />
      <GamesTransferDialog open={gamesTxIn} onOpenChange={setGamesTxIn} direction="in" />
      <GamesTransferDialog open={gamesTxOut} onOpenChange={setGamesTxOut} direction="out" />
    </div>
  );
}
