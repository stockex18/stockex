"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { AdminSecurityAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * One admin's security cap, set where their security is read.
 *
 * The cap is the share of lodged security that may be consumed before that
 * admin's users stop opening trades and stop betting. Each admin gets their
 * own — one book can be trusted further than another — and leaving it blank
 * follows the platform figure, so a change there still moves everybody who
 * has not been given a number of their own.
 *
 * Closing a book stops OPENING only: closing a position always works.
 */
export function SecurityCapControl({ adminId }: { adminId: string }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");

  const { data: u } = useQuery({
    queryKey: ["security-utilisation", adminId],
    queryFn: () => AdminSecurityAPI.utilisation(adminId),
    enabled: !!adminId,
    staleTime: 5_000,
  });

  useEffect(() => {
    setDraft(u?.cap_is_own ? String(u.cap_pct) : "");
  }, [u?.cap_is_own, u?.cap_pct, adminId]);

  const save = useMutation({
    mutationFn: (pct: number | null) => AdminSecurityAPI.setCap(adminId, pct),
    onSuccess: (res: any) => {
      toast.success(
        res?.cap_is_own ? `Cap set to ${res.cap_pct}%` : "Following the platform cap",
      );
      qc.invalidateQueries({ queryKey: ["security-utilisation", adminId] });
      qc.invalidateQueries({ queryKey: ["admin", "security-money"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not save the cap"),
  });

  if (!u) return null;

  const blocked = !!u.blocked;
  const used = Number(u.used_pct || 0);
  const cap = Number(u.cap_pct || 0);
  const bar = Math.max(0, Math.min(100, used));

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        blocked ? "border-destructive/40 bg-destructive/5" : "border-border/60 bg-card",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold">
          {blocked ? (
            <ShieldAlert className="size-4 text-destructive" />
          ) : (
            <ShieldCheck className="size-4 text-emerald-600 dark:text-emerald-400" />
          )}
          Security cap
        </span>
        <span className="flex items-center gap-1.5">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value.replace(/[^\d.]/g, ""))}
            placeholder={String(cap)}
            inputMode="decimal"
            aria-label="Cap percent for this admin"
            className="h-8 w-[76px] font-tabular text-sm"
          />
          <span className="text-xs text-muted-foreground">%</span>
          <Button
            size="sm"
            className="h-8"
            disabled={save.isPending || draft.trim() === ""}
            onClick={() => save.mutate(Number(draft))}
          >
            Save
          </Button>
          {u.cap_is_own && (
            <Button
              size="sm"
              variant="ghost"
              className="h-8"
              disabled={save.isPending}
              onClick={() => save.mutate(null)}
            >
              Use platform
            </Button>
          )}
        </span>
      </div>

      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", blocked ? "bg-destructive" : "bg-emerald-500")}
          style={{ width: `${bar}%` }}
        />
      </div>

      <p className="mt-1.5 text-[11px] text-muted-foreground">
        <span className={cn("font-semibold", blocked ? "text-destructive" : "text-foreground")}>
          {used.toFixed(2)}% used
        </span>{" "}
        of 🪙{Number(u.lodged).toLocaleString("en-IN")} lodged · limit {cap}%
        {u.cap_is_own ? " (this admin's own)" : " (platform)"} ·{" "}
        {blocked
          ? "book CLOSED — their users cannot open a trade or place a bet; closing still works"
          : "book open"}
      </p>
    </div>
  );
}
