"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useBranding } from "@/lib/branding-context";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Check, Eye, EyeOff, X, User, Mail, Phone, Lock, Building2, MapPin, Gift, ShieldCheck } from "lucide-react";
import { AuthAPI, ApiError, type BrokerOption } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import { BrokerPicker } from "@/components/common/BrokerPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { brokerTitle, cn } from "@/lib/utils";

const schema = z.object({
  full_name: z.string().min(2, "Enter your full name").max(128),
  email: z.string().email("Invalid email"),
  mobile: z
    .string()
    .regex(/^[6-9]\d{9}$/, "10-digit Indian mobile starting 6/7/8/9"),
  password: z
    .string()
    .min(8, "Minimum 8 characters")
    .regex(/[A-Z]/, "Must contain an uppercase letter")
    .regex(/[a-z]/, "Must contain a lowercase letter")
    .regex(/\d/, "Must contain a digit")
    .regex(/[^A-Za-z0-9]/, "Must contain a special character (e.g. @, #, $)"),
  // Optional at the schema level: a referral signup inherits the referrer's
  // broker, so there is nothing to pick. Enforced in onSubmit when there is
  // no referral code.
  broker_id: z.string().optional().default(""),
  // The code texted to the mobile. Only checked when the server asks for one.
  otp: z.string().optional().default(""),
});
type FormValues = z.infer<typeof schema>;

const PWD_RULES = [
  { id: "len",   label: "At least 8 characters",       test: (s: string) => s.length >= 8 },
  { id: "upper", label: "One uppercase letter (A–Z)",  test: (s: string) => /[A-Z]/.test(s) },
  { id: "lower", label: "One lowercase letter (a–z)",  test: (s: string) => /[a-z]/.test(s) },
  { id: "digit", label: "One number (0–9)",            test: (s: string) => /\d/.test(s) },
  { id: "spec",  label: "One special character (@, #, $…)", test: (s: string) => /[^A-Za-z0-9]/.test(s) },
];

type Strength = {
  score: number;
  label: string;
  chipClass: string;
  barClass: string;
};

function passwordStrength(pwd: string): Strength {
  const score = PWD_RULES.reduce((n, r) => n + (r.test(pwd) ? 1 : 0), 0);
  if (!pwd) {
    return { score: 0, label: "", chipClass: "", barClass: "bg-muted" };
  }
  if (score <= 2) {
    return {
      score,
      label: "Weak",
      chipClass: "bg-sell/15 text-sell ring-1 ring-sell/30",
      barClass: "bg-sell",
    };
  }
  if (score <= 4) {
    return {
      score,
      label: "Medium",
      chipClass: "bg-atm/20 text-atm ring-1 ring-atm/40",
      barClass: "bg-atm",
    };
  }
  return {
    score,
    label: "Strong",
    chipClass: "bg-buy/15 text-buy ring-1 ring-buy/30",
    barClass: "bg-buy",
  };
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterPageInner />
    </Suspense>
  );
}

function RegisterPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Referral code — prefilled from ?ref= but editable via the form field so a
  // user can type a friend's code (short 6-digit number or the full user_code).
  const [refCode, setRefCode] = useState(
    (searchParams?.get("ref") || "").trim().toUpperCase(),
  );
  // Demo signup mode (?demo=1 from the login "Try Demo" button): same form +
  // broker pick, but creates a PERSONAL demo account and logs in immediately.
  const demo = (searchParams?.get("demo") || "") === "1";
  const setSession = useAuthStore((s) => s.setSession);
  // On a tenant custom domain (e.g. stockcafe.live) the URL has no ?ref=,
  // so fall back to the resolved brand's admin code. Belt-and-suspenders
  // alongside the backend's Origin/Referer detection — covers the case
  // where a proxy strips the Origin header.
  const { branding } = useBranding();
  const [showPwd, setShowPwd] = useState(false);
  const [pwdFocused, setPwdFocused] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState<BrokerOption | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  // Referral signups inherit the referrer's broker, so the picker is hidden —
  // unless the backend rejects the code and asks for an explicit pick.
  const [forcePicker, setForcePicker] = useState(false);
  const showBrokerPicker = !refCode || forcePicker;

  // Does signup want a texted code? Asked of the server, not assumed: with the
  // check off nothing below renders and this page behaves exactly as before.
  const { data: signupCfg } = useQuery({
    queryKey: ["auth", "signup-config"],
    queryFn: () => AuthAPI.signupConfig(),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const needOtp = !!signupCfg?.sms_otp;
  const [otpSentTo, setOtpSentTo] = useState<string | null>(null);
  const [otpSending, setOtpSending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", email: "", mobile: "", password: "", broker_id: "", otp: "" },
    mode: "onChange",
  });
  const brokerId = form.watch("broker_id");
  const mobileVal = form.watch("mobile") || "";
  // A code belongs to the number it was sent to. Change the number and the
  // code in the box is for someone else, so the box goes away.
  const codeIsForThisNumber = otpSentTo !== null && otpSentTo === mobileVal;
  useEffect(() => {
    if (otpSentTo !== null && otpSentTo !== mobileVal) form.setValue("otp", "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mobileVal, otpSentTo]);

  async function sendCode() {
    if (!/^[6-9]\d{9}$/.test(mobileVal)) {
      form.setError("mobile", { message: "Enter a valid 10-digit mobile first" });
      return;
    }
    setOtpSending(true);
    try {
      const r = await AuthAPI.requestSignupOtp(mobileVal);
      setOtpSentTo(mobileVal);
      setCooldown(60);
      toast.success(r?.message || "Verification code sent");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not send the code");
    } finally {
      setOtpSending(false);
    }
  }

  const pwd = form.watch("password") || "";
  const strength = passwordStrength(pwd);
  // All five rules met and the field left alone → the checklist has nothing
  // left to teach, so it folds away instead of pushing the form down a screen.
  const showRules =
    pwdFocused || (pwd.length > 0 && !PWD_RULES.every((r) => r.test(pwd)));

  async function onSubmit(values: FormValues) {
    // Broker is REQUIRED (unless a referral link already places the user under
    // its referrer's broker). Block submit until one is picked.
    if (!refCode && !values.broker_id) {
      form.setError("broker_id", { message: "Please choose your broker" });
      return;
    }
    if (needOtp) {
      if (!codeIsForThisNumber) {
        form.setError("otp", { message: "Send a verification code to this mobile first" });
        return;
      }
      if (!/^\d{4}$/.test(values.otp || "")) {
        form.setError("otp", { message: "Enter the 4-digit code from the SMS" });
        return;
      }
    }
    try {
      const body = {
        full_name: values.full_name,
        email: values.email,
        mobile: values.mobile,
        password: values.password,
        broker_id: values.broker_id,
        otp: needOtp ? values.otp : undefined,
        referral_code: refCode || branding?.user_code || undefined,
      };
      // Signing up opens a DEMO account and logs straight in — nobody becomes
      // a real client of the book by filling a form. They try the platform on
      // virtual money and turn real deliberately, from Profile → Switch to
      // Real Account, which is the moment their admin is told.
      //
      // The server enforces this on both routes, so the only difference left
      // between them is which one an older build happens to call.
      const pair = demo
        ? await AuthAPI.demoRegister(body)
        : await AuthAPI.register(body);
      setSession(pair as any);
      toast.success("Demo account ready — 🪙10,00,000 virtual balance");
      router.push("/dashboard");
      return;
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Registration failed";
      // A referral link hides the picker. If the code turned out not to resolve
      // to a referrer, the backend asks for a broker — reveal the picker so the
      // user isn't stuck on an error they can't act on.
      if (msg.toLowerCase().includes("broker")) setForcePicker(true);
      toast.error(msg);
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header — hidden on mobile (tab bar already says "Register"),
          visible on desktop where the tab bar is absent. */}
      <div className="hidden space-y-1.5 lg:block">
        <h2 className="text-3xl font-bold tracking-tight">
          {demo ? "Create demo account" : "Create account"}
        </h2>
        <p className="text-sm text-muted-foreground">
          {demo
            ? "Practice with 🪙10,00,000 virtual money — switch to a real account anytime."
            : "Open your trading account in 60 seconds."}
        </p>
      </div>

      {/* Demo banner — always visible (mobile too) so the user knows this signup
          is a risk-free practice account. */}
      {demo && (
        <div className="flex items-start gap-2 rounded-xl border border-primary/40 bg-primary/5 px-3 py-2.5">
          <span className="text-base leading-none">🪙</span>
          <span className="text-[11px] leading-snug text-muted-foreground">
            <span className="font-bold text-foreground">Demo account</span> — pre-funded with{" "}
            <span className="font-bold text-foreground">🪙10,00,000</span> virtual balance. No real
            money. You can convert it to a real account anytime from your profile.
          </span>
        </div>
      )}

      {/* Form */}
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3.5 sm:space-y-5">
        {/* Full name */}
        <div className="space-y-1.5">
          <Label htmlFor="full_name" className="text-sm font-semibold text-foreground">Full name</Label>
          <div className="relative">
            <User className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="full_name"
              placeholder="Rohan Sharma"
              autoComplete="name"
              className="h-10 rounded-xl border-border/60 bg-muted/40 pl-10 text-sm transition-colors focus:border-primary/50 focus:bg-background sm:h-12"
              {...form.register("full_name")}
            />
          </div>
          {form.formState.errors.full_name && (
            <p className="text-xs text-destructive">{form.formState.errors.full_name.message}</p>
          )}
        </div>

        {/* Email + Mobile */}
        <div className="grid grid-cols-2 gap-3 sm:gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-sm font-semibold text-foreground">Email</Label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground sm:left-3.5 sm:size-4" />
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                className="h-10 rounded-xl border-border/60 bg-muted/40 pl-9 text-sm transition-colors focus:border-primary/50 focus:bg-background sm:h-12 sm:pl-10"
                {...form.register("email")}
              />
            </div>
            {form.formState.errors.email && (
              <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mobile" className="text-sm font-semibold text-foreground">Mobile</Label>
            <div className="relative">
              <Phone className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground sm:left-3.5 sm:size-4" />
              <Input
                id="mobile"
                inputMode="numeric"
                maxLength={10}
                autoComplete="tel"
                placeholder="9999900000"
                className="h-10 rounded-xl border-border/60 bg-muted/40 pl-9 text-sm transition-colors focus:border-primary/50 focus:bg-background sm:h-12 sm:pl-10"
                {...form.register("mobile")}
              />
            </div>
            {form.formState.errors.mobile && (
              <p className="text-xs text-destructive">{form.formState.errors.mobile.message}</p>
            )}
          </div>
        </div>

        {/* Mobile verification — only when the server asks for it. */}
        {needOtp && (
          <div className="space-y-2 rounded-xl border border-primary/25 bg-primary/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                <ShieldCheck className="size-4 text-primary" />
                Verify your mobile
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={sendCode}
                disabled={otpSending || cooldown > 0 || !/^[6-9]\d{9}$/.test(mobileVal)}
                className="h-8 shrink-0 rounded-lg px-3 text-xs"
              >
                {otpSending
                  ? "Sending…"
                  : cooldown > 0
                    ? `Resend in ${cooldown}s`
                    : codeIsForThisNumber
                      ? "Resend code"
                      : "Send code"}
              </Button>
            </div>
            {codeIsForThisNumber ? (
              <>
                <Input
                  id="otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={4}
                  placeholder="4-digit code"
                  className="h-10 rounded-xl border-border/60 bg-background text-center text-base tracking-[0.4em]"
                  {...form.register("otp")}
                />
                <p className="text-[11px] text-muted-foreground">
                  Sent by SMS to {mobileVal.slice(0, 2)}******{mobileVal.slice(-2)}. It is valid for 5 minutes.
                </p>
              </>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                We will text a 4-digit code to the mobile above. Enter it here to continue.
              </p>
            )}
            {form.formState.errors.otp && (
              <p className="text-xs text-destructive">{form.formState.errors.otp.message}</p>
            )}
          </div>
        )}

        {/* Password */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password" className="text-sm font-semibold text-foreground">Password</Label>
            {pwd && (
              <span
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                  strength.chipClass,
                )}
              >
                {strength.label}
              </span>
            )}
          </div>

          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="password"
              type={showPwd ? "text" : "password"}
              placeholder="e.g. Abc@1234"
              autoComplete="new-password"
              className="h-10 rounded-xl border-border/60 bg-muted/40 pl-10 pr-12 text-sm transition-colors focus:border-primary/50 focus:bg-background sm:h-12"
              {...form.register("password", {
                onBlur: () => setPwdFocused(false),
              })}
              onFocus={() => setPwdFocused(true)}
            />
            <button
              type="button"
              onClick={() => setShowPwd((v) => !v)}
              aria-label={showPwd ? "Hide password" : "Show password"}
              aria-pressed={showPwd}
              tabIndex={-1}
              className="absolute inset-y-0 right-0 flex items-center px-3.5 text-muted-foreground transition-colors hover:text-foreground"
            >
              {showPwd ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>

          {/* Strength bar */}
          <div className="flex gap-1.5" aria-hidden>
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className={cn(
                  "h-1 flex-1 rounded-full transition-colors duration-300 sm:h-1.5",
                  i < strength.score ? strength.barClass : "bg-muted",
                )}
              />
            ))}
          </div>

          {/* Live rules checklist — always 2-col so it stays compact on mobile */}
          {showRules && (
            <ul
              className="grid grid-cols-2 gap-1.5 rounded-xl border border-border/40 bg-muted/20 p-3 sm:gap-2 sm:p-3.5"
              aria-live="polite"
            >
              {PWD_RULES.map((r) => {
                const ok = r.test(pwd);
                return (
                  <li
                    key={r.id}
                    className={cn(
                      "flex items-center gap-1.5 text-[11px] transition-colors sm:text-xs",
                      ok ? "text-buy" : "text-muted-foreground",
                    )}
                  >
                    <span
                      className={cn(
                        "grid size-3.5 shrink-0 place-items-center rounded-full transition-colors sm:size-4",
                        ok ? "bg-buy/15" : "bg-muted",
                      )}
                    >
                      {ok ? (
                        <Check className="size-2 sm:size-2.5" strokeWidth={3} />
                      ) : (
                        <X className="size-2 text-muted-foreground sm:size-2.5" strokeWidth={3} />
                      )}
                    </span>
                    <span className="leading-tight">{r.label}</span>
                  </li>
                );
              })}
            </ul>
          )}

          {form.formState.errors.password && !showRules && (
            <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
          )}
        </div>

        {/* Referral code — optional. Prefilled from the ?ref= link but editable
            so a user can type a friend's 6-digit code (or full user code). */}
        <div className="space-y-1.5">
          <Label htmlFor="ref" className="text-sm font-semibold text-foreground">
            Referral code <span className="font-normal text-muted-foreground">(optional)</span>
          </Label>
          <div className="relative">
            <Gift className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="ref"
              inputMode="text"
              placeholder="e.g. 048213"
              value={refCode}
              onChange={(e) => setRefCode(e.target.value.trim().toUpperCase())}
              className="h-10 rounded-xl border-border/60 bg-muted/40 pl-10 text-sm transition-colors focus:border-primary/50 focus:bg-background sm:h-12"
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Have a friend&apos;s code? Enter it to join under them and reward them.
          </p>
        </div>

        {/* Broker selection — browse all, or search by city or PIN code, and
            pick who you join under. Skipped
            on a referral link: the referrer's own broker/admin chain is
            inherited, so the new user lands in the referrer's pool. */}
        {!showBrokerPicker ? (
          <div className="flex items-start gap-2 rounded-xl border border-primary/40 bg-primary/5 px-3 py-2.5">
            <Building2 className="mt-0.5 size-3.5 shrink-0 text-primary" />
            <span className="text-[11px] leading-snug text-muted-foreground">
              Joining via referral <span className="font-mono font-bold text-foreground">{refCode}</span> — you&apos;ll be
              placed under the same broker as the person who referred you.
            </span>
          </div>
        ) : (
        <div className="space-y-1.5">
          <Label className="text-sm font-semibold text-foreground">Choose your broker</Label>
          {selectedBroker && !pickerOpen ? (
            <div className="flex items-center justify-between gap-2 rounded-xl border border-primary/40 bg-primary/5 px-3 py-2.5">
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 text-sm font-bold">
                  <Building2 className="size-3.5 shrink-0 text-primary" /> {brokerTitle(selectedBroker).title}
                </span>
                {brokerTitle(selectedBroker).subtitle && (
                  <span className="block pl-5 text-[11px] text-muted-foreground">
                    {brokerTitle(selectedBroker).subtitle}
                  </span>
                )}
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                  {selectedBroker.city && (
                    <span className="inline-flex items-center gap-0.5"><MapPin className="size-3" /> {selectedBroker.city}</span>
                  )}
                  {selectedBroker.pincode && (
                    <span className="font-mono">{selectedBroker.pincode}</span>
                  )}
                  <span className="font-mono">{selectedBroker.user_code}</span>
                </span>
              </span>
              <button type="button" onClick={() => setPickerOpen(true)} className="shrink-0 text-xs font-bold text-primary hover:opacity-80">
                Change
              </button>
            </div>
          ) : (
            <BrokerPicker
              value={brokerId || null}
              onSelect={(b) => {
                form.setValue("broker_id", b.id, { shouldValidate: true });
                setSelectedBroker(b);
                setPickerOpen(false);
              }}
            />
          )}
          {form.formState.errors.broker_id && (
            <p className="text-xs text-destructive">{form.formState.errors.broker_id.message}</p>
          )}
        </div>
        )}

        <Button
          type="submit"
          className="h-10 w-full rounded-xl border-0 bg-[#141714] text-sm font-semibold text-white transition-colors hover:bg-[#2C312C] sm:h-12"
          loading={form.formState.isSubmitting}
        >
          {demo ? "Start demo — 🪙10,00,000 free" : "Create account"}
        </Button>
      </form>

      {/* Footer */}
      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-primary hover:text-primary/80">
          Sign in
        </Link>
      </p>
    </div>
  );
}
