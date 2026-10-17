"use client";

import { useQuery } from "@tanstack/react-query";
import { GamesAPI } from "@/lib/api";
import type { GameUiId } from "@/lib/games/ids";
import { GAME_META, SETTINGS_KEY } from "@/lib/games/ids";

/** Shared 3s-polled games settings (one query for the whole section). */
export function useGamesSettings() {
  return useQuery({
    queryKey: ["games", "settings"],
    queryFn: () => GamesAPI.settings(),
    refetchInterval: 3000,
    staleTime: 2000,
  });
}

/** Config block for one game (by UI id). Returns undefined until settings load. */
export function useGameConfig(id: GameUiId) {
  const { data } = useGamesSettings();
  const games = data?.games || {};
  return games[SETTINGS_KEY[id]];
}

/** A NIFTY game on a weekend / NSE holiday: the market is shut, so no window
 *  runs and no bet goes in (the server refuses them too). BTC is 24x7. */
export function useNseClosed(id: GameUiId) {
  const { data } = useGamesSettings();
  return GAME_META[id].asset === "NIFTY" && data?.nse_open_today === false;
}

export function useGamesWallet() {
  return useQuery({
    queryKey: ["games", "wallet"],
    queryFn: () => GamesAPI.wallet(),
    refetchInterval: 4000,
  });
}

/**
 * Live NIFTY + BTC price (numbers or null).
 * `intervalMs` controls the poll cadence — the lobby uses the default 3s, but
 * an open game screen passes ~1s so the price ticks fast and feels live.
 * The endpoint is cheap (in-memory LTP reads fed by Zerodha / Infoway WS).
 */
export function useGamesPrice(intervalMs = 3000) {
  return useQuery({
    queryKey: ["games", "price"],
    queryFn: () => GamesAPI.price(),
    refetchInterval: intervalMs,
    refetchIntervalInBackground: false,
  });
}

type Kline = { time: number; open: number; high: number; low: number; close: number; volume: number };

/** Fetch BTC candles straight from Binance in the browser (public + CORS).
 *  Tries the market-data host first (fewer geo blocks), then the main API.
 *  This works even when the backend server can't reach Binance. */
async function fetchBinanceKlinesWeb(interval: string, limit = 200): Promise<Kline[]> {
  const hosts = ["https://data-api.binance.vision", "https://api.binance.com"];
  for (const h of hosts) {
    try {
      const r = await fetch(`${h}/api/v3/klines?symbol=BTCUSDT&interval=${interval}&limit=${limit}`);
      if (!r.ok) continue;
      const rows = await r.json();
      if (Array.isArray(rows) && rows.length) {
        return rows.map((k: any[]) => ({
          time: Math.floor(Number(k[0]) / 1000),
          open: Number(k[1]), high: Number(k[2]), low: Number(k[3]),
          close: Number(k[4]), volume: Number(k[5]),
        }));
      }
    } catch {
      /* try next host */
    }
  }
  return [];
}

/** Candle history for the chart.
 *  BTC  → Binance directly from the browser (backend fallback).
 *  NIFTY → backend (Kite). */
export function useGamesKlines(asset: "btc" | "nifty", interval: string, intervalMs = 5000) {
  return useQuery({
    queryKey: ["games", "klines", asset, interval],
    queryFn: async () => {
      if (asset === "btc") {
        const candles = await fetchBinanceKlinesWeb(interval, 200);
        if (candles.length) return { candles, source: "binance-web", interval };
      }
      // NIFTY, or BTC web-fetch failed → backend.
      return GamesAPI.klines(asset, interval, 200);
    },
    refetchInterval: intervalMs,
    refetchIntervalInBackground: false,
    staleTime: 3000,
  });
}
