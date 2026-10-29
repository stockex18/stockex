"use client";

import { useEffect, useState, type ReactNode } from "react";
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

// Same choices, same values as the server's TradingExperience.
const EXPERIENCE = [
  { value: "NEW", label: "New to trading" },
  { value: "UNDER_1Y", label: "Less than 1 year" },
  { value: "Y1_3", label: "1–3 years" },
  { value: "OVER_3Y", label: "More than 3 years" },
];
const QUESTION_MAX = 500;
// A first check only; the server does the real validation.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="flex items-baseline justify-between text-xs font-medium text-[var(--sx-text-2)]">
        {label}
        {hint && <span className="font-normal text-[var(--sx-text-3)]">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

type Step = "details" | "code" | "done";

export function LeadForm({ tags, compact = false }: { tags: LeadTags; compact?: boolean }) {
  const [step, setStep] = useState<Step>("details");
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [city, setCity] = useState("");
  const [email, setEmail] = useState("");
  const [experience, setExperience] = useState("");
  const [question, setQuestion] = useState("");
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
  const locked = step === "code";
  // Field ids must differ between the two forms on the page.
  const idp = compact ? "lf2" : "lf1";

  // Checked before a code is sent, so nobody spends a code on a form the
  // server would only refuse.
  function firstProblem(): string | null {
    if (name.trim().length < 2) return "Please enter your full name.";
    if (!/^[6-9]\d{9}$/.test(mobile10)) return "Enter a valid 10-digit mobile number.";
    if (!EMAIL_RE.test(email.trim())) return "Enter a valid email address.";
    if (city.trim().length < 2) return "Please enter your city.";
    if (!experience) return "Please choose your trading experience.";
    if (!consent) return "Please allow us to contact you.";
    return null;
  }

  async function sendCode() {
    setError(null);
    setNotice(null);
    const problem = firstProblem();
    if (problem) {
      setError(problem);
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
        email: email.trim(),
        experience,
        question: question.trim(),
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

      <Field id={`${idp}-name`} label="Full name">
        <input
          id={`${idp}-name`}
          className="sx-input"
          placeholder="e.g. Ravi Kumar"
          autoComplete="name"
          value={name}
          maxLength={80}
          onChange={(e) => setName(e.target.value)}
          disabled={locked}
        />
      </Field>

      <Field id={`${idp}-mobile`} label="Mobile number">
        <div className="flex gap-2">
          <span className="sx-prefix">+91</span>
          <input
            id={`${idp}-mobile`}
            className="sx-input"
            placeholder="10-digit number"
            inputMode="numeric"
            autoComplete="tel-national"
            value={mobile}
            maxLength={14}
            onChange={(e) => setMobile(digits(e.target.value))}
            disabled={locked}
          />
        </div>
      </Field>

      <Field id={`${idp}-email`} label="Email address">
        <input
          id={`${idp}-email`}
          type="email"
          className="sx-input"
          placeholder="you@example.com"
          autoComplete="email"
          inputMode="email"
          value={email}
          maxLength={254}
          onChange={(e) => setEmail(e.target.value)}
          disabled={locked}
        />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field id={`${idp}-city`} label="City">
          <input
            id={`${idp}-city`}
            className="sx-input"
            placeholder="e.g. Indore"
            autoComplete="address-level2"
            value={city}
            maxLength={80}
            onChange={(e) => setCity(e.target.value)}
            disabled={locked}
          />
        </Field>
        <Field id={`${idp}-exp`} label="Trading experience">
          <select
            id={`${idp}-exp`}
            className="sx-input sx-select"
            required
            value={experience}
            onChange={(e) => setExperience(e.target.value)}
            disabled={locked}
          >
            <option value="" disabled>
              Select
            </option>
            {EXPERIENCE.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field id={`${idp}-question`} label="Your question" hint="Optional">
        <textarea
          id={`${idp}-question`}
          className="sx-input sx-textarea"
          placeholder="Anything you'd like us to answer on the call"
          rows={compact ? 2 : 3}
          value={question}
          maxLength={QUESTION_MAX}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={locked}
        />
      </Field>

      {/* Honeypot: hidden from people, irresistible to form-filling bots. */}
      <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label>
          Website
          <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
        </label>
      </div>

      {step === "code" && (
        <div className="flex flex-col gap-2">
          <label className="text-sm text-[var(--sx-text-2)]" htmlFor={`${idp}-code`}>
            Enter the code sent to +91 {mobile10}
          </label>
          <input
            id={`${idp}-code`}
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
