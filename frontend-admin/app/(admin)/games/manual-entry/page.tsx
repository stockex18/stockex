"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Check, RotateCcw, Gavel } from "lucide-react";
import { AdminGamesAPI, ApiError } from "@/lib/api";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

function todayIST(): string {
  // Server keys days by IST calendar date; approximate on the client.
  const now = new Date();
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60000);
  return ist.toISOString().slice(0, 10);
}

function deriveNumber(close: string): string {
  const n = Number(close);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const frac = Math.round((n - Math.floor(n)) * 100);
  return String(frac).padStart(2, "0");
}

export default function ManualGameEntryPage() {
  const qc = useQueryClient();
  const [day, setDay] = useState(todayIST());
  const [close, setClose] = useState("");
  const [closes, setCloses] = useState<Record<string, string>>({}); // per-game close
  const [reverseOpen, setReverseOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "manual-entry", day],
    queryFn: () => AdminGamesAPI.manualEntry(day),
    refetchInterval: 20_000,
  });

  const declareM = useMutation({
    mutationFn: () => AdminGamesAPI.manualEntryDeclare({ day, close_price: close }),
    onSuccess: (res: any) => {
      toast.success(`Declared — number .${String(res?.number ?? "").padStart(2, "0")} · all 3 games settled`);
      qc.invalidateQueries({ queryKey: ["admin", "manual-entry", day] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Declare failed"),
  });

  const reverseM = useMutation({
    mutationFn: () => AdminGamesAPI.manualEntryReverse(day),
    onSuccess: (res: any) => {
      const games = res?.games ?? [];
      const totalReversed = games.reduce((s: number, g: any) => s + (g.won_reversed ?? 0), 0);
      const shortfalls = games.flatMap((g: any) => g.shortfalls ?? []);
      setReverseOpen(false);
      if (shortfalls.length) {
        toast.warning(`Reversed ${totalReversed} wins — ${shortfalls.length} payout(s) could NOT be clawed back (already spent).`);
      } else {
        toast.success(`Reversed ${totalReversed} wins — payouts clawed back, results cleared.`);
      }
      qc.invalidateQueries({ queryKey: ["admin", "manual-entry", day] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Reverse failed"),
  });

  // Per-game declare / reverse — fix ONE wrong game without touching the others.
  const declareGameM = useMutation({
    mutationFn: (v: { game_key: string; close_price: string }) =>
      AdminGamesAPI.manualEntryDeclareGame({ day, ...v }),
    onSuccess: (res: any) => {
      toast.success(`${res?.game_key} declared — number .${String(res?.number ?? "").padStart(2, "0")}`);
      qc.invalidateQueries({ queryKey: ["admin", "manual-entry", day] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Declare failed"),
  });
  const reverseGameM = useMutation({
    mutationFn: (game_key: string) => AdminGamesAPI.manualEntryReverseGame({ day, game_key }),
    onSuccess: (res: any) => {
      const short = res?.shortfalls ?? [];
      if (short.length) toast.warning(`${res?.game} reversed — ${short.length} payout(s) not clawed back (spent).`);
      else toast.success(`${res?.game} reversed — re-declare the correct close.`);
      qc.invalidateQueries({ queryKey: ["admin", "manual-entry", day] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Reverse failed"),
  });

  const games: any[] = data?.games ?? [];
  const anyDeclared = games.some((g) => g.declared);
  const manualClose = data?.manual_close ?? null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Manual Game Entry"
        description="Super-admin only — declare all 3 from one NIFTY close, OR fix each game separately below (per-game declare + reverse). Reverse only the wrong game and re-declare it."
      />

      {/* Declare card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gavel className="size-4" /> Declare result
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5 sm:max-w-[200px]">
            <Label htmlFor="day">Day (IST)</Label>
            <Input id="day" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </div>

          {/* Per-game — type each game's close separately, declare / reverse each */}
          <div className="space-y-2">
            <Label>Per-game close — enter each game separately</Label>
            {games.map((g) => {
              const busyDeclare = declareGameM.isPending && declareGameM.variables?.game_key === g.game_key;
              const busyReverse = reverseGameM.isPending && reverseGameM.variables === g.game_key;
              const gClose = closes[g.game_key] ?? "";
              return (
                <div key={g.game_key} className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/10 p-2.5">
                  <span className="w-28 shrink-0 font-medium">{g.label}</span>
                  {g.declared ? (
                    <>
                      <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-bold text-emerald-600">Declared</span>
                      <span className="font-mono text-sm text-muted-foreground">
                        {g.game_key === "niftyNumber" && g.result != null ? `.${String(g.result).padStart(2, "0")}` : g.close_price ?? "—"}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        loading={busyReverse}
                        onClick={() => reverseGameM.mutate(g.game_key)}
                        className="ml-auto border-amber-500/50 text-amber-600 hover:bg-amber-500/10"
                      >
                        <RotateCcw className="mr-1 size-3.5" /> Reverse
                      </Button>
                    </>
                  ) : (
                    <>
                      <Input
                        inputMode="decimal"
                        placeholder="NIFTY close e.g. 24774.30"
                        value={gClose}
                        onChange={(e) => setCloses((p) => ({ ...p, [g.game_key]: e.target.value }))}
                        className="h-9 w-44"
                      />
                      {gClose && Number(gClose) > 0 && g.game_key === "niftyNumber" && (
                        <span className="text-xs text-muted-foreground">→ .{deriveNumber(gClose)}</span>
                      )}
                      <Button
                        size="sm"
                        loading={busyDeclare}
                        disabled={!(Number(gClose) > 0)}
                        onClick={() => declareGameM.mutate({ game_key: g.game_key, close_price: gClose })}
                        className="ml-auto bg-emerald-600 hover:bg-emerald-700"
                      >
                        <Check className="mr-1 size-3.5" /> Declare
                      </Button>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          {/* Or one close for all three */}
          <div className="space-y-2 border-t border-border pt-3">
            <Label htmlFor="close">Or declare all 3 from one NIFTY close</Label>
            <div className="flex flex-wrap items-end gap-2">
              <Input
                id="close"
                inputMode="decimal"
                placeholder="e.g. 24774.30"
                value={close}
                onChange={(e) => setClose(e.target.value)}
                className="w-56"
              />
              <Button
                onClick={() => declareM.mutate()}
                loading={declareM.isPending}
                disabled={!close || Number(close) <= 0}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                <Check className="mr-1.5 size-4" /> Declare all 3
              </Button>
              {close && Number(close) > 0 && (
                <span className="text-xs text-muted-foreground">
                  Number .{deriveNumber(close)} · Jackpot {Number(close).toLocaleString("en-IN")} · Bracket {Number(close).toLocaleString("en-IN")}
                </span>
              )}
            </div>
          </div>

          {manualClose && (
            <p className="text-xs text-muted-foreground">
              Currently typed close for {day}: <span className="font-mono font-semibold">🪙{manualClose}</span>
            </p>
          )}
        </CardContent>
      </Card>

      {/* Per-game state */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Current state · {day}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-3">Game</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Result</th>
                <th className="px-4 py-3 text-right">Bets</th>
                <th className="px-4 py-3 text-right">Winners</th>
                <th className="px-4 py-3 text-right">Payout</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">Loading…</td>
                </tr>
              ) : (
                games.map((g) => (
                  <tr key={g.game_key} className="border-b border-border/60 last:border-0">
                    <td className="px-4 py-3 font-medium">{g.label}</td>
                    <td className="px-4 py-3">
                      {g.declared ? (
                        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-bold text-emerald-600">
                          Declared
                        </span>
                      ) : (
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
                          Pending
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono">
                      {g.game_key === "niftyNumber" && g.result != null
                        ? `.${String(g.result).padStart(2, "0")}`
                        : g.close_price ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{g.bets}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{g.winners}</td>
                    <td className="px-4 py-3 text-right tabular-nums">🪙{g.payout}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Reverse */}
      <Card className="border-amber-500/30">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold">Wrong result punched?</p>
            <p className="text-[12px] text-muted-foreground">
              Reverse claws back all credited payouts (winner + hierarchy + referral) and clears the
              declared result so you can re-declare the correct close.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => setReverseOpen(true)}
            disabled={!anyDeclared}
            className="border-amber-500/50 text-amber-600 hover:bg-amber-500/10"
          >
            <RotateCcw className="mr-1.5 size-4" /> Reverse {day}
          </Button>
        </CardContent>
      </Card>

      <Dialog open={reverseOpen} onOpenChange={(v) => !reverseM.isPending && setReverseOpen(v)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" /> Reverse {day}?
            </DialogTitle>
            <DialogDescription className="space-y-2 pt-1">
              <span className="block">
                This undoes the settlement for <span className="font-bold text-foreground">all 3 nifty games</span> on {day}:
              </span>
              <span className="block rounded-lg border border-border bg-muted/30 p-2.5 text-[13px] leading-relaxed text-foreground">
                • Claws back every credited payout (winner + hierarchy + referral)
                <br />• Resets all bets to pending
                <br />• Clears the declared result
              </span>
              <span className="block text-[12px]">
                Any payout already spent/withdrawn by a winner can&apos;t be clawed back — those are reported.
                Then re-declare with the correct close.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => setReverseOpen(false)} disabled={reverseM.isPending}>
              Cancel
            </Button>
            <Button
              onClick={() => reverseM.mutate()}
              loading={reverseM.isPending}
              className="bg-amber-600 font-bold text-white hover:bg-amber-700"
            >
              Yes, reverse
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
