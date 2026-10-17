// IST-based trading-window math for the Up/Down games (client-side; the
// server is the source of truth — this only drives the countdown + the
// "can I bet right now" UX gate).

export type WindowStatus = "open" | "pre_market" | "post_market" | "market_closed";

export interface WindowInfo {
  windowNumber: number;
  status: WindowStatus;
  secondsToClose: number;
  canTrade: boolean;
  startHms: string;
  endHms: string;
}

/** Current IST wall-clock seconds-since-midnight, derived without pulling in
 *  a date lib: format the time in Asia/Kolkata and parse H/M/S. */
export function istSecondsNow(): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? "0");
  return get("hour") * 3600 + get("minute") * 60 + get("second");
}

function hmsToSec(hms: string): number {
  const [h, m, s] = hms.split(":").map((x) => Number(x) || 0);
  return h * 3600 + m * 60 + (s || 0);
}

/** Compute the live window for a fixed round-duration game. */
export function getTradingWindowInfo(
  startHms: string,
  endHms: string,
  roundDurationSec: number,
): WindowInfo {
  const now = istSecondsNow();
  const start = hmsToSec(startHms);
  const end = hmsToSec(endHms);
  const base = { startHms, endHms };
  if (now < start) {
    return { windowNumber: 0, status: "pre_market", secondsToClose: 0, canTrade: false, ...base };
  }
  if (now >= end) {
    return { windowNumber: 0, status: "post_market", secondsToClose: 0, canTrade: false, ...base };
  }
  const delta = now - start;
  const windowNumber = Math.floor(delta / roundDurationSec) + 1;
  const windowClose = start + windowNumber * roundDurationSec;
  return {
    windowNumber,
    status: "open",
    secondsToClose: Math.max(0, windowClose - now),
    canTrade: true,
    ...base,
  };
}

/** Whether the current IST time is within [startHms, endHms] — for the
 *  bidding-window games (number / bracket / jackpot). */
export function isBiddingOpen(startHms: string, endHms: string): boolean {
  const now = istSecondsNow();
  return now >= hmsToSec(startHms) && now <= hmsToSec(endHms);
}

/** Seconds from now until the given IST time-of-day today. Returns 0 once the
 *  time has passed (result is being declared) so the countdown clamps at 0. */
export function secondsUntilIst(hms: string): number {
  return Math.max(0, hmsToSec(hms) - istSecondsNow());
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Clock format. Shows H:MM:SS once the duration crosses an hour, else MM:SS,
 *  so a multi-hour result timer never renders as a confusing "389:38". */
export function formatCountdown(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0 ? `${h}:${pad(m)}:${pad(r)}` : `${pad(m)}:${pad(r)}`;
}

/** Human-readable duration, e.g. "6 hours 29 min", "29 min 38 sec", "38 sec". */
export function formatDurationHuman(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h} hour${h > 1 ? "s" : ""} ${m} min`;
  if (m > 0) return `${m} min ${r} sec`;
  return `${r} sec`;
}
