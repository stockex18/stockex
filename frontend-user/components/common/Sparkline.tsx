"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { InstrumentAPI } from "@/lib/api";
import { cn } from "@/lib/utils";

const IST_SEC = 5.5 * 3600;
const istDay = (t: number) => Math.floor((t + IST_SEC) / 86400);

/**
 * Today's (or the last session's) intraday line for one instrument.
 *
 * Only for short, shared lists like the home card: the history endpoint is
 * cached per token on the server, so every user asking for NIFTY costs one
 * upstream call a minute. Never put this on a per-user list of 30 rows.
 */
export function Sparkline({
  token,
  up,
  className,
}: {
  token: string | null | undefined;
  up: boolean;
  className?: string;
}) {
  const { data } = useQuery<any[]>({
    queryKey: ["sparkline", token],
    queryFn: () => InstrumentAPI.history(String(token), "15minute", 5),
    enabled: !!token,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  const points = useMemo(() => {
    const candles = (data ?? []).filter((c) => Number(c?.close) > 0 && Number(c?.time) > 0);
    if (candles.length < 2) return "";
    const last = istDay(Number(candles[candles.length - 1].time));
    const closes = candles.filter((c) => istDay(Number(c.time)) === last).map((c) => Number(c.close));
    if (closes.length < 2) return "";
    const lo = Math.min(...closes);
    const span = Math.max(...closes) - lo || 1;
    return closes
      .map((v, i) => `${((i / (closes.length - 1)) * 100).toFixed(2)},${(30 - ((v - lo) / span) * 28).toFixed(2)}`)
      .join(" ");
  }, [data]);

  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" className={cn("h-8 w-16", className)} aria-hidden>
      {points && (
        <polyline
          points={points}
          fill="none"
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          className={up ? "stroke-emerald-500" : "stroke-red-500"}
        />
      )}
    </svg>
  );
}
