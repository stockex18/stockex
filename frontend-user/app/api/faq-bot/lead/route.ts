/**
 * POST /api/faq-bot/lead  { full_name, email, city, experience,
 *                          enquiry_for, question } — StockEx Buddy's
 * callback form, shown after the chat's mobile OTP.
 *
 * The mobile and the backend's one-time chat token come from the signed
 * session cookie (lib/faqBot/session.ts), never from the browser, so the
 * lead is always filed for the number that was verified. Relays to FastAPI's
 * POST /api/v1/marketing-bot/lead (same lead row as the /start page, source
 * "Chatbot"), then re-issues the cookie without the token and marked done,
 * keeping its expiry, so the chat opens.
 */

import {
  BACKEND_URL,
  clientIp,
  createSessionValue,
  readSession,
  secondsLeft,
  sessionCookie,
} from "@/lib/faqBot/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_TIMEOUT_MS = 10_000;
const FIELDS = ["full_name", "email", "city", "experience", "enquiry_for", "question"] as const;

function jsonError(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

export async function POST(req: Request) {
  const s = readSession(req);
  if (!s?.token) {
    return jsonError(401, "NOT_VERIFIED", "Your verification has expired. Please verify your mobile again.");
  }
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  const fields: Record<string, string> = {};
  for (const k of FIELDS) {
    const v = body?.[k];
    fields[k] = typeof v === "string" ? v.slice(0, k === "question" ? 2000 : 254) : "";
  }

  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/api/v1/marketing-bot/lead`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": clientIp(req),
        "user-agent": req.headers.get("user-agent") ?? "",
      },
      body: JSON.stringify({ ...fields, mobile: s.mobile, chat_token: s.token }),
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
  } catch {
    return jsonError(502, "UNAVAILABLE", "We couldn't send your details right now. Please try again.");
  }

  const data = (await res.json().catch(() => null)) as {
    message?: string;
    error?: { code?: string; message?: string; details?: { field?: string } };
  } | null;
  if (!res.ok) {
    // The token was refused (expired / already used): verify again.
    const expired = data?.error?.details?.field === "otp";
    return jsonError(
      res.status === 429 ? 429 : expired ? 401 : 400,
      expired ? "NOT_VERIFIED" : (data?.error?.code ?? "FAILED"),
      res.status === 429
        ? "Too many attempts. Please wait a minute and try again."
        : (data?.error?.message ?? "We couldn't send your details. Please try again."),
    );
  }

  const value = createSessionValue(s.mobile, { formDone: true, exp: s.exp });
  return Response.json(
    { ok: true, message: data?.message ?? "Thank you! Our team will call you shortly." },
    { headers: { "set-cookie": sessionCookie(value, secondsLeft(s)) } },
  );
}
