"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, ChevronRight } from "lucide-react";
import {
  PiBriefcaseFill,
  PiCaretRightBold,
  PiChartLineUpBold,
  PiCoinFill,
  PiDownloadSimpleBold,
  PiEyeBold,
  PiEyeSlashBold,
  PiGameControllerFill,
  PiSquaresFourFill,
  PiStarFill,
} from "react-icons/pi";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";
import { DashboardAPI, GamesAPI, OrderAPI, PositionAPI, WalletAPI, AccountsAPI, TickerAPI } from "@/lib/api";
import { WALLET_CODE, WALLET_LABEL, SEGMENT_KINDS, type WalletKind } from "@/lib/wallets";
import { cn, formatINR, formatPrice, pnlColor } from "@/lib/utils";
import { AddFundsWizard } from "@/components/wallet/AddFundsWizard";
import { Ticker } from "@/components/common/Ticker";
import { MarketOverview } from "@/components/trading/MarketOverview";

// Badge tone + plain-words label per wallet card.
const WALLET_TONE: Record<WalletKind, string> = {
  MAIN: "bg-slate-500/15 text-slate-600 dark:text-slate-300",
  NSE_BSE: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  MCX: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
  CRYPTO: "bg-violet-500/15 text-violet-600 dark:text-violet-400",
  FOREX: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
};
const WALLET_KIND_LABEL: Record<WalletKind, string> = {
  MAIN: "Cash",
  NSE_BSE: "Equity",
  MCX: "Commodity",
  CRYPTO: "Crypto",
  FOREX: "Forex",
};

/** The app's balance unit, drawn as a gold coin instead of the emoji. */
function Coin({ className }: { className?: string }) {
  return <PiCoinFill className={cn("shrink-0 text-amber-500 drop-shadow-sm", className)} aria-hidden />;
}

