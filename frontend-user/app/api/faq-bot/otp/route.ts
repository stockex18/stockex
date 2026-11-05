/**
 * POST /api/faq-bot/otp  { mobile } — text StockEx Buddy's
 * verification code to a mobile number.
 *
 * Relays to FastAPI's public POST /api/v1/marketing-bot/otp, forwarding the
 * visitor's IP so the backend's per-IP limit, per-number cooldown and daily
 * SMS cap (app/services/sms_service.py) apply to the real visitor.
 */

import { BACKEND_URL, clientIp, sessionConfigured } from "@/lib/faqBot/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_TIMEOUT_MS = 10_000;

function jsonError(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

export async function POST(req: Request) {
  if (!sessionConfigured()) {
    return jsonError(503, "NOT_CONFIGURED", "Verification isn't available right now.");
  }
  const body = (await req.json().catch(() => null)) as { mobile?: unknown } | null;
  const mobile = typeof body?.mobile === "string" ? body.mobile.trim().slice(0, 20) : "";
  if (!mobile) return jsonError(400, "BAD_REQUEST", "Enter your mobile number.");

  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/api/v1/marketing-bot/otp`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": clientIp(req) },
      body: JSON.stringify({ mobile }),
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
  } catch {
    return jsonError(502, "UNAVAILABLE", "We couldn't send the code right now. Please try again.");
  }

  const data = (await res.json().catch(() => null)) as {
    message?: string;
    error?: { code?: string; message?: string };
  } | null;
  if (!res.ok) {
    return jsonError(
      res.status === 429 ? 429 : 400,
      data?.error?.code ?? "FAILED",
      res.status === 429
        ? "Too many attempts. Please wait a minute and try again."
        : (data?.error?.message ?? "We couldn't send the code. Please try again."),
    );
  }
  return Response.json({ ok: true, message: data?.message ?? "Code sent." });
}
