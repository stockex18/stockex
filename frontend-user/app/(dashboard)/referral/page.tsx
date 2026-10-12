"use client";

import { Suspense, useEffect, useState } from "react";
import { PageTourAuto } from "@/components/tour/PageTourAuto";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, Check, Gift, Users, UserCheck, Coins, Share2, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ReferralAPI } from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";

export default function ReferralPage() {
  const [copied, setCopied] = useState<"code" | "link" | null>(null);

  const { data } = useQuery({
    queryKey: ["referral", "stats"],
    queryFn: () => ReferralAPI.stats(),
    refetchInterval: 15000,
  });
  const { data: earnings } = useQuery({
    queryKey: ["referral", "earnings"],
    queryFn: () => ReferralAPI.earnings(100),
  });

  const code: string = data?.code || "—";
  const referrals: any[] = data?.referrals || [];

  // The backend's `share_link` is a RELATIVE path (`/register?ref=CODE`) — pasted
  // into WhatsApp/SMS it isn't a clickable link (looks like a bare code). Build
  // the ABSOLUTE URL from the current origin so "Copy link" / Share give a full
  // https://…/register?ref=CODE that opens the signup page directly.
  const [origin, setOrigin] = useState("");
  useEffect(() => {
    if (typeof window !== "undefined") setOrigin(window.location.origin);
  }, []);
  const relPath: string =
    data?.share_link || (code && code !== "—" ? `/register?ref=${code}` : "");
  const link: string = relPath
    ? relPath.startsWith("http")
      ? relPath
      : `${origin}${relPath.startsWith("/") ? "" : "/"}${relPath}`
    : "";

  function copy(kind: "code" | "link", text: string) {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(kind);
      toast.success(kind === "code" ? "Code copied" : "Link copied");
      setTimeout(() => setCopied(null), 1500);
    });
  }

  // Native share sheet on mobile; falls back to copying the link on desktop.
  function share() {
    if (typeof navigator !== "undefined" && (navigator as any).share) {
      (navigator as any)
        .share({
          title: "Join me on StockEx",
          text: `Use my referral code ${code} to sign up on StockEx.`,
          url: link,
        })
        .catch(() => {});
    } else {
      copy("link", link);
    }
  }

  const recentEarnings = (earnings || []).slice(0, 20);

  return (
    <div className="mx-auto w-full max-w-screen-lg space-y-5 p-3 pb-24 sm:p-6 md:pb-6">
      <Suspense fallback={null}>
        <PageTourAuto id="referral" />
      </Suspense>
      {/* Title */}
      <div className="flex items-center gap-2">
        <span className="grid size-9 place-items-center rounded-xl bg-primary/10 text-primary">
          <Gift className="size-5" />
        </span>
        <h1 className="text-lg font-bold tracking-tight">Refer &amp; Earn</h1>
      </div>

      {/* Share hero */}
      <Card className="overflow-hidden border-primary/30">
        <CardContent className="relative space-y-5 p-5 sm:p-6">
          <span
            aria-hidden
            className="pointer-events-none absolute -right-12 -top-12 size-48 rounded-full bg-primary/10 blur-3xl"
          />
          <span
            aria-hidden
            className="pointer-events-none absolute -bottom-16 -left-10 size-40 rounded-full bg-primary/5 blur-3xl"
          />

          <div data-tour="rf-code" className="relative">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Your referral code
            </div>
            <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <span className="inline-flex w-full items-center justify-center rounded-lg border border-primary/40 bg-primary/5 px-4 py-3 text-3xl font-bold tracking-[0.3em] text-primary sm:w-auto sm:justify-start sm:text-4xl">
                {code}
              </span>
            </div>
          </div>

          {/* Action row — copy code / copy link / native share */}
          <div data-tour="rf-actions" className="relative grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Button variant="outline" onClick={() => copy("code", code)}>
              {copied === "code" ? <Check className="size-4" /> : <Copy className="size-4" />}
              Copy code
            </Button>
            <Button variant="outline" onClick={() => copy("link", link)}>
              {copied === "link" ? <Check className="size-4" /> : <Copy className="size-4" />}
              Copy link
            </Button>
            <Button onClick={share}>
              <Share2 className="size-4" />
              Share
            </Button>
          </div>

          {/* Shareable link preview */}
          <div className="relative flex items-center gap-2 rounded-md border border-border/60 bg-muted/40 px-3 py-2">
            <Share2 className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {link || "Your invite link will appear here"}
            </span>
          </div>

          <p className="relative text-xs leading-relaxed text-muted-foreground">
            Share your code. When a friend signs up with it and starts playing / trading, you earn a
            reward — automatically credited to your wallet.
          </p>
        </CardContent>
      </Card>

      {/* Stat tiles */}
      <div data-tour="rf-stats" className="grid grid-cols-3 gap-3">
        <Stat
          icon={<Users className="size-4" />}
          label="Referrals"
          value={String(data?.total_referrals ?? 0)}
        />
        <Stat
          icon={<UserCheck className="size-4" />}
          label="Active"
          value={String(data?.active_referrals ?? 0)}
        />
        <Stat
          icon={<Coins className="size-4" />}
          label="Earned"
          value={formatINR(data?.total_earnings ?? 0)}
          accent
        />
      </div>

      {/* Your referrals */}
      <div data-tour="rf-list">
        <h2 className="mb-2.5 text-sm font-bold uppercase tracking-wide text-muted-foreground">
          Your referrals
        </h2>
        {referrals.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
              <span className="grid size-11 place-items-center rounded-xl bg-primary/10 text-primary">
                <Users className="size-5" />
              </span>
              <p className="text-sm font-medium">No referrals yet</p>
              <p className="max-w-xs text-xs text-muted-foreground">
                Share your code to invite friends — you&apos;ll see them here once they sign up.
              </p>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Mobile (< md): stacked cards */}
            <div className="space-y-2 md:hidden">
              {referrals.map((r, i) => (
                <div key={i} className="rounded-xl border border-border/60 bg-card p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-semibold">
                      {r.referred_user_code || "—"}
                    </span>
                    <StatusPill status={r.status} />
                  </div>
                  {r.referred_name && (
                    <p className="mt-1 truncate text-xs text-muted-foreground">{r.referred_name}</p>
                  )}
                  <div className="mt-2.5 flex items-end justify-between border-t border-border/50 pt-2">
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        Earned
                      </div>
                      <div className="font-tabular text-base font-bold tabular-nums text-buy">
                        {formatINR(r.earnings)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        Joined
                      </div>
                      <div className="font-tabular text-xs tabular-nums text-muted-foreground">
                        {r.joined_at ? new Date(r.joined_at).toLocaleDateString("en-IN") : "—"}
                      </div>
                    </div>
                  </div>
                  <div className="mt-2.5 border-t border-border/50 pt-2.5">
                    <RewardProgress r={r} />
                  </div>
                </div>
              ))}
            </div>

            {/* Desktop (md+): table */}
            <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold">User</th>
                    <th className="px-3 py-2 text-left font-semibold">Status</th>
                    <th className="px-3 py-2 text-left font-semibold">Reward progress</th>
                    <th className="px-3 py-2 text-right font-semibold">Earned</th>
                    <th className="px-3 py-2 text-right font-semibold">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {referrals.map((r, i) => (
                    <tr
                      key={i}
                      className="border-t border-border/60 transition-colors hover:bg-muted/15"
                    >
                      <td className="px-3 py-2">
                        <div className="font-mono text-xs">{r.referred_user_code || "—"}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {r.referred_name || ""}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <StatusPill status={r.status} />
                      </td>
                      <td className="px-3 py-2" style={{ minWidth: 180 }}>
                        <RewardProgress r={r} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-tabular font-bold tabular-nums text-buy">
                        {formatINR(r.earnings)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-tabular text-[11px] tabular-nums text-muted-foreground">
                        {r.joined_at ? new Date(r.joined_at).toLocaleDateString("en-IN") : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {/* Recent earnings */}
      {(earnings?.length ?? 0) > 0 && (
        <div data-tour="rf-earnings">
          <h2 className="mb-2.5 flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-muted-foreground">
            <TrendingUp className="size-4" /> Recent earnings
          </h2>
          <Card>
            <CardContent className="space-y-1 p-4">
              {recentEarnings.map((e: any, i: number) => (
                <div
                  key={i}
                  className="flex items-center justify-between gap-3 border-b border-border/60 py-2 last:border-0"
                >
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                    {e.narration}
                  </span>
                  <span className="shrink-0 font-tabular text-sm font-bold tabular-nums text-buy">
                    +{formatINR(e.amount)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <Card className="overflow-hidden">
      <CardContent className="relative p-3 sm:p-4">
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute -right-6 -top-6 size-20 rounded-full blur-2xl",
            accent ? "bg-primary/10" : "bg-muted/40",
          )}
        />
        <div className="relative flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
          <span className={cn(accent && "text-primary")}>{icon}</span>
          {label}
        </div>
        <div
          className={cn(
            "relative mt-1 text-lg font-bold tabular-nums sm:text-xl",
            accent && "text-primary",
          )}
        >
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

function StatusPill({ status }: { status: string }) {
  const s = String(status || "").toUpperCase();
  const isActive = s === "ACTIVE";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
        isActive ? "bg-buy/15 text-buy" : "bg-muted text-muted-foreground",
      )}
    >
      {status}
    </span>
  );
}

/** Per-referred-user reward progress — how much of the super-admin's net
 *  brokerage threshold this referral has generated. At 100% the referrer's
 *  one-time reward has been paid. */
function RewardProgress({ r }: { r: any }) {
  const paid = !!r.trading_reward_paid;
  const pct = paid ? 100 : Math.max(0, Math.min(100, Number(r.trading_progress_pct || 0)));
  const threshold = Number(r.trading_threshold || 0);
  const accrued = Number(r.sa_brokerage_accrued || 0);
  const reward = Number(r.trading_reward || 0);
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2 text-[10px]">
        <span className="uppercase tracking-wide text-muted-foreground">
          {paid ? "Reward unlocked" : "Reward progress"}
        </span>
        <span className={cn("font-bold tabular-nums", paid ? "text-buy" : "text-foreground")}>
          {paid ? `+${formatINR(reward)} ✓` : `${pct.toFixed(0)}%`}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", paid ? "bg-buy" : "bg-primary")}
          style={{ width: `${Math.max(3, pct)}%` }}
        />
      </div>
      {!paid && threshold > 0 && (
        <div className="mt-1 text-[10px] tabular-nums text-muted-foreground">
          {formatINR(accrued)} / {formatINR(threshold)} → unlock {formatINR(reward)}
        </div>
      )}
    </div>
  );
}
