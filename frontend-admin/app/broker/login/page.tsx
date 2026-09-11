"use client";

/**
 * The broker's own login — a separate door onto the panel, and the start page
 * of the separately-installed StockEx Broker app.
 *
 *   - Locked to brokers SERVER-side (`portal: "broker"`): an admin's
 *     credentials are refused here before any session is issued.
 *   - Opening the installed app while already signed in goes straight to the
 *     dashboard, so the app never greets a signed-in broker with a form.
 *   - `?install=1` (the website's "Download Broker App") scrolls to and lights
 *     up the install block.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Eye, EyeOff, KeyRound, Loader2, LogIn, Rocket, ShieldCheck, Smartphone } from "lucide-react";
import { useAdminAuthStore } from "@/stores/authStore";
import { AdminAuthAPI, ApiError } from "@/lib/api";
import { InstallPWAButton } from "@/components/pwa/InstallPWAButton";

const schema = z.object({
  identifier: z.string().min(3, "Enter your broker code or email"),
  password: z.string().min(8, "Minimum 8 characters"),
  two_fa_code: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

const demoSchema = z.object({
  full_name: z.string().min(2, "Enter your full name").max(128),
  email: z.string().email("Invalid email"),
  mobile: z.string().regex(/^[6-9]\d{9}$/, "10-digit Indian mobile"),
  password: z
    .string()
    .min(8, "Min 8 chars")
    .regex(/[A-Z]/, "One uppercase")
    .regex(/[a-z]/, "One lowercase")
    .regex(/\d/, "One digit")
    .regex(/[^A-Za-z0-9]/, "One special char"),
});
type DemoValues = z.infer<typeof demoSchema>;

const GOLD_TEXT =
  "bg-gradient-to-r from-[#f7e7a1] via-[#d4af37] to-[#b8862b] bg-clip-text text-transparent";
const FIELD =
  "h-12 w-full rounded-xl border border-[#d4af37]/25 bg-black/40 px-4 text-[15px] text-[#f5ecd0] outline-none transition " +
  "placeholder:text-[#f5ecd0]/30 focus:border-[#d4af37]/70 focus:ring-2 focus:ring-[#d4af37]/20";

export default function BrokerLoginPage() {
  const router = useRouter();
  const login = useAdminAuthStore((s) => s.login);
  const admin = useAdminAuthStore((s) => s.admin);
  const hydrated = useAdminAuthStore((s) => s.hydrated);
  const setSession = useAdminAuthStore((s) => s.setSession);
  const [demoOpen, setDemoOpen] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [needs2fa, setNeeds2fa] = useState(false);
  const [fromInstallLink, setFromInstallLink] = useState(false);
  const appBlockRef = useRef<HTMLDivElement | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { identifier: "", password: "", two_fa_code: "" },
  });

  const demoForm = useForm<DemoValues>({
    resolver: zodResolver(demoSchema),
    defaultValues: { full_name: "", email: "", mobile: "", password: "" },
  });

  // The installed app opens HERE. A broker who is already signed in should
  // land on their dashboard, not be asked to sign in every time.
  useEffect(() => {
    if (hydrated && admin && String(admin.role).toUpperCase() === "BROKER") {
      router.replace("/dashboard");
    }
  }, [hydrated, admin, router]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("install") === "1") {
      setFromInstallLink(true);
      requestAnimationFrame(() =>
        appBlockRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
      );
    }
  }, []);

  async function onSubmit(values: FormValues) {
    try {
      await login(
        values.identifier.trim(),
        values.password,
        needs2fa ? values.two_fa_code?.trim() || undefined : undefined,
        "broker",
      );
      toast.success("Welcome back");
      router.push("/dashboard");
    } catch (err) {
      const code = (err as any)?.code;
      const msg = err instanceof ApiError ? err.message : "Login failed";
      if (code === "TWO_FA_REQUIRED" || /two-factor/i.test(msg)) {
        setNeeds2fa(true);
        toast.message("Enter the 6-digit code from your authenticator app");
        return;
      }
      toast.error(msg);
    }
  }

  async function onDemoSubmit(values: DemoValues) {
    try {
      const pair = await AdminAuthAPI.brokerDemoRegister(values);
      setSession(pair);
      toast.success("Demo broker ready — 🪙50,00,000 virtual float");
      router.push("/dashboard");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start broker demo");
    }
  }

  const busy = form.formState.isSubmitting;

  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-[#0b0906] text-[#f5ecd0]">
      {/* Ambient gold light — decorative only. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[420px] w-[620px] -translate-x-1/2 rounded-full bg-[#d4af37]/20 blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 right-[-10%] h-[360px] w-[420px] rounded-full bg-[#b8862b]/15 blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06] [background-image:radial-gradient(#d4af37_1px,transparent_1px)] [background-size:22px_22px]"
      />

      <div className="relative mx-auto flex min-h-[100svh] w-full max-w-[440px] flex-col justify-center px-5 py-10 sm:py-14">
        {/* Brand */}
        <div className="mb-7 flex flex-col items-center text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/broker-icon-192.png"
            alt="StockEx Broker"
            width={84}
            height={84}
            className="size-[84px] rounded-[26px] shadow-[0_10px_40px_-8px_rgba(212,175,55,0.55)] ring-1 ring-[#d4af37]/40"
          />
          <h1 className={`mt-5 font-display text-[28px] font-bold leading-tight tracking-tight ${GOLD_TEXT}`}>
            StockEx Broker
          </h1>
          <p className="mt-1.5 text-sm text-[#f5ecd0]/60">
            Sign in to manage your clients, positions and payments.
          </p>
        </div>

        {/* Card */}
        <div className="rounded-3xl border border-[#d4af37]/20 bg-gradient-to-b from-[#1a1510]/90 to-[#0f0c08]/90 p-5 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)] backdrop-blur-xl sm:p-7">
          <div className="mb-5 inline-flex items-center gap-1.5 rounded-full border border-[#d4af37]/30 bg-[#d4af37]/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-[#e9cf7a]">
            <ShieldCheck className="size-3.5" />
            Broker access only
          </div>

          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <label htmlFor="identifier" className="text-xs font-medium text-[#f5ecd0]/70">
                Broker code or email
              </label>
              <input
                id="identifier"
                autoComplete="username"
                autoCapitalize="characters"
                placeholder="BRK12345678"
                className={FIELD}
                {...form.register("identifier")}
              />
              {form.formState.errors.identifier && (
                <p className="text-xs text-red-400">{form.formState.errors.identifier.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="text-xs font-medium text-[#f5ecd0]/70">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPw ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className={`${FIELD} pr-12`}
                  {...form.register("password")}
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  aria-label={showPw ? "Hide password" : "Show password"}
                  className="absolute right-1.5 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-lg text-[#f5ecd0]/50 transition hover:bg-white/5 hover:text-[#e9cf7a]"
                >
                  {showPw ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
              {form.formState.errors.password && (
                <p className="text-xs text-red-400">{form.formState.errors.password.message}</p>
              )}
            </div>

            {needs2fa && (
              <div className="space-y-1.5">
                <label htmlFor="two_fa_code" className="flex items-center gap-1.5 text-xs font-medium text-[#f5ecd0]/70">
                  <KeyRound className="size-3.5" /> 6-digit authenticator code
                </label>
                <input
                  id="two_fa_code"
                  inputMode="numeric"
                  maxLength={6}
                  autoComplete="one-time-code"
                  placeholder="123456"
                  autoFocus
                  className={`${FIELD} tracking-[0.4em]`}
                  {...form.register("two_fa_code")}
                />
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="group relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-gradient-to-r from-[#f1d77e] via-[#d4af37] to-[#b8862b] text-[15px] font-semibold text-[#1a1206] shadow-[0_10px_30px_-10px_rgba(212,175,55,0.7)] transition active:scale-[0.99] disabled:opacity-70"
            >
              <span
                aria-hidden
                className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 group-hover:translate-x-full"
              />
              {busy ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          {/* The broker app. Separate install from the admin app — both can
              live on one phone. `fallback` so a broker sent here to install
              always has something to tap. */}
          <div
            id="broker-app"
            ref={appBlockRef}
            className={
              "mt-6 rounded-2xl border p-4 transition " +
              (fromInstallLink
                ? "border-[#d4af37]/70 bg-[#d4af37]/10 ring-2 ring-[#d4af37]/30"
                : "border-[#d4af37]/15 bg-black/30")
            }
          >
            <div className="mb-3 flex items-center gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#d4af37]/15 text-[#e9cf7a]">
                <Smartphone className="size-5" />
              </span>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-[#f5ecd0]">Get the Broker app</div>
                <p className="text-[11px] leading-snug text-[#f5ecd0]/55">
                  Installs as its own app — alongside the admin app if you use both.
                </p>
              </div>
            </div>
            <InstallPWAButton
              fallback
              className="h-11 border-[#d4af37]/40 bg-[#d4af37]/10 text-[#f1d77e] hover:bg-[#d4af37] hover:text-[#1a1206]"
            />
          </div>

          {/* Broker demo — a personal demo broker dashboard with 50L virtual
              float. Moved here from the admin login: it creates a BROKER. */}
          <div className="mt-4">
            {!demoOpen ? (
              <button
                type="button"
                onClick={() => setDemoOpen(true)}
                className="flex w-full items-center gap-3 rounded-2xl border border-[#d4af37]/15 bg-black/30 p-3 text-left transition hover:border-[#d4af37]/40"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#d4af37]/15 text-[#e9cf7a]">
                  <Rocket className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-[#f5ecd0]">Try a Broker Demo</span>
                  <span className="block text-[11px] text-[#f5ecd0]/55">
                    Free dashboard · 🪙50,00,000 virtual · switch to real anytime
                  </span>
                </span>
              </button>
            ) : (
              <form
                onSubmit={demoForm.handleSubmit(onDemoSubmit)}
                className="space-y-3 rounded-2xl border border-[#d4af37]/25 bg-black/30 p-4"
                noValidate
              >
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-[#f5ecd0]">Create broker demo</div>
                  <button
                    type="button"
                    onClick={() => setDemoOpen(false)}
                    className="text-xs text-[#f5ecd0]/50 hover:text-[#e9cf7a]"
                  >
                    Cancel
                  </button>
                </div>
                {(
                  [
                    ["full_name", "Full name", "text", "Your name"],
                    ["email", "Email", "email", "you@example.com"],
                    ["mobile", "Mobile", "tel", "9999900000"],
                    ["password", "Password", "password", "Abc@1234"],
                  ] as const
                ).map(([name, label, type, ph]) => (
                  <div key={name} className="space-y-1">
                    <label htmlFor={`demo_${name}`} className="text-xs font-medium text-[#f5ecd0]/70">
                      {label}
                    </label>
                    <input
                      id={`demo_${name}`}
                      type={type}
                      placeholder={ph}
                      maxLength={name === "mobile" ? 10 : undefined}
                      className={`${FIELD} h-11`}
                      {...demoForm.register(name)}
                    />
                    {demoForm.formState.errors[name] && (
                      <p className="text-xs text-red-400">{demoForm.formState.errors[name]?.message}</p>
                    )}
                  </div>
                ))}
                <button
                  type="submit"
                  disabled={demoForm.formState.isSubmitting}
                  className="flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-[#d4af37]/50 text-sm font-semibold text-[#f1d77e] transition hover:bg-[#d4af37] hover:text-[#1a1206] disabled:opacity-60"
                >
                  {demoForm.formState.isSubmitting ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Rocket className="size-4" />
                  )}
                  Start broker demo
                </button>
              </form>
            )}
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-[#f5ecd0]/45">
          Not a broker?{" "}
          <Link href="/login" className="font-medium text-[#e9cf7a] underline-offset-4 hover:underline">
            Admin login
          </Link>
        </p>
        <p className="mt-2 text-center text-[10px] text-[#f5ecd0]/30">
          Activity is logged. Rate-limiting is enforced server-side.
        </p>
      </div>
    </main>
  );
}
