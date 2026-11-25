"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertsAPI, InstrumentAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface AlertInstrument {
  token: string;
  symbol: string;
  exchange?: string | null;
}

type AlertKind = "LTP_ABOVE" | "LTP_BELOW";

function fmt(n: number): string {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/* New price alert — one form for the Alerts page and the 🔔 on a symbol's
   trade sheet (mobile Market). With `instrument` the symbol comes filled in.
   Shows the live LTP, starts the target at it, and says when the alert would
   fire at once (the server fires as soon as the condition is true). */
export function NewAlertDialog({
  open,
  onOpenChange,
  instrument,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  instrument?: AlertInstrument | null;
}) {
  const qc = useQueryClient();
  const [picked, setPicked] = useState<AlertInstrument | null>(instrument ?? null);
  const [search, setSearch] = useState(instrument?.symbol ?? "");
  const [kind, setKind] = useState<AlertKind>("LTP_ABOVE");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  // Fresh form every time it opens (and for whichever symbol opened it).
  useEffect(() => {
    if (!open) return;
    setPicked(instrument ?? null);
    setSearch(instrument?.symbol ?? "");
    setKind("LTP_ABOVE");
    setTarget("");
    setNote("");
  }, [open, instrument?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  const typing = !picked || search !== picked.symbol;
  const { data: results } = useQuery({
    queryKey: ["instr-search-alerts", search],
    queryFn: () => InstrumentAPI.search(search, undefined, undefined, 12),
    enabled: open && typing && search.trim().length > 0,
  });

  const { data: quote } = useQuery({
    queryKey: ["quote", picked?.token],
    queryFn: () => InstrumentAPI.quote(picked!.token),
    enabled: open && !!picked?.token,
    refetchInterval: open ? 2000 : false,
  });
  const ltp = Number(quote?.ltp || quote?.last_ltp || 0) || null;

  // Start the target at the live price, once, so the user only nudges it.
  useEffect(() => {
    if (ltp && !target) setTarget(String(ltp));
  }, [ltp]); // eslint-disable-line react-hooks/exhaustive-deps

  const t = Number(target);
  const firesNow =
    !!ltp && t > 0 && ((kind === "LTP_ABOVE" && ltp >= t) || (kind === "LTP_BELOW" && ltp <= t));

  function pick(r: any) {
    setPicked({ token: String(r.token), symbol: r.symbol, exchange: r.exchange });
    setSearch(r.symbol);
    setTarget("");
  }

  async function create() {
    if (!picked || !(t > 0)) {
      toast.error("Choose an instrument and a target price");
      return;
    }
    setSaving(true);
    try {
      await AlertsAPI.create({ token: picked.token, alert_type: kind, target_price: t, note });
      toast.success(`Alert set: ${picked.symbol} ${kind === "LTP_ABOVE" ? "above" : "below"} ${fmt(t)}`);
      qc.invalidateQueries({ queryKey: ["alerts"] });
      onOpenChange(false);
    } catch (e: any) {
      toast.error(e?.message || "Could not create the alert");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100%-1rem)] max-w-md">
        <DialogHeader>
          <DialogTitle>New price alert</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="alert-instrument">Instrument</Label>
            <Input
              id="alert-instrument"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search symbol…"
              autoComplete="off"
            />
            {typing && search && results?.length ? (
              <div className="max-h-44 space-y-1 overflow-y-auto rounded-md border border-border p-1">
                {results.map((r: any) => (
                  <button
                    type="button"
                    key={r.token}
                    onClick={() => pick(r)}
                    className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                  >
                    <span className="truncate">{r.symbol}</span>
                    <span className="shrink-0 text-muted-foreground">{r.exchange}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {picked && !typing && (
              <div className="flex items-center justify-between rounded-md bg-muted/50 px-2.5 py-1.5 text-xs">
                <span className="text-muted-foreground">Current price (LTP)</span>
                <span className="font-tabular font-semibold tabular-nums">{ltp ? fmt(ltp) : "—"}</span>
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <Label>Alert me when the price</Label>
            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  ["LTP_ABOVE", "Rises above", "border-buy bg-buy/10 text-buy"],
                  ["LTP_BELOW", "Falls below", "border-sell bg-sell/10 text-sell"],
                ] as const
              ).map(([k, label, on]) => (
                <button
                  type="button"
                  key={k}
                  onClick={() => setKind(k)}
                  aria-pressed={kind === k}
                  className={cn(
                    "h-10 rounded-md border text-sm font-semibold transition-colors",
                    kind === k ? on : "border-border text-muted-foreground hover:bg-muted/50",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="alert-target">Target price (🪙)</Label>
            <Input
              id="alert-target"
              type="number"
              inputMode="decimal"
              step="0.05"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
            {firesNow && (
              <p className="text-xs text-amber-500">
                The price is already {kind === "LTP_ABOVE" ? "at or above" : "at or below"} this target, so the
                alert will fire straight away.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="alert-note">Note (optional)</Label>
            <Input id="alert-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={create} loading={saving}>
            Create alert
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
