"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Landmark, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { PositionAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Pledge a delivery holding, or take it back off.
 *
 * Shares bought for delivery are paid for in full, and that cash sits locked
 * against the position. Pledging them turns the haircut share of their value
 * into margin for NSE / BSE futures and options — the shares stay yours, the
 * position does not move, and nothing is sold. It is the one way a holding
 * does some work while you still hold it.
 *
 * Renders nothing unless this row is a delivery holding in NSE / BSE equity,
 * because nothing else can be pledged.
 */
export function PledgeButton({
  row,
  compact = false,
}: {
  row: any;
  compact?: boolean;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const seg = String(row?.segment_type ?? row?.segment ?? "").toUpperCase();
  const prod = String(row?.product_type ?? "").toUpperCase();
  const isDelivery = prod === "CNC" && (seg === "NSE_EQUITY" || seg === "BSE_EQUITY");
  const pledged = !!row?.is_pledge;

  const toggle = useMutation({
    mutationFn: () => PositionAPI.pledge(String(row.id), !pledged),
    onMutate: () => setBusy(true),
    onSettled: () => setBusy(false),
    onSuccess: (res: any) => {
      toast.success(
        pledged
          ? "Un-pledged"
          : `Pledged — F&O margin is now ${res?.fno_free_margin ?? "updated"}`,
      );
      // The holding, the wallet strip and the order panel's buying power all
      // move together, so refresh the lot rather than one of them.
      for (const k of [["positions"], ["wallet"], ["wallet-summary"], ["pnl-summary"]]) {
        qc.invalidateQueries({ queryKey: k });
      }
    },
    onError: (e: any) =>
      toast.error(e?.message || "Could not change the pledge on this holding"),
  });

  if (!isDelivery) return null;

  return (
    <Button
      size="sm"
      variant="ghost"
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation();
        toggle.mutate();
      }}
      title={
        pledged
          ? "Un-pledge these shares — only possible while the margin is not holding an F&O position"
          : "Pledge these shares to get F&O margin against them. The shares stay yours."
      }
      className={cn(
        "h-7 gap-1 rounded-md px-2 text-xs font-semibold ring-1 ring-inset",
        pledged
          ? "bg-emerald-500/15 text-emerald-600 ring-emerald-500/30 hover:bg-emerald-500/25 dark:text-emerald-400"
          : "bg-primary/10 text-primary ring-primary/25 hover:bg-primary/20",
      )}
    >
      {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Landmark className="size-3.5" />}
      {compact ? (pledged ? "Pledged" : "Pledge") : pledged ? "Pledged" : "Pledge"}
    </Button>
  );
}
