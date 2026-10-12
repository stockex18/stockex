"use client";

// Guided tour of the user dashboard, built on driver.js.
//
// - driver.js is imported lazily inside startDashboardTour(), so it never
//   runs on the server (no hydration mismatch) and costs nothing until a
//   tour actually starts.
// - Elements are found by `data-tour="…"` markers rather than CSS classes.
// - Steps whose element isn't visible right now are skipped: the desktop
//   layout (sidebar, stat tiles) and the phone layout (bottom bar) show
//   different things, and a step pointing at a hidden element would float
//   in the middle of the screen.
// - "Seen" is remembered PER USER (SEEN_KEY + ":" + user id) in this
//   browser's localStorage, so every new account gets the tour even on a
//   shared browser. Bump the version suffix to show it to everyone again
//   after a redesign.

import "driver.js/dist/driver.css";
import { useAuthStore } from "@/stores/authStore";

export const SEEN_KEY = "stockex.tour.dashboard.v1";

function seenKey(): string {
  const id = useAuthStore.getState().user?.id;
  return id ? `${SEEN_KEY}:${id}` : SEEN_KEY;
}

type TourStep = {
  /** data-tour marker; omit for a centred, element-less step */
  target?: string;
  title: string;
  description: string;
  side?: "top" | "bottom" | "left" | "right";
};

const STEPS: TourStep[] = [
  {
    title: "Welcome to StockEx 👋",
    description:
      "A quick 1-minute tour of your dashboard. Use Next / Back, or press Esc to skip — you can restart it any time from the ? button at the top.",
  },
  {
    target: "portfolio",
    title: "Your portfolio",
    description:
      "Total value across all your wallets and today's profit or loss. Tap the eye icon to hide your balances.",
    side: "bottom",
  },
  {
    target: "wallets",
    title: "Your wallets",
    description:
      "Money is kept in separate wallets per market (Main, Indian, MCX, Crypto…). The star marks your primary trading wallet. Use Manage to move funds between them.",
    side: "top",
  },
  {
    target: "quick-actions",
    title: "Quick actions",
    description:
      "Deposit money, open the option chain, check your open positions, or jump to the market watch to find something to trade.",
    side: "top",
  },
  {
    target: "stats",
    title: "Today at a glance",
    description: "Your open positions, orders waiting to fill, and today's P&L.",
    side: "top",
  },
  {
    target: "games",
    title: "Play & Win",
    description: "Short prediction games on NIFTY and BTC, played from a separate games wallet.",
    side: "bottom",
  },
  {
    target: "nav-sidebar",
    title: "Find your way around",
    description:
      "Everything else lives here: the trading terminal, positions, wallet, reports, referrals and more.",
    side: "right",
  },
  {
    target: "nav-bottom",
    title: "Find your way around",
    description:
      "Home, Market, Games, Positions and your Profile — always one tap away at the bottom of the screen.",
    side: "top",
  },
  {
    target: "notifications",
    title: "Notifications",
    description: "Order fills, deposit approvals and alerts from your broker show up here.",
    side: "bottom",
  },
  {
    target: "tour-button",
    title: "That's it!",
    description: "Tap this ? button whenever you want to see this tour again. Happy trading!",
    side: "bottom",
  },
];

function visible(el: Element | null): el is HTMLElement {
  if (!el || !(el instanceof HTMLElement)) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
}

export function markDashboardTourSeen() {
  try {
    localStorage.setItem(seenKey(), new Date().toISOString());
  } catch {
    /* storage blocked: the tour may show again next visit */
  }
}

export function hasSeenDashboardTour(): boolean {
  try {
    return !!localStorage.getItem(seenKey());
  } catch {
    return true; // can't remember → don't auto-start on every visit
  }
}

export async function startDashboardTour() {
  const { driver } = await import("driver.js");

  const steps = STEPS.flatMap((s) => {
    if (!s.target) {
      return [{ popover: { title: s.title, description: s.description } }];
    }
    const el = document.querySelector(`[data-tour="${s.target}"]`);
    if (!visible(el)) return [];
    return [
      {
        element: el,
        popover: { title: s.title, description: s.description, side: s.side, align: "start" as const },
      },
    ];
  });

  const tour = driver({
    steps,
    showProgress: true,
    progressText: "{{current}} of {{total}}",
    nextBtnText: "Next",
    prevBtnText: "Back",
    doneBtnText: "Done",
    allowClose: true,
    overlayOpacity: 0.65,
    stagePadding: 6,
    stageRadius: 14,
    smoothScroll: true,
    popoverClass: "stockex-tour",
    // Finishing OR skipping both count as "seen".
    onDestroyed: () => markDashboardTourSeen(),
  });
  tour.drive();
}
