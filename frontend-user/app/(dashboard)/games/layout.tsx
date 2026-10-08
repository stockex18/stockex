"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { PiArrowsLeftRightBold, PiCoinFill, PiGameControllerFill, PiPlusBold } from "react-icons/pi";
import { formatCoins as formatINR } from "@/lib/games/coins";
import { useGamesSettings, useGamesWallet } from "@/components/games/useGames";
import { TransferDialog } from "@/components/games/TransferDialog";

export default function GamesLayout({ children }: { children: React.ReactNode }) {
  const { data: settings } = useGamesSettings();
  const { data: wallet } = useGamesWallet();
  const [txIn, setTxIn] = useState(false);
  const [txOut, setTxOut] = useState(false);

  const maintenance = settings?.maintenance_mode || settings?.games_enabled === false;

  return (
    <div className="mx-auto w-full max-w-screen-xl p-3 pb-24 sm:p-6 md:pb-6">
      {/* Games sub-header — stacks cleanly on mobile, single row on ≥sm */}
      <div className="mb-4 flex flex-col gap-3 sm:mb-5 sm:flex-row sm:items-center">
        <Link href="/games" className="flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-2xl bg-gradient-to-br from-yellow-300 to-amber-500 text-neutral-900 shadow-md shadow-amber-500/30">
            <PiGameControllerFill className="size-6" />
          </span>
          <span className="leading-tight">
            <span className="block text-lg font-extrabold tracking-tight">Games</span>
            <span className="block text-[11px] font-semibold text-muted-foreground">Play market games &amp; win coins</span>
          </span>
        </Link>

        <div className="flex items-center gap-2 sm:ml-auto">
          {/* Coin balance — amber/atm coin accent so ◉ reads as a real
              "coins" balance, not just another 🪙 figure. */}
          <div className="flex flex-1 items-center gap-3 rounded-2xl border border-primary/40 bg-gradient-to-r from-primary/15 via-primary/5 to-transparent px-3 py-2 sm:flex-none">
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-yellow-300 to-amber-500 text-neutral-900 shadow-md shadow-amber-500/30">
              <PiCoinFill className="size-6" />
            </span>
            <div className="min-w-0">
              <div className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">Games coins</div>
              {/* Shown in ◉ coins (not tickets) — each game has its own ticket
                  price, so a single "Tkt" count across games is misleading. */}
              <div className="text-lg font-extrabold leading-tight tabular-nums text-primary">
                {formatINR(wallet?.balance ?? 0)}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setTxOut(true)}
            aria-label="Move coins to main wallet"
            title="To main wallet"
            className="grid size-12 shrink-0 place-items-center rounded-2xl border border-border bg-card text-foreground/80 shadow-sm transition-colors hover:border-primary/50 active:scale-95"
          >
            <PiArrowsLeftRightBold className="size-5" />
          </button>
          <button
            type="button"
            onClick={() => setTxIn(true)}
            aria-label="Add coins"
            title="Add coins"
            className="grid size-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-yellow-300 to-amber-500 text-neutral-900 shadow-md shadow-amber-500/30 transition-transform active:scale-95"
          >
            <PiPlusBold className="size-5" />
          </button>
        </div>
      </div>

      {maintenance && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-atm/30 bg-atm/10 px-3 py-2 text-sm text-atm">
          <AlertTriangle className="size-4 shrink-0" />
          <span>{settings?.maintenance_message || "Games are temporarily unavailable."}</span>
        </div>
      )}

      {children}

      <TransferDialog open={txIn} onOpenChange={setTxIn} direction="in" />
      <TransferDialog open={txOut} onOpenChange={setTxOut} direction="out" />
    </div>
  );
}
