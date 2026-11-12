"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FyersAPI } from "@/lib/api";

/**
 * Red count on the "Fyers Connect" menu item: mismatches since this admin
 * last opened that page. "Last opened" is per browser (localStorage) — it is
 * a reading marker, not shared state. The AdminWsBridge invalidates the
 * ["fyers"] keys on every `price_mismatch` event, so the count moves live.
 */
const SEEN_KEY = "admin.fyers.mismatchSeenAt";

function seenAt(): string | undefined {
  try {
    return window.localStorage.getItem(SEEN_KEY) || undefined;
  } catch {
    return undefined;
  }
}

export function useMarkFyersMismatchesSeen() {
  const qc = useQueryClient();
  return () => {
    try {
      window.localStorage.setItem(SEEN_KEY, new Date().toISOString());
    } catch {
      // Private window / storage blocked: the badge just falls back to "today".
    }
    qc.invalidateQueries({ queryKey: ["fyers", "mismatch-count"] });
  };
}

export function FyersMismatchBadge() {
  const { data } = useQuery({
    queryKey: ["fyers", "mismatch-count"],
    queryFn: () => FyersAPI.mismatchCount(seenAt()),
    refetchInterval: 60_000,
    staleTime: 10_000,
  });
  const n = data?.count ?? 0;
  if (n <= 0) return null;
  return (
    <span className="ml-auto rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-bold leading-none text-destructive-foreground">
      {n > 99 ? "99+" : n}
    </span>
  );
}
