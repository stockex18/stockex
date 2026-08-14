import { redirect } from "next/navigation";

/**
 * `/reports` had a layout (the four-tab bar) but no index page, so the
 * bare URL 404'd — nothing links to it, but trimming the path off
 * /reports/tradebook or opening an old bookmark landed on a not-found.
 * Send it to the first tab, which is what the tab bar highlights anyway.
 */
export default function ReportsIndex() {
  redirect("/reports/pnl");
}
