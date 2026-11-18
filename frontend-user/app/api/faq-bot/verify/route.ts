/**
 * StockEx Buddy mobile verification status.
 *
 *   GET    /api/faq-bot/verify               → { verified, mobile?, needsForm? }
 *   POST   /api/faq-bot/verify {mobile, otp} → checks the code with
 *          FastAPI (POST /api/v1/marketing-bot/verify) and, if right, sets the
 *          signed session cookie (lib/faqBot/session.ts) for 1 hour, with
 *          the backend's one-time chat token for the lead form
 *          (app/api/faq-bot/lead). needsForm = not yet a lead.
 *   DELETE /api/faq-bot/verify               → clears it ("use another number")
 *
 * `mobile` in responses is masked (••••••3210).
 */

import {
  BACKEND_URL,
  clientIp,
  SESSION_MAX_AGE_SEC,
  createSessionValue,
  maskMobile,
  readSession,
  sessionConfigured,
  sessionCookie,
} from "@/lib/faqBot/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_TIMEOUT_MS = 10_000;

function jsonError(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

export function GET(req: Request) {
  const s = readSession(req);
  return Response.json(
    s ? { verified: true, mobile: maskMobile(s.mobile), needsForm: s.needsForm } : { verified: false },
  );
}

export async function POST(req: Request) {
  if (!sessionConfigured()) {
    return jsonError(503, "NOT_CONFIGURED", "Verification isn't available right now.");
  }
  const body = (await req.json().catch(() => null)) as { mobile?: unknown; otp?: unknown } | null;
  const mobile = typeof body?.mobile === "string" ? body.mobile.trim().slice(0, 20) : "";
  const otp = typeof body?.otp === "string" ? body.otp.trim().slice(0, 8) : "";
  if (!mobile || !/^\d{4,8}$/.test(otp)) {
    return jsonError(400, "BAD_REQUEST", "Enter the code we sent to your mobile.");
  }

  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/api/v1/marketing-bot/verify`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": clientIp(req) },
      body: JSON.stringify({ mobile, otp }),
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
  } catch {
    return jsonError(502, "UNAVAILABLE", "We couldn't check the code right now. Please try again.");
  }

  const data = (await res.json().catch(() => null)) as {
    data?: { verified?: boolean; mobile?: string; chat_token?: string; has_lead?: boolean };
    error?: { code?: string; message?: string };
  } | null;
  const verifiedMobile = data?.data?.mobile;
  if (!res.ok || !data?.data?.verified || !verifiedMobile || !/^\d{10}$/.test(verifiedMobile)) {
    return jsonError(
      res.status === 429 ? 429 : 400,
      data?.error?.code ?? "FAILED",
      res.status === 429
        ? "Too many attempts. Please wait a minute and try again."
        : (data?.error?.message ?? "That code didn't work. Please try again."),
    );
  }

  const token = typeof data.data.chat_token === "string" ? data.data.chat_token : "";
  // Already a lead → straight to the chat. No token (older backend) → the
  // form couldn't be filed anyway, so the chat opens as before.
  const needsForm = !!token && !data.data.has_lead;
  const value = createSessionValue(verifiedMobile, { token, formDone: !needsForm });
  return Response.json(
    { verified: true, mobile: maskMobile(verifiedMobile), needsForm },
    { headers: { "set-cookie": sessionCookie(value, SESSION_MAX_AGE_SEC) } },
  );
}

export function DELETE() {
  return Response.json({ verified: false }, { headers: { "set-cookie": sessionCookie("", 0) } });
}
