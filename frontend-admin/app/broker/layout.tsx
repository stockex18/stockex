import type { Metadata, Viewport } from "next";

// Everything under /broker belongs to the BROKER app, not the admin app:
// its own manifest (so it installs as a second app beside the admin one),
// its own iPhone home-screen icon, and its own title.
export const metadata: Metadata = {
  title: { default: "StockEx Broker", template: "%s · StockEx Broker" },
  description: "StockEx broker panel.",
  manifest: "/broker.webmanifest",
  icons: { icon: "/broker-icon-192.png", apple: "/broker-apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "StockEx Broker", statusBarStyle: "black-translucent" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#0b0906",
  width: "device-width",
  initialScale: 1,
};

export default function BrokerLayout({ children }: { children: React.ReactNode }) {
  return children;
}
