"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Wallet as WalletIcon, ArrowLeftRight, Plus, Star, TrendingUp, LineChart, Gamepad2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn, formatINR } from "@/lib/utils";
import { isDesktopWeb } from "@/lib/platform";
import { AccountsAPI, GamesAPI } from "@/lib/api";
import { WALLET_ACCENT, WALLET_CODE, WALLET_LABEL, SEGMENT_KINDS, type WalletKind } from "@/lib/wallets";
import { TransferDialog } from "@/components/accounts/TransferDialog";
import { TransferDialog as GamesTransferDialog } from "@/components/games/TransferDialog";

export default function AccountsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferFrom, setTransferFrom] = useState<WalletKind>("MAIN");
  const [transferTo, setTransferTo] = useState<WalletKind>("NSE_BSE");
  const [gamesTxIn, setGamesTxIn] = useState(false);
  const [gamesTxOut, setGamesTxOut] = useState(false);

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

  return (
    <div className="mx-auto w-full max-w-screen-lg space-y-5 p-3 pb-24 sm:p-6 md:pb-6">
      <div className="flex items-center gap-2">
        <span className="grid size-9 place-items-center rounded-xl bg-primary/10 text-primary">
          <WalletIcon className="size-5" />
        </span>
        <h1 className="text-lg font-bold tracking-tight">My Accounts</h1>
      </div>

      {/* Main (cash) wallet hero */}
      <Card className="overflow-hidden border-primary/30">
        <CardContent className="relative p-5">
          <span aria-hidden className="pointer-events-none absolute -right-10 -top-10 size-40 rounded-full bg-primary/10 blur-3xl" />
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Main wallet (cash)</div>
          <div className="mt-1 text-3xl font-bold tabular-nums text-primary sm:text-4xl">
            {formatINR(main?.available_balance ?? 0)}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">Deposits land here · fund your trading wallets from this</div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href="/wallet">
              <Button size="sm"><Plus className="size-4" /> Add / Withdraw</Button>
            </Link>
            <Button size="sm" variant="outline" onClick={() => openTransfer("MAIN")}>
              <ArrowLeftRight className="size-4" /> Move to a wallet
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Trading wallets */}
      <div>
        <h2 className="mb-2.5 text-sm font-bold uppercase tracking-wide text-muted-foreground">Trading wallets</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {segs.map((w) => {
            const kind = w.kind as WalletKind;
            const accent = WALLET_ACCENT[kind];
            const isPrimary = primary === kind;
            return (
              <Card key={kind} className={cn("overflow-hidden", isPrimary && "ring-2 ring-primary/40")}>
                <CardContent className="relative p-4">
                  <span aria-hidden className={cn("pointer-events-none absolute -right-8 -top-8 size-24 rounded-full blur-2xl", accent.bg)} />
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={cn("rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider", accent.bg, accent.text)}>
                          {WALLET_CODE[kind]}
                        </span>
                        {isPrimary && (
                          <span className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] font-bold text-primary">
                            <Star className="size-3 fill-primary" /> Primary
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-sm font-semibold">{WALLET_LABEL[kind]}</div>
                    </div>
                    {w.profit_blocked && <span className="text-[10px] font-bold text-sell">Blocked</span>}
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Balance</div>
                      <div className="text-lg font-bold tabular-nums">{formatINR(w.available_balance)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Used margin</div>
                      <div className="text-lg font-bold tabular-nums text-muted-foreground">{formatINR(w.used_margin)}</div>
                    </div>
                  </div>

                  <div className="mt-4 grid grid-cols-3 gap-2">
                    <Button
                      size="sm"
                      className="col-span-1"
                      onClick={() => {
                        if (!isPrimary) setPrimary.mutate(kind);
                        // Surface-aware routing (user request):
                        //  • Desktop WEB → the full Trading Terminal (its layout
                        //    is desktop-first).
                        //  • Mobile APP webview / phone → the Market (watchlist)
                        //    page, the mobile-friendly trade flow.
                        const w = encodeURIComponent(kind);
                        router.push(isDesktopWeb() ? `/terminal?wallet=${w}` : `/marketwatch?wallet=${w}`);
                      }}
                    >
                      <LineChart className="size-4" /> Trade
                    </Button>
                    <Button
                      size="sm"
                      variant={isPrimary ? "secondary" : "outline"}
                      disabled={isPrimary || setPrimary.isPending}
                      onClick={() => setPrimary.mutate(kind)}
                    >
                      <Star className="size-4" /> {isPrimary ? "Primary" : "Set primary"}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => openTransfer("MAIN", kind)}>
                      <ArrowLeftRight className="size-4" /> Move
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Games wallet — separate system, funded from Main. */}
      <div>
        <h2 className="mb-2.5 text-sm font-bold uppercase tracking-wide text-muted-foreground">Games wallet</h2>
        <Card className="overflow-hidden border-primary/30">
          <CardContent className="relative p-4">
            <span aria-hidden className="pointer-events-none absolute -right-8 -top-8 size-24 rounded-full bg-primary/15 blur-2xl" />
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2.5">
                <span className="grid size-10 place-items-center rounded-xl bg-primary/10 text-primary">
                  <Gamepad2 className="size-5" />
                </span>
                <div>
                  <span className="rounded-md bg-primary/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-primary">GAMES</span>
                  <div className="mt-1 text-sm font-semibold">Games</div>
                </div>
              </div>
            </div>

            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Balance</div>
              <div className="text-2xl font-bold tabular-nums text-primary">{formatINR(gamesWallet?.balance ?? 0)}</div>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2">
              <Button size="sm" onClick={() => router.push("/games")}>
                <Gamepad2 className="size-4" /> Play
              </Button>
              <Button size="sm" variant="outline" onClick={() => setGamesTxIn(true)}>
                <Plus className="size-4" /> Add funds
              </Button>
              <Button size="sm" variant="outline" onClick={() => setGamesTxOut(true)}>
                <ArrowLeftRight className="size-4" /> To main
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <TrendingUp className="size-3.5" /> Your <b className="text-foreground">primary</b> wallet decides which market &amp; instruments you trade. Default: NSE / BSE.
      </p>

      <TransferDialog open={transferOpen} onOpenChange={setTransferOpen} defaultFrom={transferFrom} defaultTo={transferTo} />
      <GamesTransferDialog open={gamesTxIn} onOpenChange={setGamesTxIn} direction="in" />
      <GamesTransferDialog open={gamesTxOut} onOpenChange={setGamesTxOut} direction="out" />
    </div>
  );
}
