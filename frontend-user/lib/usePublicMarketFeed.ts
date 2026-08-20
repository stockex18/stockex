"use client";

import { useEffect, useMemo, useState } from "react";
import { API_URL } from "@/lib/constants";
import { useMarketStream } from "@/lib/useMarketStream";

/**
 * Live market data for the PUBLIC marketing pages.
 *
 * The landing page has no user and therefore no JWT, so it cannot touch
 * anything under `/api/v1/user/*`. Two public surfaces make this work:
 *
 *   1. `GET /api/v1/market/snapshot` — a curated, server-side instrument
 *      list with prices. This is both the first paint AND the token
 *      discovery step: the page has no way to resolve "RELIANCE" to an
 *      instrument token on its own (search is auth-only).
 *   2. `/ws/marketdata` — already public (its `token` query param is
 *      optional). Once we know the tokens, `useMarketStream` streams
 *      ticks over the snapshot.
 *
 * The REST call also acts as the fallback path: if the socket is blocked
 * by a corporate proxy or fails to upgrade, the poll below keeps the
 * numbers moving rather than freezing them at first paint.
 */

export type PublicQuote = {
  key: string;
  label: string;
  category: string;
  exchange: string;
  token: string;
  name: string;
  ltp: number;
  change: number;
  change_pct: number;
};

// Slow poll. The WS carries the realtime path; this only has to recover
// from a failed upgrade or a dropped socket, so it stays cheap.
const POLL_MS = 30_000;

export function usePublicMarketFeed(): {
  rows: PublicQuote[];
  loading: boolean;
  failed: boolean;
} {
  const [rows, setRows] = useState<PublicQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const load = async () => {
      try {
        const res = await fetch(
          `${API_URL.replace(/\/$/, "")}/api/v1/market/snapshot`,
          { cache: "no-store" },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        const data: PublicQuote[] = Array.isArray(body?.data) ? body.data : [];
        if (cancelled) return;
        setRows(data);
        // An empty list is a failure for display purposes: it means the
        // instruments aren't seeded or the feed has no positive LTP yet.
        // Callers render an "unavailable" state rather than an empty
        // ticker that looks like a layout bug.
        setFailed(data.length === 0);
      } catch {
        if (!cancelled) setFailed((prev) => (rows.length ? prev : true));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
    // Intentionally mount-only: `rows` is read inside the catch purely to
    // avoid clearing a good render on a transient network blip, and adding
    // it to the deps would restart the poll on every tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Token list is stable as long as the snapshot is — `useMarketStream`
  // keys its subscription off the joined string, so an unstable array
  // identity here would resubscribe on every render.
  const tokens = useMemo(() => rows.map((r) => r.token), [rows]);
  const live = useMarketStream(tokens);

  // Overlay live ticks on the snapshot. The snapshot supplies identity
  // (label / category / exchange); the socket supplies price. A token the
  // socket hasn't sent yet keeps its REST price, so nothing ever renders
  // as a zero or a dash once the first paint has landed.
  const merged = useMemo(() => {
    if (!live.size) return rows;
    return rows.map((r) => {
      const q = live.get(r.token);
      if (!q) return r;
      const ltp = Number(q.ltp);
      if (!Number.isFinite(ltp) || ltp <= 0) return r;
      return {
        ...r,
        ltp,
        change: Number.isFinite(Number(q.change)) ? Number(q.change) : r.change,
        change_pct: Number.isFinite(Number(q.change_pct))
          ? Number(q.change_pct)
          : r.change_pct,
      };
    });
  }, [rows, live]);

  return { rows: merged, loading, failed };
}
