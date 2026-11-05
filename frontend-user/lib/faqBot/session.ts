/**
 * StockEx Buddy — "this visitor verified their mobile" session.
 *
 * Server-only. After a correct OTP (app/api/faq-bot/verify), the visitor
 * gets a signed, httpOnly cookie that keeps them verified for an hour, so
 * the panel doesn't ask for a new code on every visit.
 *
 * Cookie value: base64url(JSON {m: mobile, exp}) + "." + HMAC-SHA256 of it,
 * keyed by FAQ_BOT_SESSION_SECRET (server-only, 32+ characters). The
 * mobile is readable by its owner but can't be changed without the secret.
 * No secret set → nobody can verify, and the chat stays off.
 */

import { createHmac, timingSafeEqual } from "crypto";

export const SESSION_COOKIE = "sx_buddy";
// How long one verification lasts in a browser before the OTP is asked again.
export const SESSION_MINUTES = 60;
// Only the bot's own routes ever receive the cookie.
const COOKIE_PATH = "/api/faq-bot";

const SECRET = process.env.FAQ_BOT_SESSION_SECRET ?? "";

export function sessionConfigured(): boolean {
  return SECRET.length >= 32;
}

/** Where the Next.js server reaches FastAPI for the OTP calls. */
export const BACKEND_URL =
  process.env.FAQ_BOT_BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

function sign(data: string): string {
  return createHmac("sha256", SECRET).update(data).digest("base64url");
}

export function createSessionValue(mobile: string): string {
  const exp = Date.now() + SESSION_MINUTES * 60 * 1000;
  const data = Buffer.from(JSON.stringify({ m: mobile, exp })).toString("base64url");
  return `${data}.${sign(data)}`;
}

export interface BotSession {
  mobile: string;
  exp: number;
}

export function readSession(req: Request): BotSession | null {
  if (!sessionConfigured()) return null;
  const raw = req.headers
    .get("cookie")
    ?.split(/;\s*/)
    .find((c) => c.startsWith(`${SESSION_COOKIE}=`))
    ?.slice(SESSION_COOKIE.length + 1);
  if (!raw) return null;
  const [data, mac] = raw.split(".");
  if (!data || !mac) return null;
  const want = Buffer.from(sign(data));
  const got = Buffer.from(mac);
  if (want.length !== got.length || !timingSafeEqual(want, got)) return null;
  try {
    const { m, exp } = JSON.parse(Buffer.from(data, "base64url").toString("utf8")) as {
      m?: unknown;
      exp?: unknown;
    };
    if (typeof m !== "string" || !/^\d{10}$/.test(m)) return null;
    if (typeof exp !== "number" || exp < Date.now()) return null;
    return { mobile: m, exp };
  } catch {
    return null;
  }
}

/** Set-Cookie header value; pass maxAgeSec 0 to clear. */
export function sessionCookie(value: string, maxAgeSec: number): string {
  const parts = [
    `${SESSION_COOKIE}=${value}`,
    `Path=${COOKIE_PATH}`,
    `Max-Age=${maxAgeSec}`,
    "HttpOnly",
    "SameSite=Lax",
  ];
  if (process.env.NODE_ENV === "production") parts.push("Secure");
  return parts.join("; ");
}

export const SESSION_MAX_AGE_SEC = SESSION_MINUTES * 60;

/** "••••••3210" */
export function maskMobile(m: string): string {
  return `••••••${m.slice(-4)}`;
}

/** Visitor IP as nginx forwards it (first X-Forwarded-For hop). */
export function clientIp(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  const ip = fwd?.split(",")[0]?.trim() || req.headers.get("x-real-ip") || "unknown";
  return ip.slice(0, 64);
}
