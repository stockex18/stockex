"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Briefcase,
  ChevronRight,
  Gamepad2,
  LineChart,
  Sparkles,
  Star,
  Table2,
  Wallet,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";
import { DashboardAPI, GamesAPI, OrderAPI, PositionAPI, WalletAPI, AccountsAPI } from "@/lib/api";
import { WALLET_CODE, WALLET_LABEL, SEGMENT_KINDS, type WalletKind } from "@/lib/wallets";
import { cn, formatINR, formatPrice, pnlColor } from "@/lib/utils";
import { AddFundsWizard } from "@/components/wallet/AddFundsWizard";
import { MarketOverview } from "@/components/trading/MarketOverview";
import { TopMovers } from "@/components/trading/TopMovers";

// Distinct accent per wallet card (MAIN first, then each trading segment).
const WALLET_TONE = [
  "bg-slate-500/15 text-slate-600 dark:text-slate-300",
  "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  "bg-teal-500/15 text-teal-600 dark:text-teal-400",
  "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400",
  "bg-zinc-500/15 text-zinc-600 dark:text-zinc-300",
];

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

  const [hideBalance] = useState(false);

  return (
    // Mobile: reorder so the wallets/accounts section sits right under the
    // greeting (the heavy portfolio hero + market overview drop below). At
    // sm+ everything resets to source order → desktop layout unchanged.
    <div className="flex flex-col gap-5">
      {/* ── Greeting ─────────────────────────────────────────────── */}
      <header className="order-1 flex items-center justify-between sm:order-none">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Welcome back</p>
          <h1 className="text-xl font-semibold tracking-tight md:text-2xl">
            {user?.full_name?.split(" ")[0] ?? "Trader"} 👋
          </h1>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {user?.is_demo && <span className="mr-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">DEMO</span>}
            {user?.user_code}
          </p>
        </div>

        {/* Games CTA — fills the header's right space with a bold, colorful
            promo that advertises the live max win multiple. */}
        <Link
          href="/games"
          aria-label="Play games"
          className="group relative shrink-0 overflow-hidden rounded-2xl bg-gradient-to-br from-emerald-600 via-green-500 to-teal-500 px-3 py-2 text-white shadow-lg shadow-emerald-600/30 transition-transform hover:-translate-y-0.5 active:scale-95"
        >
          <span aria-hidden className="pointer-events-none absolute -right-3 -top-4 size-14 rounded-full bg-white/15 blur-xl" />
          <div className="relative flex items-center gap-2">
            <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-white/20 ring-1 ring-inset ring-white/25">
              <Gamepad2 className="size-5" strokeWidth={2.4} />
            </span>
            <div className="leading-tight">
              <div className="flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-white/85">
                <Sparkles className="size-2.5" /> Play & win
              </div>
              <div className="text-sm font-extrabold tracking-tight">
                {gamesMaxMult >= 2 ? <>Up to {gamesMaxMult}× wins</> : "Games are live"}
              </div>
            </div>
            <ChevronRight className="size-4 shrink-0 text-white/80 transition-transform group-hover:translate-x-0.5" />
          </div>
        </Link>
      </header>

      {/* ── Quick actions ─────────────────────────────────────── */}
      <section className="order-4 grid grid-cols-4 gap-2 sm:order-none sm:gap-3">
        <QuickAction
          onClick={() => setDepositOpen(true)}
          icon={ArrowDownToLine}
          label="Deposit"
          tone={{ bg: "bg-emerald-500/15", fg: "text-emerald-600 dark:text-emerald-400", border: "border-emerald-500/30 hover:border-emerald-500/60" }}
        />
        <QuickAction
          href="/option-chain"
          icon={Table2}
          label="Options"
          tone={{ bg: "bg-slate-500/15", fg: "text-slate-600 dark:text-slate-300", border: "border-slate-500/30 hover:border-slate-500/60" }}
        />
        <QuickAction
          href="/positions"
          icon={Briefcase}
          label="Position"
          tone={{ bg: "bg-blue-500/15", fg: "text-blue-600 dark:text-blue-400", border: "border-blue-500/30 hover:border-blue-500/60" }}
        />
        <QuickAction
          href="/marketwatch"
          icon={LineChart}
          label="Market"
          tone={{ bg: "bg-amber-500/15", fg: "text-amber-600 dark:text-amber-400", border: "border-amber-500/30 hover:border-amber-500/60" }}
        />
      </section>

      {/* ── My wallets (multi-wallet) — always shows all wallets ──── */}
      <section className="order-2 sm:order-none">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-bold uppercase tracking-wide text-muted-foreground">My wallets</h3>
          <Link href="/accounts" className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
            Manage <ChevronRight className="size-3.5" />
          </Link>
        </div>
        <div className="-mx-1 flex snap-x gap-2.5 overflow-x-auto px-1 pb-1 sm:grid sm:grid-cols-3 sm:overflow-visible lg:grid-cols-5">
          {(() => {
            const map = new Map((accounts?.wallets || []).map((w: any) => [w.kind, w]));
            return (["MAIN", ...SEGMENT_KINDS] as WalletKind[]).map(
              (k) => map.get(k) || { kind: k, available_balance: "0", used_margin: "0" },
            );
          })().map((w: any, wi: number) => {
            const kind = w.kind as WalletKind;
            const isMain = kind === "MAIN";
            const isPrimary = (accounts?.primary_wallet_kind || "NSE_BSE") === kind;
            const Wrapper: any = isMain ? "div" : Link;
            const badgeTone = WALLET_TONE[wi % WALLET_TONE.length];
            return (
              <Wrapper
                key={kind}
                {...(isMain ? {} : { href: "/accounts" })}
                className={cn(
                  "min-w-[150px] shrink-0 snap-start rounded-2xl border p-3 shadow-sm transition-all sm:min-w-0",
                  isPrimary
                    ? "border-primary/50 bg-primary/5 ring-1 ring-inset ring-primary/20"
                    : "border-border bg-card hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className={cn("rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", badgeTone)}>
                    {WALLET_CODE[kind]}
                  </span>
                  {isPrimary && !isMain && (
                    <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-primary">
                      <Star className="size-3 fill-primary" /> Primary
                    </span>
                  )}
                </div>
                <div className="mt-2 text-[11px] font-medium text-muted-foreground">{WALLET_LABEL[kind]}{isMain ? " (cash)" : ""}</div>
                <div className="text-lg font-bold tabular-nums">
                  {hideBalance ? "••••" : formatINR(w.available_balance)}
                </div>
                {!isMain && Number(w.used_margin) > 0 && (
                  <div className="text-[10px] font-medium tabular-nums text-sell">Used {formatINR(w.used_margin)}</div>
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

      {/* Mobile: live top gainers & losers from a NIFTY large-cap basket. */}
      <TopMovers className="order-6 sm:hidden" />

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

/** Per-action accent palette — each quick action gets its own bold color. */
type QaTone = { bg: string; fg: string; border: string };

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
  tone: QaTone;
}) {
  const cls = cn(
    "flex flex-col items-center justify-center gap-1.5 rounded-2xl border bg-card p-3 text-[11px] font-bold transition-all",
    "hover:-translate-y-0.5 hover:shadow-md active:scale-95",
    tone.border,
  );
  const inner = (
    <>
      <div className={cn("grid size-11 place-items-center rounded-full", tone.bg, tone.fg)}>
        <Icon className="size-5" strokeWidth={2.5} />
      </div>
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
