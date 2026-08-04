"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, ChevronDown } from "lucide-react";
import { AccountsAPI } from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { SEGMENT_KINDS, WALLET_ACCENT, WALLET_CODE, WALLET_LABEL, type WalletKind } from "@/lib/wallets";

/**
 * Market-page account bar — the SEGMENT trading-account selector that sits at
 * the top of the Market view (above the Watchlist / Options tabs).
 *
 * Shows the currently-selected trading account (the segment wallet trades are
 * placed from): its wallet CODE chip + label, and — the key ask — that
 * account's BALANCE in bold, in the wallet's accent color. A dropdown switches
 * the active account among the 4 segment wallets WITHOUT leaving the Market
 * page: `setPrimary` + invalidate `["accounts"]` re-scopes the instrument
 * chips (MobileInstrumentsBar reads the primary wallet kind) and repaints the
 * balance live. Unlike TerminalAccountBar, this does NOT navigate to /terminal.
 */
export function MarketAccountBar() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  const { data } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => AccountsAPI.list(),
    staleTime: 5_000,
    refetchInterval: 3_000,
  });

  const kind: WalletKind = (data?.primary_wallet_kind || "NSE_BSE") as WalletKind;
  const walletMap = new Map<string, any>((data?.wallets || []).map((w: any) => [w.kind, w]));
  const _w = walletMap.get(kind);
  const balance = _w?.free_margin ?? _w?.available_balance ?? 0;

  const setPrimary = useMutation({
    mutationFn: (k: string) => AccountsAPI.setPrimary(k),
    onSuccess: (_r, k) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(`Trading from ${WALLET_LABEL[k as WalletKind]}`, { duration: 1500 });
    },
    onError: (e: any) => toast.error(e?.message || "Failed to switch account"),
  });

  // Close the dropdown on outside click.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  function switchTo(k: WalletKind) {
    setOpen(false);
    if (k === kind) return;
    setPrimary.mutate(k);
  }

  const accent = WALLET_ACCENT[kind];

  return (
    <div className="relative shrink-0 border-b border-border bg-card px-3 py-2" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Switch trading account"
        className="flex w-full items-center gap-2 text-left"
      >
        {/* CODE chip (accent) + label — the selected trading account */}
        <span
          className={cn(
            "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
            accent.bg,
            accent.text,
          )}
        >
          {WALLET_CODE[kind]}
        </span>
        <span className="shrink-0 text-xs font-semibold text-muted-foreground">
          {WALLET_LABEL[kind]}
        </span>

        {/* Balance — bold, wallet accent color, tabular-nums, the biggest element */}
        <span className={cn("ml-auto truncate text-base font-extrabold tabular-nums", accent.text)}>
          {formatINR(balance)}
        </span>

        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full z-30 mt-1 overflow-hidden rounded-xl border border-border bg-card shadow-lg">
          <div className="border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Trade from account
          </div>
          {SEGMENT_KINDS.map((k) => {
            const w = walletMap.get(k);
            const acc = WALLET_ACCENT[k];
            const active = k === kind;
            return (
              <button
                key={k}
                type="button"
                onClick={() => switchTo(k)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/40",
                  active && "bg-primary/5",
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                      acc.bg,
                      acc.text,
                    )}
                  >
                    {WALLET_CODE[k]}
                  </span>
                  <span className="text-xs font-semibold">{WALLET_LABEL[k]}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={cn("text-xs font-bold tabular-nums", acc.text)}>
                    {formatINR(w?.free_margin ?? w?.available_balance ?? 0)}
                  </span>
                  {active && <Check className="size-4 text-primary" />}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
