"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import type { AxiosError } from "axios";
import { api } from "@/lib/api";
import type { ApiErrorResponse, ApiResponse } from "@/types";

/** Ad-tracking tags carried from the landing URL to the lead. Kept for the
 *  session so a visitor who browses away and back still files under the
 *  campaign that first brought them. */
export type LeadTags = {
  ref_code?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  utm_term?: string;
};

const TAGS_KEY = "sx.start.tags";
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"] as const;
// Matches the server's per-number SMS cooldown, so "Resend" is only offered
// when the server would actually send one.
const RESEND_AFTER_SEC = 60;

export function useLeadTags(): LeadTags {
  const [tags, setTags] = useState<LeadTags>({});
  useEffect(() => {
    let saved: LeadTags = {};
    try {
      saved = JSON.parse(window.sessionStorage.getItem(TAGS_KEY) || "{}") || {};
    } catch {
      saved = {};
    }
    const qs = new URLSearchParams(window.location.search);
    const fresh: LeadTags = {};
    const ref = qs.get("ref");
    if (ref) fresh.ref_code = ref.trim().toUpperCase();
    for (const k of UTM_KEYS) {
      const v = qs.get(k);
      if (v) fresh[k] = v.trim();
    }
    const merged = { ...saved, ...fresh };
    try {
      window.sessionStorage.setItem(TAGS_KEY, JSON.stringify(merged));
    } catch {
      /* private mode: the tags still ride along for this page view */
    }
    setTags(merged);
  }, []);
  return tags;
}

function errorText(err: unknown): string {
  const ax = err as AxiosError<ApiErrorResponse>;
  return (
    ax?.response?.data?.error?.message ||
    (ax?.response?.status === 429 ? "Too many attempts. Please wait a minute and try again." : "") ||
    "Something went wrong. Please try again."
  );
}

const digits = (s: string) => s.replace(/\D/g, "");

type Step = "details" | "code" | "done";

