"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, ChevronDown, Layers, WalletCards } from "lucide-react";
import { AccountsAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn, formatINR } from "@/lib/utils";
import { SEGMENT_KINDS, WALLET_ACCENT, WALLET_CODE, WALLET_LABEL, type WalletKind } from "@/lib/wallets";

/**
 * Terminal header controls (right side):
 *   • ACTIVE ACCOUNT chip + dropdown to switch the trading wallet the terminal
 *     is scoped to — swaps `?wallet=` and re-scopes instruments / order routing.
 *   • "Option chain" button — shown ONLY for the NSE / BSE wallet. Options are
 *     an NSE/BSE F&O product; a Crypto / Forex / MCX account must NOT be able
 *     to open the option chain and place F&O orders from there.
 *
 * Reads `?wallet=` (falls back to the user's primary wallet). Self-contained
 * so the layout only wires the picker-open callback.
 */
export function TerminalAccountBar({ onOpenPicker }: { onOpenPicker: () => void }) {
  const sp = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  const { data } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => AccountsAPI.list(),
    staleTime: 5_000,
    refetchInterval: 3_000,
  });

  const walletParam = sp?.get("wallet") || null;
  const primary: string = data?.primary_wallet_kind || "NSE_BSE";
  const kind: WalletKind = ((walletParam && SEGMENT_KINDS.includes(walletParam as WalletKind))
    ? walletParam
    : primary) as WalletKind;

  const walletMap = new Map<string, any>((data?.wallets || []).map((w: any) => [w.kind, w]));

  const setPrimary = useMutation({
    mutationFn: (k: string) => AccountsAPI.setPrimary(k),
    onSuccess: (_r, k) => qc.invalidateQueries({ queryKey: ["accounts"] }),
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
    // Drop the token so the terminal defaults to the new wallet's instrument
    // (its own segment) instead of keeping the previous account's symbol.
    router.push(`/terminal?wallet=${encodeURIComponent(k)}`);
  }

  const accent = WALLET_ACCENT[kind];
  // Option chain button: the NSE/BSE wallet (index/stock options) and the
  // Crypto wallet (Binance BTC options, view-only phase 1).
  const showOptionChain = kind === "NSE_BSE" || kind === "CRYPTO";

  return (
    <div className="flex items-center gap-2">
      {/* Active account switcher */}
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          title="Switch trading account"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 text-xs font-semibold transition-colors hover:bg-muted/40"
        >
          <WalletCards className={cn("size-4", accent.text)} />
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", accent.bg, accent.text)}>
            {WALLET_CODE[kind]}
          </span>
          <span className="hidden font-semibold sm:inline">{WALLET_LABEL[kind]}</span>
          <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
        </button>

        {open && (
          <div className="absolute right-0 top-full z-30 mt-1 w-60 overflow-hidden rounded-xl border border-border bg-card shadow-lg">
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
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", acc.bg, acc.text)}>
                      {WALLET_CODE[k]}
                    </span>
                    <div>
                      <div className="text-xs font-semibold">{WALLET_LABEL[k]}</div>
                      <div className="text-[10px] tabular-nums text-muted-foreground">
                        {/* free margin = available + credit + live float P&L —
                            the SAME value the order panel's "Avl margin" shows. */}
                        Bal {formatINR(w?.free_margin ?? w?.available_balance ?? 0)}
                      </div>
                    </div>
                  </div>
                  {active && <Check className="size-4 text-primary" />}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Option chain — NSE/BSE only */}
      {showOptionChain && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 border-primary/40 font-bold text-primary hover:bg-primary/10 hover:text-primary"
          onClick={onOpenPicker}
          title="Open option chain"
        >
          <Layers className="size-4" strokeWidth={2.5} />
          <span className="text-xs font-bold">Option chain</span>
        </Button>
      )}
    </div>
  );
}
