"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, ArrowLeftRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { COIN_SYMBOL, formatCoins as formatINR } from "@/lib/games/coins";
import { GamesAPI } from "@/lib/api";
import { useGamesWallet } from "@/components/games/useGames";
import { TransferDialog } from "@/components/games/TransferDialog";

export default function GamesWalletPage() {
  const { data: wallet } = useGamesWallet();
  const [txIn, setTxIn] = useState(false);
  const [txOut, setTxOut] = useState(false);
  const { data: ledger } = useQuery({
    queryKey: ["games", "ledger", "all"],
    queryFn: () => GamesAPI.ledger({ limit: 100 }),
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Games wallet</div>
            <div className="text-3xl font-bold tabular-nums text-primary">
              {/* ◉ keeps its original gold; only the figure follows the theme. */}
              <span className="text-[#E8A900] dark:text-[#FFC105]">{COIN_SYMBOL}</span>{" "}
              {formatINR(wallet?.balance ?? 0, { withSymbol: false })}
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setTxOut(true)}>
              <ArrowLeftRight className="size-4" /> Send to main
            </Button>
            <Button onClick={() => setTxIn(true)}>
              <Plus className="size-4" /> Add from main
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Games ledger</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {(ledger || []).length === 0 && (
            <div className="py-8 text-center text-sm text-muted-foreground">No games activity yet.</div>
          )}
          {(ledger || []).map((r: any) => {
            const credit = r.entry_type === "CREDIT";
            return (
              <div key={r.id} className="flex items-center justify-between border-b border-border/60 py-2 last:border-0">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{r.description}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {new Date(r.created_at).toLocaleString("en-IN")}
                  </div>
                </div>
                <div className="text-right">
                  <div className={cn("text-sm font-bold tabular-nums", credit ? "text-buy" : "text-sell")}>
                    {credit ? "+" : "−"}{formatINR(r.amount)}
                  </div>
                  <div className="text-[11px] tabular-nums text-muted-foreground">
                    Bal {formatINR(r.balance_after)}
                  </div>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <TransferDialog open={txIn} onOpenChange={setTxIn} direction="in" />
      <TransferDialog open={txOut} onOpenChange={setTxOut} direction="out" />
    </div>
  );
}