export function LeadForm({ tags, compact = false }: { tags: LeadTags; compact?: boolean }) {
  const [step, setStep] = useState<Step>("details");
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [city, setCity] = useState("");
  const [consent, setConsent] = useState(true);
  const [website, setWebsite] = useState(""); // honeypot
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [wait, setWait] = useState(0);

  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  const mobile10 = digits(mobile).slice(-10);
  const detailsOk =
    name.trim().length >= 2 && /^[6-9]\d{9}$/.test(mobile10) && city.trim().length >= 2 && consent;

  async function sendCode() {
    setError(null);
    setNotice(null);
    if (!detailsOk) {
      setError(
        !consent
          ? "Please allow us to contact you."
          : !/^[6-9]\d{9}$/.test(mobile10)
            ? "Enter a valid 10-digit mobile number."
            : "Please fill in your name and city.",
      );
      return;
    }
    setBusy(true);
    try {
      const res = await api.post<ApiResponse<{ sent: boolean }>>("/leads/otp", { mobile: mobile10 });
      setNotice(res.data?.message || "Code sent");
      setStep("code");
      setCode("");
      setWait(RESEND_AFTER_SEC);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setError(null);
    if (!/^\d{4,8}$/.test(code)) {
      setError("Enter the code we sent by SMS.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/leads", {
        full_name: name.trim(),
        mobile: mobile10,
        city: city.trim(),
        otp: code,
        website,
        ...tags,
      });
      setStep("done");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const registerHref = (() => {
    const qs = new URLSearchParams();
    if (tags.ref_code) qs.set("ref", tags.ref_code);
    if (name.trim()) qs.set("name", name.trim());
    if (mobile10) qs.set("mobile", mobile10);
    const s = qs.toString();
    return s ? `/register?${s}` : "/register";
  })();

  if (step === "done") {
    return (
      <div className="flex flex-col items-center gap-4 py-6 text-center" role="status">
        <CheckCircle2 className="h-12 w-12 text-[var(--sx-ok)]" />
        <div>
          <p className="text-xl font-semibold">Thank you, {name.trim().split(" ")[0]}!</p>
          <p className="mt-1 text-sm text-[var(--sx-text-2)]">
            Our team will call you on {mobile10.slice(0, 2)}******{mobile10.slice(-2)} shortly.
          </p>
        </div>
        <p className="text-sm text-[var(--sx-text-2)]">Don&apos;t want to wait? Start practising right now.</p>
        <Link href={registerHref} className="sx-btn sx-btn-primary w-full">
          Open your free demo account
        </Link>
      </div>
    );
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (step === "details") void sendCode();
        else void submit();
      }}
      noValidate
    >
      {!compact && (
        <div className="mb-1">
          <p className="text-lg font-semibold">Request a free callback</p>
          <p className="text-sm text-[var(--sx-text-2)]">Tell us a little about you. We&apos;ll call you back.</p>
        </div>
      )}

      <label className="sr-only" htmlFor={`lf-name-${compact}`}>Full name</label>
      <input
        id={`lf-name-${compact}`}
        className="sx-input"
        placeholder="Full name"
        autoComplete="name"
        value={name}
        maxLength={80}
        onChange={(e) => setName(e.target.value)}
        disabled={step === "code"}
      />

      <label className="sr-only" htmlFor={`lf-mobile-${compact}`}>Mobile number</label>
      <div className="flex gap-2">
        <span className="sx-prefix">+91</span>
        <input
          id={`lf-mobile-${compact}`}
          className="sx-input"
          placeholder="10-digit mobile number"
          inputMode="numeric"
          autoComplete="tel-national"
          value={mobile}
          maxLength={14}
          onChange={(e) => setMobile(digits(e.target.value))}
          disabled={step === "code"}
        />
      </div>

      <label className="sr-only" htmlFor={`lf-city-${compact}`}>City</label>
      <input
        id={`lf-city-${compact}`}
        className="sx-input"
        placeholder="City"
        autoComplete="address-level2"
        value={city}
        maxLength={80}
        onChange={(e) => setCity(e.target.value)}
        disabled={step === "code"}
      />

      {/* Honeypot: hidden from people, irresistible to form-filling bots. */}
      <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label>
          Website
          <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
        </label>
      </div>

      {step === "code" && (
        <div className="flex flex-col gap-2">
          <label className="text-sm text-[var(--sx-text-2)]" htmlFor={`lf-code-${compact}`}>
            Enter the code sent to +91 {mobile10}
          </label>
          <input
            id={`lf-code-${compact}`}
            className="sx-input text-center text-lg tracking-[0.5em]"
            placeholder="••••"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            maxLength={8}
            autoFocus
            onChange={(e) => setCode(digits(e.target.value))}
          />
          <div className="flex items-center justify-between text-xs text-[var(--sx-text-3)]">
            <button
              type="button"
              className="underline-offset-2 hover:underline"
              onClick={() => {
                setStep("details");
                setError(null);
                setNotice(null);
              }}
            >
              Change details
            </button>
            {wait > 0 ? (
              <span>Resend in {wait}s</span>
            ) : (
              <button type="button" className="text-[var(--sx-accent-light)] hover:underline" onClick={() => void sendCode()}>
                Resend code
              </button>
            )}
          </div>
        </div>
      )}

      {step === "details" && (
        <label className="flex items-start gap-2 text-xs text-[var(--sx-text-2)]">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-[var(--sx-accent)]"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          <span>I agree to be contacted by StockEx by call, SMS or WhatsApp.</span>
        </label>
      )}

      {notice && step === "code" && !error && <p className="text-xs text-[var(--sx-ok)]">{notice}</p>}
      {error && (
        <p className="text-sm text-[var(--sx-bad)]" role="alert">
          {error}
        </p>
      )}

      <button type="submit" className="sx-btn sx-btn-primary mt-1 w-full" disabled={busy}>
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        {step === "details" ? "Get verification code" : "Verify & request callback"}
      </button>

      <p className="flex items-center justify-center gap-1.5 text-xs text-[var(--sx-text-3)]">
        <ShieldCheck className="h-3.5 w-3.5" /> Your number is only used to contact you about StockEx.
      </p>
    </form>
  );
}
