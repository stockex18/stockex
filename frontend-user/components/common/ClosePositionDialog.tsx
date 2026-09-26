"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { PositionAPI } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Replacement for the browser-native `confirm("Square off this position?")`
 * dialog. The native confirm:
 *   • doesn't theme with the app (jarring system chrome),
 *   • can't show context (symbol, side, current lots),
 *   • is all-or-nothing — no partial-close UX.
 *
 * This modal mirrors the screenshot the user shared: symbol/side/open-lots
 * summary, four quick presets (25 / 50 / 75 / FULL), a numeric override
 * box, and a destructive Close action. Optimistically removes the row from
 * `["positions","open"]` on click so the UI feels instant; the API call
 * runs in the background and rolls back on error.
 */
export interface ClosePositionTarget {
  id: string;
  symbol: string;
  side: "BUY" | "SELL" | string;
  /** Open lots (canonical lot count, NOT raw qty). Can be fractional for
   *  MCX/crypto/forex (0.01, 0.001). */
  lots: number;
  /** Contracts per lot, so the box can be typed in QTY as well as lots —
   *  some operators size in one, some in the other. */
  lotSize?: number;
  /** Used for the market-hours guard so a click outside trading hours
   *  shows a clear toast instead of firing the API and getting rejected
   *  (which would briefly remove the row before rollback). */
  segment_type?: string;
  exchange?: string;
}

type Preset = 25 | 50 | 75 | 100;

interface Props {
  target: ClosePositionTarget | null;
  onClose: () => void;
}

