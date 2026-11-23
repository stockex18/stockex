/**
 * /start — campaign landing page.
 *
 * Built at the request of the Digital Marketing team as the destination for
 * paid ads and WhatsApp campaigns. It is deliberately separate from the
 * homepage: one focused page with two actions — open a free account, or
 * request a callback — and no navigation to wander off through.
 *
 * - Leads from the callback form are verified by SMS code and saved through
 *   `POST /api/v1/leads`; the team works them from the admin panel's Leads page.
 * - The `ref` and `utm_*` query parameters are captured with each lead, so
 *   every enquiry can be traced back to the campaign that produced it.
 * - Content, copy and layout changes should be agreed with the Digital
 *   Marketing team before they ship, as they are tied to live campaigns.
 */
import type { Metadata } from "next";
import Script from "next/script";
import "./start.css";
import { StartLanding } from "@/components/start/StartLanding";

// Google Ads tag (Digital Marketing). Loaded on /start only, not site-wide:
// this is where the paid ads land, and the trading app stays untracked.
const GOOGLE_ADS_ID = "AW-10957161727";

// The ad / WhatsApp landing page. Kept out of search results on purpose: the
// homepage is the page that should rank, and a campaign page indexed next to
// it only competes with it.
export const metadata: Metadata = {
  title: "Open your free StockEx account",
  description:
    "Trade NSE, F&O, MCX, Forex and Crypto from one app. Practise free on a demo account, or ask us to call you back.",
  robots: { index: false, follow: false },
  openGraph: {
    title: "Trade NSE, F&O, MCX, Forex & Crypto from one app — StockEx",
    description: "Practise free on a demo account, then go live when you are ready.",
    images: ["/images/platform_img.png"],
  },
};

export default function StartPage() {
  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtm.js?id=${GOOGLE_ADS_ID}`}
        strategy="afterInteractive"
      />
      {/* Google's snippet as given: no gtag('config') — the tag's settings
          live in Google Ads, and a config call here would double-count. */}
      <Script id="google-ads-tag" strategy="afterInteractive">
        {`window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());`}
      </Script>
      <StartLanding />
    </>
  );
}
