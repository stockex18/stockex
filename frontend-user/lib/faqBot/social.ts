/**
 * StockEx social handles used by StockEx Buddy (the no-AI help chat).
 *
 * Shown as "Follow StockEx" buttons in the home-page chat panel. Set in
 * .env.local / the server env:
 *
 *   NEXT_PUBLIC_STOCKEX_FACEBOOK_URL=https://www.facebook.com/<page>
 *   NEXT_PUBLIC_STOCKEX_INSTAGRAM_URL=https://www.instagram.com/<handle>
 *
 * A link that is unset is simply not shown. NEXT_PUBLIC_ values are baked in
 * at `next build`, so rebuild after changing them.
 */

export interface SocialLink {
  key: "facebook" | "instagram";
  label: string;
  url: string;
}

const RAW: SocialLink[] = [
  {
    key: "facebook",
    label: "Facebook",
    url: process.env.NEXT_PUBLIC_STOCKEX_FACEBOOK_URL ?? "",
  },
  {
    key: "instagram",
    label: "Instagram",
    url: process.env.NEXT_PUBLIC_STOCKEX_INSTAGRAM_URL ?? "",
  },
];

/** Only links that are configured and look like https URLs. */
export const SOCIAL_LINKS: SocialLink[] = RAW.filter((s) => /^https:\/\/\S+$/.test(s.url.trim()));
