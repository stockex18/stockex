// Web App Manifest for the STOCKEX BROKER app.
//
// The admin panel ships TWO installable apps from one origin: the admin app
// (app/manifest.webmanifest) and this one. What keeps them apart is `id` —
// browsers identify an installed web app by its manifest id, so two distinct
// ids install as two apps with two icons, side by side on the same phone.
// Share an id and installing the second silently replaces the first.
//
// `scope: "/"` rather than "/broker/": after sign-in the broker works in the
// same /dashboard, /users, ... pages as everyone else, and a narrower scope
// would throw every one of those navigations out of the app into a browser tab.
//
// Linked only from the /broker pages (app/broker/layout.tsx), and protected
// from AdminBrandingChrome's manifest rewrite there.

export const dynamic = "force-static";

const BROKER_MANIFEST = {
  id: "stockex-broker",
  name: "StockEx Broker",
  short_name: "Broker",
  description: "StockEx broker panel — manage your clients, positions and payments.",
  // The app opens on the broker login; that page forwards a signed-in broker
  // straight to the dashboard, so reopening the app never shows the form.
  start_url: "/broker/login?source=app",
  scope: "/",
  display: "standalone",
  display_override: ["standalone", "minimal-ui"],
  orientation: "portrait",
  background_color: "#0b0906",
  theme_color: "#0b0906",
  categories: ["finance", "business"],
  icons: [
    { src: "/broker-icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
    { src: "/broker-icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
    {
      src: "/broker-icon-maskable-512.png",
      sizes: "512x512",
      type: "image/png",
      purpose: "maskable",
    },
  ],
};

export function GET() {
  return new Response(JSON.stringify(BROKER_MANIFEST), {
    headers: {
      "Content-Type": "application/manifest+json; charset=utf-8",
      "Cache-Control": "public, max-age=300",
    },
  });
}