const money = (v: number | string | null | undefined) => formatINR(v, { withSymbol: false });

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const { data: summary } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => DashboardAPI.summary(),
    refetchInterval: 5000,
  });
  const { data: positions } = useQuery({
    queryKey: ["positions", "open"],
    queryFn: () => PositionAPI.open(),
    refetchInterval: 5000,
  });
  const { data: orders } = useQuery({
    queryKey: ["orders", "recent-dashboard"],
    queryFn: () => OrderAPI.list(),
  });
  // Today's P&L comes from the dedicated `/positions/pnl-summary` endpoint —
  // /dashboard/summary used to recompute it inline, but that path:
  //   1. only iterated currently-open positions, so trades CLOSED today were
  //      excluded from "Today's P&L";
  //   2. added each position's LIFETIME `realized_pnl` (not just today's),
  //      inflating the number with old realised slices; and
  //   3. didn't convert USD-quoted (crypto / forex / MCX) P&L to INR,
  //      reading ~83× too small for those users.
  // The pnl-summary endpoint already covers all three correctly and is the
  // same source the terminal's positions strip + PnlSummaryCards use, so the
  // dashboard, terminal and reports views now agree on a single number.
  const { data: pnlSummary } = useQuery({
    queryKey: ["positions", "pnl-summary"],
    queryFn: () => PositionAPI.pnlSummary(),
    refetchInterval: 5000,
  });

  // Announcement strip written by the super admin. Long stale time because a
  // ticker line is not a price - refetching it every few seconds would be
  // noise, and a new line reaching users a minute late is fine.
  const { data: ticker } = useQuery({
    queryKey: ["ticker"],
    queryFn: () => TickerAPI.mine(),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  // Multi-wallet accounts (Main + per-segment trading wallets).
  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => AccountsAPI.list(),
    refetchInterval: 8000,
  });

  // Add-funds wizard — same 4-step flow as the Wallet page, opened straight
  // from the home Deposit quick-action so users don't have to hop to /wallet.
  const qc = useQueryClient();
  const [depositOpen, setDepositOpen] = useState(false);
  const { data: companyBanks } = useQuery({
    queryKey: ["company-banks"],
    queryFn: () => WalletAPI.companyBanks(),
    staleTime: 5 * 60_000,
  });
  const defaultBank =
    companyBanks?.find((b: any) => b.is_default) ?? companyBanks?.[0];

  // Games promo — resolve the best win multiple across all enabled games so
  // the header CTA advertises a real, current number (shares the games
  // settings cache; cheap long-stale fetch, no polling here).
  const { data: gamesSettings } = useQuery({
    queryKey: ["games", "settings"],
    queryFn: () => GamesAPI.settings(),
    staleTime: 60_000,
  });
  const gamesMaxMult = (() => {
    const g = (gamesSettings as any)?.games || {};
    let m = 0;
    for (const k of Object.keys(g)) {
      const c = g[k];
      if (!c || c.enabled === false) continue;
      const wm = Number(c.win_multiplier || 0);
      if (wm > m) m = wm;
      const fp = Number(c.fixed_profit || 0);
      const tp = Number(c.ticket_price || 0);
      if (fp > 0 && tp > 0) m = Math.max(m, fp / tp);
    }
    return Math.min(Math.round(m), 100); // sane cap for the badge
  })();

  const wallet = summary?.wallet ?? {};
  // Prefer the canonical pnl-summary value; fall back to the dashboard
  // payload only while the dedicated query is still loading so we don't
  // flash 🪙0 on first paint.
  const todayPnl = Number(pnlSummary?.today_pnl ?? summary?.today_pnl ?? 0);

  const [hideBalance, setHideBalance] = useState(false);
  // Hour-based greeting, set after mount: the server renders in UTC and
  // would disagree with the phone's clock.
  const [greeting, setGreeting] = useState("Welcome back,");
  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(h < 12 ? "Good Morning," : h < 17 ? "Good Afternoon," : "Good Evening,");
  }, []);

  // Total across every wallet: balance + open P&L (`equity`).
  const totalValue = (accounts?.wallets ?? []).reduce(
    (sum: number, w: any) => sum + (Number(w.equity ?? w.available_balance) || 0),
    0,
  );
  const dayBase = totalValue - todayPnl;
  const todayPct = dayBase > 0 ? (todayPnl / dayBase) * 100 : 0;

  return (
    // Mobile: reorder so the wallets/accounts section sits right under the
    // greeting (the heavy portfolio hero + market overview drop below). At
    // sm+ everything resets to source order → desktop layout unchanged.
    <div className="flex flex-col gap-5">
      {/* Announcement strip. Renders nothing when there is nothing to say, so
          there is no empty bar left behind when every line is switched off. */}
      <Ticker messages={ticker?.messages ?? []} className="order-first sm:order-none" />
      {/* ── Greeting + Play & Win ───────────────────────────────── */}
      <header className="order-1 flex items-center justify-between gap-3 sm:order-none">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-muted-foreground">{greeting}</p>
          <h1 className="truncate text-[22px] font-extrabold tracking-tight md:text-3xl">
            {user?.full_name?.split(" ")[0] ?? "Trader"} <span aria-hidden>👋</span>
          </h1>
          <p className="mt-0.5 text-[11px] font-semibold text-muted-foreground">
            {user?.is_demo && (
              <span className="mr-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">DEMO</span>
            )}
            {user?.user_code}
          </p>
        </div>

        <Link
          href="/games"
          aria-label="Play games"
          className="group relative shrink-0 overflow-hidden rounded-2xl bg-gradient-to-br from-yellow-300 via-amber-400 to-amber-500 py-2 pl-2 pr-2.5 text-neutral-900 shadow-lg shadow-amber-500/30 transition-transform hover:-translate-y-0.5 active:scale-95"
        >
          <span aria-hidden className="pointer-events-none absolute -right-4 -top-6 size-16 rounded-full bg-white/30 blur-xl" />
          <div className="relative flex items-center gap-2">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-neutral-900 text-amber-300 shadow-inner">
              <PiGameControllerFill className="size-5" />
            </span>
            <div className="leading-tight">
              <div className="text-[9.5px] font-extrabold uppercase tracking-wider text-neutral-900/70">Play &amp; Win</div>
              <div className="text-[13px] font-extrabold tracking-tight">
                {gamesMaxMult >= 2 ? <>Up to {gamesMaxMult}x wins</> : "Games are live"}
              </div>
            </div>
            <PiCaretRightBold className="size-3.5 shrink-0 transition-transform group-hover:translate-x-0.5" />
          </div>
        </Link>
      </header>

      {/* ── Total portfolio value ─────────────────────────────────── */}
      <section className="relative order-2 overflow-hidden rounded-2xl border border-border bg-card p-4 shadow-sm sm:order-none">
        <span aria-hidden className="pointer-events-none absolute -right-12 -top-16 size-48 rounded-full bg-primary/15 blur-3xl" />
        <div className="relative flex items-center gap-2 text-[12px] font-bold text-muted-foreground">
          Total Portfolio Value
          <button
            type="button"
            onClick={() => setHideBalance((v) => !v)}
            aria-label={hideBalance ? "Show balances" : "Hide balances"}
            className="grid size-6 place-items-center rounded-full hover:bg-muted"
          >
            {hideBalance ? <PiEyeSlashBold className="size-4" /> : <PiEyeBold className="size-4" />}
          </button>
        </div>
        <div className="relative mt-1 flex items-center gap-2 font-tabular text-[28px] font-extrabold leading-none tracking-tight tabular-nums">
          <Coin className="size-7" />
          {hideBalance ? "••••••" : money(totalValue)}
        </div>
        <div className={cn("relative mt-2 text-[12px] font-bold tabular-nums", pnlColor(todayPnl))}>
          {hideBalance
            ? "••••"
            : `${todayPnl > 0 ? "+" : ""}${money(todayPnl)} (${todayPnl > 0 ? "+" : ""}${todayPct.toFixed(2)}%)`}
          <span className="ml-1 font-semibold text-muted-foreground">today</span>
        </div>
      </section>

      {/* ── Quick actions ─────────────────────────────────────── */}
      <section className="order-4 grid grid-cols-4 gap-2 sm:order-none sm:gap-3">
        <QuickAction
          onClick={() => setDepositOpen(true)}
          icon={PiDownloadSimpleBold}
          label="Deposit"
          tone="from-emerald-400 to-emerald-600 text-white shadow-emerald-500/30 dark:from-yellow-300 dark:to-amber-500 dark:text-neutral-900 dark:shadow-amber-500/30"
        />
        <QuickAction
          href="/option-chain"
          icon={PiSquaresFourFill}
          label="Options"
          tone="from-sky-400 to-blue-600 text-white shadow-blue-500/30"
        />
        <QuickAction
          href="/positions"
          icon={PiBriefcaseFill}
          label="Position"
          tone="from-indigo-400 to-blue-700 text-white shadow-indigo-500/30"
        />
        <QuickAction
          href="/marketwatch"
          icon={PiChartLineUpBold}
          label="Market"
          tone="from-orange-300 to-orange-500 text-white shadow-orange-500/30 dark:from-yellow-300 dark:to-amber-500 dark:text-neutral-900 dark:shadow-amber-500/30"
        />
      </section>

      {/* ── My wallets (multi-wallet) — always shows all wallets ──── */}
      <section className="order-3 sm:order-none">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[15px] font-extrabold tracking-tight">My Wallets</h3>
          <Link href="/accounts" className="inline-flex items-center gap-0.5 text-xs font-bold text-primary hover:underline">
            Manage <PiCaretRightBold className="size-3" />
          </Link>
        </div>
        <div className="-mx-4 flex snap-x scroll-px-4 gap-2.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 lg:grid-cols-5 [&::-webkit-scrollbar]:hidden">
          {(() => {
            const map = new Map((accounts?.wallets || []).map((w: any) => [w.kind, w]));
            return (["MAIN", ...SEGMENT_KINDS] as WalletKind[]).map(
              (k) => map.get(k) || { kind: k, available_balance: "0", used_margin: "0" },
            );
          })().map((w: any) => {
            const kind = w.kind as WalletKind;
            const isMain = kind === "MAIN";
            const isPrimary = (accounts?.primary_wallet_kind || "NSE_BSE") === kind;
            const Wrapper: any = isMain ? "div" : Link;
            return (
              <Wrapper
                key={kind}
                {...(isMain ? {} : { href: "/accounts" })}
                className={cn(
                  "min-w-[128px] shrink-0 snap-start rounded-2xl border bg-card p-3 shadow-sm transition-all sm:min-w-0",
                  isPrimary && !isMain
                    ? "border-primary/60 ring-1 ring-inset ring-primary/25"
                    : "border-border hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md",
                )}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className={cn("rounded-md px-1.5 py-0.5 text-[10px] font-extrabold uppercase tracking-wider", WALLET_TONE[kind])}>
                    {WALLET_CODE[kind]}
                  </span>
                  {isPrimary && !isMain && <PiStarFill className="size-3.5 text-primary" aria-label="Primary wallet" />}
                </div>
                <div className="mt-1.5 text-[11px] font-semibold text-muted-foreground">{WALLET_KIND_LABEL[kind] ?? WALLET_LABEL[kind]}</div>
                <div className="mt-0.5 flex items-center gap-1.5 font-tabular text-[15px] font-extrabold tabular-nums">
                  <Coin className="size-4" />
                  {hideBalance ? "••••" : money(w.available_balance)}
                </div>
                {!isMain && Number(w.used_margin) > 0 && (
                  <div className="text-[10px] font-semibold tabular-nums text-sell">Used {money(w.used_margin)}</div>
                )}
              </Wrapper>
            );
          })}
        </div>
      </section>

      {/* Add-funds 4-step wizard — same flow as the Wallet page. */}
      <AddFundsWizard
        open={depositOpen}
        onClose={() => setDepositOpen(false)}
        companyBanks={(companyBanks as any[]) ?? []}
        payeeName={defaultBank?.account_holder}
        onSuccess={() => {
          qc.invalidateQueries({ queryKey: ["dashboard"] });
          qc.invalidateQueries({ queryKey: ["my-deposits"] });
          qc.invalidateQueries({ queryKey: ["wallet-summary"] });
          qc.invalidateQueries({ queryKey: ["wallet-txns"] });
        }}
      />

      {/* ── Mobile: live market overview (replaces the stat tiles) ──
          Phones get a live, color-coded market snapshot in place of the
          three small stat tiles — same data plumbing as the terminal's
          instruments panel, ticking via the marketdata WS. */}
      <MarketOverview className="order-5 sm:hidden" />

      {/* ── Stat tiles row — desktop only (sm+). Hidden on mobile where
          the MarketOverview above takes their place. ────────────────── */}
      <section className="hidden gap-3 sm:grid sm:grid-cols-3">
        <StatTile label="Open positions" value={String(summary?.open_positions ?? 0)} hint="live MTM" />
        <StatTile label="Pending orders" value={String(summary?.pending_orders ?? 0)} hint="awaiting fill" />
        <StatTile
          label="Today's P&L"
          value={hideBalance ? "•••" : formatINR(todayPnl)}
          tone={pnlColor(todayPnl)}
        />
      </section>

      {/* ── Open positions + Recent orders — desktop only (lg+).
          Hidden on mobile where the live MarketOverview above is the
          primary focus; the full positions/orders live on their own
          bottom-nav tabs. ──────────────────────────────────────────── */}
      <section className="hidden gap-4 lg:grid lg:grid-cols-3">
        <PanelCard
          className="lg:col-span-2"
          title="Open positions"
          subtitle="Live mark-to-market"
          action={{ label: "View all", href: "/positions" }}
        >
          {positions?.length ? (
            <ul className="divide-y divide-border">
              {positions.slice(0, 6).map((p: any) => {
                const isUp = Number(p.unrealized_pnl) >= 0;
                return (
                  <li key={p.id}>
                    <Link
                      href="/positions"
                      className="flex items-center justify-between gap-3 py-2.5 transition-colors hover:bg-muted/30"
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className={cn(
                            "grid size-9 place-items-center rounded-full text-xs font-bold uppercase",
                            isUp ? "bg-buy/15 text-buy" : "bg-sell/15 text-sell"
                          )}
                        >
                          {p.symbol?.slice(0, 2)}
                        </div>
                        <div>
                          <div className="text-sm font-medium">{p.symbol}</div>
                          <div className="text-[11px] text-muted-foreground">
                            {p.product_type} · {p.quantity} @ {formatPrice(p.avg_price, p.segment_type, p.exchange)}
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className={cn("font-tabular text-sm font-semibold", pnlColor(p.unrealized_pnl))}>
                          {formatINR(p.unrealized_pnl)}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          LTP {formatPrice(p.ltp, p.segment_type, p.exchange)}
                        </div>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState message="No open positions" cta={{ label: "Open a trade", href: "/terminal" }} />
          )}
        </PanelCard>

        <PanelCard
          title="Recent orders"
          subtitle="Last 6 placed"
          action={{ label: "All", href: "/positions" }}
        >
          {orders?.length ? (
            <ul className="divide-y divide-border">
              {orders.slice(0, 6).map((o: any) => {
                const isBuy = String(o.action).toUpperCase() === "BUY";
                return (
                  <li key={o.id}>
                    <Link
                      href="/positions"
                      className="flex items-center justify-between py-2 text-xs transition-colors hover:bg-muted/30"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "inline-flex w-12 justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold",
                            isBuy ? "bg-buy/15 text-buy" : "bg-sell/15 text-sell"
                          )}
                        >
                          {isBuy ? "BUY" : "SELL"}
                        </span>
                        <span className="font-medium">{o.symbol}</span>
                        <span className="text-muted-foreground">×{o.quantity}</span>
                      </div>
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-semibold",
                          o.status === "EXECUTED"
                            ? "bg-buy/15 text-buy"
                            : o.status === "REJECTED" || o.status === "CANCELLED"
                              ? "bg-muted text-muted-foreground"
                              : "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                        )}
                      >
                        {o.status}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState message="No orders yet" cta={{ label: "Place an order", href: "/terminal" }} />
          )}
        </PanelCard>
      </section>
    </div>
  );
}

function QuickAction({
  href,
  onClick,
  icon: Icon,
  label,
  tone,
}: {
  href?: string;
  onClick?: () => void;
  icon: any;
  label: string;
  /** Gradient + icon colour classes for the round badge. */
  tone: string;
}) {
  const cls = cn(
    "flex flex-col items-center justify-center gap-1.5 rounded-2xl border border-border bg-card px-1 py-3 text-[11.5px] font-bold shadow-sm transition-all",
    "hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md active:scale-95",
  );
  const inner = (
    <>
      <span className={cn("grid size-11 place-items-center rounded-full bg-gradient-to-b shadow-md", tone)}>
        <Icon className="size-[22px]" />
      </span>
      <span>{label}</span>
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={cls}>
        {inner}
      </button>
    );
  }
  return (
    <Link href={href ?? "#"} className={cls}>
      {inner}
    </Link>
  );
}

function StatTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn("mt-1 font-tabular text-lg font-semibold", tone)}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

function PanelCard({
  title,
  subtitle,
  action,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-4", className)}>
      <div className="mb-3 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="text-[11px] text-muted-foreground">{subtitle}</p>}
        </div>
        {action && (
          <Link
            href={action.href}
            className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline"
          >
            {action.label} <ChevronRight className="size-3" />
          </Link>
        )}
      </div>
      {children}
    </div>
  );
}

function EmptyState({ message, cta }: { message: string; cta?: { label: string; href: string } }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <div className="text-sm text-muted-foreground">{message}</div>
      {cta && (
        <Button asChild variant="outline" size="sm">
          <Link href={cta.href}>
            <ArrowUpRight className="size-3.5" /> {cta.label}
          </Link>
        </Button>
      )}
    </div>
  );
}
