"use client";

import { Suspense, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Link from "next/link";
import { TrendingUp } from "lucide-react";
import { useBranding } from "@/lib/branding-context";
import { StockExLogo } from "@/components/StockExLogo";
import { API_URL } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { SmokeyBackground } from "@/components/ui/smokey-background";

/**
 * Tenant brand tile — ALWAYS renders the Sprout glyph on the brand
 * gradient so something is visible no matter what.  When the admin
 * has uploaded a logo AND the image successfully loads, it's
 * rendered on top of the Sprout (covers it).  If the image fails
 * to load or hasn't been configured, the user still sees the
 * original Sprout-on-gradient look from before the logo feature
 * existed.  This guarantees zero blank tiles in production.
 */
function BrandTile({
  logoSrc,
  alt,
  size = "lg",
}: {
  logoSrc: string | null;
  alt: string;
  size?: "sm" | "lg";
}) {
  const [imgLoaded, setImgLoaded] = useState(false);
  const sizeCls = size === "lg" ? "size-16" : "size-10";
  const iconCls = size === "lg" ? "size-8" : "size-5";
  return (
    <div
      className={cn(
        "relative grid place-items-center overflow-hidden rounded-2xl bg-gradient-to-br from-primary to-primary/80 text-primary-foreground shadow-lg shadow-primary/30 ring-2 ring-primary/20",
        sizeCls,
      )}
    >
      <TrendingUp className={iconCls} strokeWidth={2.5} />
      {logoSrc && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logoSrc}
          alt={alt}
          onLoad={() => setImgLoaded(true)}
          onError={() => setImgLoaded(false)}
          className={cn(
            "absolute inset-0 rounded-2xl bg-card object-contain p-1 transition-opacity",
            imgLoaded ? "opacity-100" : "opacity-0",
          )}
        />
      )}
    </div>
  );
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={<main className="min-h-screen w-full bg-background" />}
    >
      <AuthLayoutInner>{children}</AuthLayoutInner>
    </Suspense>
  );
}

function AuthLayoutInner({ children }: { children: React.ReactNode }) {
  const searchParams = useSearchParams();
  const pathname = usePathname() || "";
  const { branding } = useBranding();
  const tenantName = (branding?.brand_name ?? "").trim();
  // Tenant logo uploaded by admin / super-admin via /settings/branding.
  // Mirrors BrandLogo.tsx: paths are server-relative, so prefix API_URL.
  // Falls back to the default Sprout glyph when no logo is configured.
  const logoSrc = branding?.logo_url
    ? `${API_URL}${branding.logo_url}`
    : null;

  const isImpersonating = !!(
    searchParams?.get("access") && searchParams?.get("refresh")
  );

  // Show the Login/Register tab bar only on those two routes; hide on
  // forgot-password / 2fa / impersonation handoff so those pages keep a
  // clean single-purpose layout.
  const showTabs = pathname === "/login" || pathname === "/register";
  const onRegister = pathname === "/register";

  if (isImpersonating) {
    return (
      <main className="grid min-h-screen w-full place-items-center bg-background">
        {children}
      </main>
    );
  }

  const tabs = showTabs ? (
    <div className="mb-6 inline-flex w-full rounded-xl bg-muted/40 p-1 ring-1 ring-inset ring-border/40">
      <Link
        href="/login"
        className={cn(
          "flex-1 rounded-lg px-3 py-2 text-center text-sm font-semibold transition-all",
          !onRegister
            ? "bg-background text-foreground shadow-sm"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        Login
      </Link>
      <Link
        href="/register"
        className={cn(
          "flex-1 rounded-lg px-3 py-2 text-center text-sm font-semibold transition-all",
          onRegister
            ? "bg-background text-foreground shadow-sm"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        Register
      </Link>
    </div>
  ) : null;

  const brandMark = (
    <Link href="/" className="mb-6 inline-flex items-center gap-2.5">
      {logoSrc ? (
        <>
          <BrandTile logoSrc={logoSrc} alt={tenantName || "Logo"} size="sm" />
          <span className="text-lg font-bold tracking-tight text-foreground">
            {tenantName || "StockEx"}
          </span>
        </>
      ) : (
        // Same mark the nav bar renders. This used to point at
        // /stockex-logo.svg — a different asset from the nav's — so the
        // login page showed one logo and the rest of the site another.
        <StockExLogo className="h-14 w-auto object-contain" />
      )}
    </Link>
  );

  // `mp-scope` activates the marketing palette on the auth pages.
  //
  // These pages already style themselves with `mp-*` utilities (the login
  // form alone has 13 `bg-mp-primary` usages), but nothing ever set the
  // scope class — so `--mp-primary` was undefined, `rgb(var(--mp-primary))`
  // was an invalid colour, and every one of those declarations was being
  // dropped. What rendered was the trading app's emerald `--primary`
  // showing through, not the marketing green anyone intended. Setting the
  // scope makes the existing classes resolve, which also lands these pages
  // on the same ink/lime system as the rest of the site. The trading app's
  // own tokens (`bg-card`, `text-foreground`, `bg-muted/40`) are untouched
  // — `mp-scope` doesn't redeclare them.
  return (
    <main className="mp-scope grid min-h-screen w-full place-items-center bg-gradient-to-br from-muted/40 via-background to-muted/40 p-4 sm:p-6">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-3xl border border-border/50 bg-card shadow-2xl shadow-primary/10 lg:grid-cols-2">
        {/* ── Left panel (desktop) — animated smoke shader ────────── */}
        <div className="mp-dark relative hidden flex-col justify-end gap-8 overflow-hidden bg-[#101210] p-10 text-white lg:flex">
          {/* Interactive WebGL smoke, tinted to the site's single accent */}
          {/* Lighter step of the brand blue — the shader paints onto a near
              black panel, where #003E85 itself would barely register. */}
          <SmokeyBackground color="#4D94E6" backdropBlurAmount="sm" />
          {/* Bottom fade so the tagline stays legible over the smoke */}
          <div
            className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/50 via-black/10 to-transparent"
            aria-hidden
          />

          <div className="relative z-10">
            <p className="text-sm font-medium text-white/80">You can easily</p>
            <h2 className="mt-2 max-w-sm text-2xl font-bold leading-snug text-white xl:text-3xl">
              Trade Indian markets with clarity, speed and control.
            </h2>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-white/75">
              Equity, F&amp;O, Commodities, IPOs and Mutual Funds — all from one
              account on NSE, BSE &amp; MCX.
            </p>
          </div>

          <div className="relative z-10 text-xs text-white/60">
            &copy; {new Date().getFullYear()} {tenantName || "StockEx"} · All
            rights reserved
          </div>
        </div>

        {/* ── Right form panel ───────────────────────────────────── */}
        <div className="relative bg-card p-6 sm:p-10">
          {brandMark}
          {tabs}
          {children}
        </div>
      </div>
    </main>
  );
}