export function ClosePositionDialog({ target, onClose }: Props) {
  const qc = useQueryClient();
  const [preset, setPreset] = useState<Preset>(100);
  // The box is typed in whichever unit the user picked. `amount` is always
  // in THAT unit; lots are worked out at submit.
  const [unit, setUnit] = useState<"LOTS" | "QTY">("LOTS");
  const [amount, setAmount] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  // Reset state whenever a new position opens the dialog. Without this the
  // last user's preset / typed value would carry over to the next click.
  useEffect(() => {
    if (target) {
      setPreset(100);
      setUnit("LOTS");
      setAmount(String(target.lots));
      setSubmitting(false);
    }
  }, [target]);

  const open = !!target;
  const openLots = target?.lots ?? 0;
  const lotSize = Math.max(1, Number(target?.lotSize ?? 1));
  const openQty = +(openLots * lotSize).toFixed(3);
  const maxInUnit = unit === "LOTS" ? openLots : openQty;

  /** Switch units and carry the number across, so flipping the toggle never
   *  silently changes how much is about to be closed. */
  function switchUnit(next: "LOTS" | "QTY") {
    if (next === unit) return;
    const v = Number(amount);
    if (Number.isFinite(v) && v > 0) {
      setAmount(
        String(+(next === "QTY" ? v * lotSize : v / lotSize).toFixed(3)),
      );
    }
    setUnit(next);
  }

  function pickPreset(p: Preset) {
    setPreset(p);
    // Round to the same decimal precision the panel uses for the lot
    // stepper (3 dp covers MCX 0.001 / crypto 0.001). Avoids "0.0033333…"
    // when the user picks 33% on 0.01 lots (we expose 25/50/75 only, so
    // values come out clean, but the rounding stays correct for edge cases).
    setAmount(String(+((maxInUnit * p) / 100).toFixed(3)));
  }

  async function submit() {
    if (!target || submitting) return;
    const typed = Number(amount);
    if (!Number.isFinite(typed) || typed <= 0) {
      toast.error(unit === "QTY" ? "Enter a valid quantity" : "Enter a valid lot count");
      return;
    }
    if (typed > maxInUnit + 1e-9) {
      toast.error(
        `Cannot close more than open ${maxInUnit} ${unit === "QTY" ? "qty" : "lots"}`,
      );
      return;
    }
    const lots = unit === "QTY" ? +(typed / lotSize).toFixed(6) : typed;
    // NO market-hours guard. This is a B-book: a user must always be able
    // to get OUT of a position, and the server accepts `is_squareoff` at
    // any hour. The positions page dropped the same guard from its own
    // close path for exactly that reason; leaving it here would have meant
    // wiring this dialog in quietly took that back, and a user sitting on
    // a loss after the bell could not exit.
    const isFull = lots >= openLots - 1e-9;

    setSubmitting(true);

    // Optimistic: drop the row from the open-positions cache for a FULL
    // close so the dialog → row removal feels instant. Partial closes
    // leave the row in place (the position is still open, just smaller);
    // the next 3 s positions poll picks up the new qty/avg.
    let snapshot: any[] | undefined;
    if (isFull) {
      snapshot = qc.getQueryData<any[]>(["positions", "open"]);
      qc.setQueryData<any[]>(["positions", "open"], (old) =>
        Array.isArray(old) ? old.filter((p) => p.id !== target.id) : old,
      );
    }

    // Close the dialog immediately — the user already committed by clicking
    // Close. Background error path rolls back the optimistic update.
    onClose();

    // Fire the success toast NOW so it pops together with the optimistic
    // row removal — not 500-2000 ms later after the network round-trip.
    // On rejection we dismiss this and replace with an error toast.
    const pendingToastId = toast.success(
      isFull
        ? `${target.symbol} closed`
        : `${target.symbol} ${typed} ${unit === "QTY" ? "qty" : "lot(s)"} closed`,
    );

    try {
      // `lots` param: omit for full close so the backend takes the position-
      // wide path (releases all margin, sets status=CLOSED). Sending an
      // explicit value here would still work but the path is slightly
      // different and full-close is the common case.
      await PositionAPI.squareoff(target.id, isFull ? undefined : lots);
      // DO NOT invalidate positions — Atlas read replica may briefly
      // return the just-closed row as still OPEN, which would re-add
      // the row after we just optimistically removed it (flicker). The
      // 2 s background poll handles eventual consistency.
      qc.invalidateQueries({ queryKey: ["wallet"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      // Refresh the Closed tab so the just-closed slice (full OR partial)
      // shows up immediately — this dialog is the mobile close path, so
      // without this the user had to pull-to-refresh to see the row. The
      // delayed retry covers the brief Atlas read-replica lag where the
      // closing Trade isn't on the replica yet on the first refetch.
      qc.invalidateQueries({ queryKey: ["positions", "closed"] });
      setTimeout(
        () => qc.invalidateQueries({ queryKey: ["positions", "closed"] }),
        1500,
      );
    } catch (e: any) {
      // Rollback the optimistic removal.
      if (isFull && snapshot) qc.setQueryData(["positions", "open"], snapshot);
      toast.dismiss(pendingToastId);
      toast.error(e?.message || "Close failed");
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-sm gap-3 p-5">
        <DialogTitle className="text-base font-semibold">Close Position</DialogTitle>

        {/* Symbol / side / open-lots summary card */}
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5 text-sm">
          <Row label="Symbol" value={target?.symbol ?? "—"} />
          <Row
            label="Side"
            value={
              <span className={cn(
                "font-semibold",
                String(target?.side).toUpperCase() === "BUY" ? "text-buy" : "text-sell",
              )}>
                {String(target?.side).toUpperCase()}
              </span>
            }
          />
          <Row label="Open lots" value={String(openLots)} />
          {lotSize > 1 && <Row label="Open qty" value={String(openQty)} />}
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {unit === "QTY" ? "Qty to close" : "Lots to close"}
            </p>
            {/* Some operators size in lots, some in contracts. Switching
                carries the number across rather than resetting it. */}
            <div className="flex overflow-hidden rounded-md border border-border">
              {(["LOTS", "QTY"] as const).map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => switchUnit(u)}
                  className={cn(
                    "px-2.5 py-1 text-[11px] font-semibold transition-colors",
                    unit === u
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                  )}
                >
                  {u}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-1.5">
            {([25, 50, 75, 100] as Preset[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => pickPreset(p)}
                className={cn(
                  "rounded-md border px-2 py-1.5 text-xs font-semibold transition-colors",
                  preset === p
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                )}
              >
                {p === 100 ? "FULL" : `${p}%`}
              </button>
            ))}
          </div>
          <input
            type="number"
            step="any"
            min={0}
            max={maxInUnit}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="mt-2 h-9 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-primary"
          />
        </div>

        <div className="mt-1 grid grid-cols-2 gap-2">
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={submitting}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {submitting ? "Closing…" : "Close"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  );
}
