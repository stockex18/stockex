import type { Metadata } from "next";
import "./start.css";
import { StartLanding } from "@/components/start/StartLanding";

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
  return <StartLanding />;
}
