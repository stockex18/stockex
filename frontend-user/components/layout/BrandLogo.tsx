"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { useBranding } from "@/lib/branding-context";
import { API_URL } from "@/lib/constants";

interface BrandLogoProps {
  href?: string | null;
  size?: "sm" | "md" | "lg";
  iconOnly?: boolean;
  className?: string;
}

// Whitelabel-aware brand mark.
// - When `BrandingProvider` has resolved a tenant brand (via ?ref= or
//   custom domain), we render the admin's uploaded logo + custom brand
//   name. The logo image is given the same size budget as the default
//   icon so layout doesn't shift.
// - When no branding is loaded, we fall back to the default
//   "🌱 StockEx Broker" wordmark — keeping the existing UX byte-
//   identical for the bulk of traffic that isn't on a branded link.
export function BrandLogo({ href = "/dashboard", size = "md", iconOnly = false, className }: BrandLogoProps) {
  const { branding } = useBranding();
  const customName = (branding?.brand_name ?? "").trim();
  // logo_url from the API is relative (e.g. "/static/branding/...");
  // prefix with API_URL so it loads from the backend host. Same logic
  // BrandingProvider uses for the favicon.
  const logoSrc = branding?.logo_url ? `${API_URL}${branding.logo_url}` : null;

  const sizes = {
    sm: { wrap: "text-lg", img: "size-7" },
    md: { wrap: "text-xl", img: "size-8" },
    lg: { wrap: "text-2xl", img: "size-10" },
  }[size];

  const content = (
    <span className={cn("inline-flex items-center gap-2 font-extrabold tracking-tight", sizes.wrap, className)}>
      <span className="shrink-0">
        {logoSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={logoSrc}
            alt={customName || "Logo"}
            className={cn(sizes.img, "rounded object-contain")}
          />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src="/app_new_icon.png"
            alt="StockEx"
            className={cn(sizes.img, "rounded object-contain")}
          />
        )}
      </span>
      {!iconOnly && (
        customName ? (
          <span className="text-foreground">{customName}</span>
        ) : (
          <span>
            <span className="text-foreground">Stock</span>
            <span className="text-primary">Ex</span>
          </span>
        )
      )}
    </span>
  );

  if (href) {
    return (
      <Link href={href} className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md">
        {content}
      </Link>
    );
  }
  return content;
}
