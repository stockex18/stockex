"use client";

import Link from "next/link";
import { StockExLogo } from "@/components/StockExLogo";
import { useBranding } from "@/lib/branding-context";
import { API_URL } from "@/lib/constants";

/**
 * Footer brand mark. Split out of MarketingFooter (a Server Component) purely
 * so the branding context — which is client-side — can be read without
 * pushing the whole footer, its sitemap and its disclaimer into the client
 * bundle.
 *
 * Mirrors the nav bar's brand block exactly (components/landing/navbar.jsx):
 * a white-label tenant with an uploaded logo gets its own mark + name,
 * everyone else falls back to `StockExLogo`. The footer used to hardcode
 * `/stockex-logo.svg` — a different asset from the nav's, so header and
 * footer showed two different logos on the same page, and tenant branding
 * never reached the footer at all.
 */
export function MarketingFooterBrand() {
  const { branding } = useBranding();
  const customName = (branding?.brand_name ?? "").trim();
  const logoSrc = branding?.logo_url ? `${API_URL}${branding.logo_url}` : null;

  return (
    <Link href="/" className="inline-flex items-center gap-3">
      {logoSrc ? (
        <>
          <span className="grid size-12 place-items-center rounded-2xl bg-white/[0.08]">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={logoSrc}
              alt={customName || "Logo"}
              className="size-9 rounded-xl object-contain"
              loading="lazy"
              decoding="async"
            />
          </span>
          <span className="font-display text-2xl font-bold tracking-tight text-mp-text">
            {customName || "StockEx"}
          </span>
        </>
      ) : (
        // Same asset the nav bar renders, so it's already in cache by the
        // time the footer scrolls into view.
        <StockExLogo className="h-14 w-auto object-contain" alt={customName || "StockEx"} />
      )}
    </Link>
  );
}
