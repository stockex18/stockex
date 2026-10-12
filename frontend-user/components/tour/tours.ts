"use client";

// Guided page tours, built on driver.js.
//
// - driver.js is imported lazily inside startTour(), so it never runs on the
//   server (no hydration mismatch) and costs nothing until a tour starts.
// - Elements are found by `data-tour="…"` markers rather than CSS classes.
//   A marker may appear more than once (e.g. a desktop and a phone version
//   of the same buttons); the first one that is actually visible is used.
// - Steps whose element isn't visible right now are skipped: desktop and
//   phone layouts show different things, and a step pointing at a hidden
//   element would float in the middle of the screen.
// - "Seen" is remembered PER USER and PER TOUR (seenKey + ":" + user id) in
//   this browser's localStorage, so every new account gets each tour once
//   even on a shared browser. Bump a tour's version suffix to show it to
//   everyone again after a redesign.
//
// To add a tour: put data-tour markers on the page, add an entry to TOURS,
// and render <PageTourAuto id="…" /> on the page (inside <Suspense>).

import "driver.js/dist/driver.css";
import { useAuthStore } from "@/stores/authStore";

type TourStep = {
  /** data-tour marker; omit for a centred, element-less step */
  target?: string;
  title: string;
  description: string;
  side?: "top" | "bottom" | "left" | "right";
};

type Tour = {
  /** Page the tour belongs to; the header "?" button replays it there. */
  path: string;
  seenKey: string;
  /** Marker of content that loads after the page; the tour waits for it. */
  ready?: string;
  steps: TourStep[];
};

const REPLAY: TourStep = {
  target: "tour-button",
  title: "That's it!",
  description: "Tap this ? button on this page whenever you want to see this tour again.",
  side: "bottom",
};

export const TOURS = {
  dashboard: {
    path: "/dashboard",
    seenKey: "stockex.tour.dashboard.v1",
    steps: [
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
        ...REPLAY,
        description: "Tap this ? button whenever you want to see a tour again. Happy trading!",
      },
    ],
  },

  accounts: {
    path: "/accounts",
    seenKey: "stockex.tour.accounts.v1",
    steps: [
      {
        title: "My Accounts 💼",
        description:
          "This is where your money lives. A quick tour of your wallets and how money moves between them.",
      },
      {
        target: "acc-main",
        title: "Main Wallet (Cash)",
        description:
          "Money you deposit lands here first. From here you can withdraw it to your bank or move it into a trading wallet. Tap the eye icon to hide balances.",
        side: "bottom",
      },
      {
        target: "acc-main-actions",
        title: "Add funds & withdraw",
        description:
          "Add Funds walks you through paying by UPI and uploading the payment screenshot. Withdraw sends money to your bank. Your broker approves both.",
        side: "top",
      },
      {
        target: "acc-trading",
        title: "Trading wallets",
        description:
          "One wallet per market: NSE / BSE, MCX, Crypto and Forex. Each has its own balance and used margin.",
        side: "top",
      },
      {
        target: "acc-trading-actions",
        title: "Trade, set primary, move",
        description:
          "Trade Now opens the market for this wallet. Set Primary makes it your default. Move transfers money in from your Main wallet.",
        side: "top",
      },
      {
        target: "acc-primary",
        title: "Your primary wallet ⭐",
        description:
          "The star marks your primary wallet — it decides which market and instruments you see when you trade. The default is NSE / BSE.",
        side: "top",
      },
      {
        target: "acc-games",
        title: "Games wallet",
        description:
          "Coins for the prediction games, kept apart from your trading money. Add Coins moves money in from Main; To Main moves your winnings back.",
        side: "top",
      },
      REPLAY,
    ],
  },

  wallet: {
    path: "/wallet",
    seenKey: "stockex.tour.wallet.v1",
    steps: [
      {
        title: "Your Wallet 💳",
        description: "Deposits, withdrawals and every cash movement on your account, in one place.",
      },
      {
        target: "wal-balance",
        title: "Available balance",
        description:
          "What you can use right now. Below it: margin blocked by open trades, your credit limit, and your realised profit or loss.",
        side: "bottom",
      },
      {
        target: "wal-actions",
        title: "Add funds & withdraw",
        description:
          "Add Funds: enter an amount, pay by UPI, then upload the payment screenshot. Withdraw: request a payout to your bank. Your broker approves both.",
        side: "bottom",
      },
      {
        target: "wal-stats",
        title: "Totals & pending requests",
        description:
          "How much you've deposited and withdrawn in total, and how many requests are still waiting for approval.",
        side: "top",
      },
      {
        target: "wal-games",
        title: "Games & referral earnings",
        description:
          "Game winnings and referral rewards collect in your games wallet. Move them to your main wallet here to withdraw them.",
        side: "top",
      },
      {
        target: "wal-transactions",
        title: "Transactions",
        description:
          "Every deposit, withdrawal and adjustment with its status (Pending, Approved, Rejected). Use All, Money in or Money out to filter.",
        side: "top",
      },
      REPLAY,
    ],
  },

  games: {
    path: "/games",
    seenKey: "stockex.tour.games.v1",
    // The game cards arrive with the games settings, a moment after the page.
    ready: "gm-card",
    steps: [
      {
        title: "Games 🎮",
        description:
          "Short prediction games on NIFTY and Bitcoin, played with coins from a separate games wallet. Here's how it works.",
      },
      {
        target: "gm-coins",
        title: "Your games coins",
        description:
          "Every game is paid from this balance and winnings land here. It's kept apart from your trading money.",
        side: "bottom",
      },
      {
        target: "gm-add",
        title: "Add coins",
        description: "Move money in from your Main wallet to play.",
        side: "bottom",
      },
      {
        target: "gm-out",
        title: "Move to Main",
        description: "Send your coins and winnings back to your Main wallet, to trade with or withdraw.",
        side: "bottom",
      },
      {
        target: "gm-prices",
        title: "Live prices",
        description:
          "The live NIFTY and BTC prices the games use. The dot on the right shows whether the market feed is live.",
        side: "bottom",
      },
      {
        target: "gm-updown",
        title: "Up / Down",
        description:
          "Predict whether the price will be higher or lower at the end of the next 15 minutes. The BTC game runs 24×7.",
        side: "top",
      },
      {
        target: "gm-number",
        title: "Number",
        description: "Guess the closing decimals of NIFTY, or the last two digits of the BTC price.",
        side: "top",
      },
      {
        target: "gm-bracket",
        title: "Bracket",
        description:
          "Pick Up or Down. You win if the price moves past a set distance above (Up) or below (Down) the current price.",
        side: "top",
      },
      {
        target: "gm-jackpot",
        title: "Jackpot",
        description: "Predict the price. The closest predictions share the prize pool.",
        side: "top",
      },
      {
        target: "gm-card",
        title: "Pick a game",
        description:
          "Each card shows the market (NIFTY or BTC) and how many tickets are in play right now. Tap Play Now to open the game and its rules.",
        side: "bottom",
      },
      REPLAY,
    ],
  },

  profile: {
    path: "/profile",
    seenKey: "stockex.tour.profile.v1",
    steps: [
      {
        title: "Your Profile 👤",
        description: "Your account details, security and settings, all in one place. Here's a quick look around.",
      },
      {
        target: "pf-header",
        title: "Your account",
        description:
          "Your name, user code and email, with your account status. Keep your user code handy when you contact support.",
        side: "bottom",
      },
      {
        target: "pf-earn",
        title: "Refer & Earn",
        description: "Share your referral code with friends and earn rewards when they join.",
        side: "bottom",
      },
      {
        target: "pf-account",
        title: "Account",
        description:
          "Check your personal details, see or switch your broker, and jump to your wallet to deposit or withdraw.",
        side: "top",
      },
      {
        target: "pf-reports",
        title: "Trading & reports",
        description:
          "Your P&L, tradebook, margin and brokerage reports, your notifications, and the ledger of every cash entry and charge.",
        side: "top",
      },
      {
        target: "pf-security",
        title: "Keep your account safe 🔒",
        description:
          "Change your password here. We recommend turning on two-factor authentication for an extra login step.",
        side: "top",
      },
      {
        target: "pf-prefs",
        title: "Appearance",
        description: "Switch between the light and dark theme.",
        side: "top",
      },
      {
        target: "pf-support",
        title: "Need help?",
        description: "Reach support on WhatsApp or by email.",
        side: "top",
      },
      {
        target: "pf-signout",
        title: "Logout",
        description: "Sign out of StockEx on this device.",
        side: "top",
      },
      REPLAY,
    ],
  },

  referral: {
    path: "/referral",
    seenKey: "stockex.tour.referral.v1",
    steps: [
      {
        title: "Refer & Earn 🎁",
        description: "Invite friends to StockEx and earn rewards when they sign up and start trading or playing.",
      },
      {
        target: "rf-code",
        title: "Your referral code",
        description: "Your personal code. Friends enter it when they sign up so you get the credit.",
        side: "bottom",
      },
      {
        target: "rf-actions",
        title: "Share it",
        description:
          "Copy your code, copy your invite link, or tap Share to send it on WhatsApp or any app. The link opens sign-up with your code already filled in.",
        side: "bottom",
      },
      {
        target: "rf-stats",
        title: "Your progress",
        description:
          "How many friends signed up with your code, how many are active, and how much you've earned so far.",
        side: "top",
      },
      {
        target: "rf-list",
        title: "Your referrals",
        description:
          "Everyone who joined with your code, their status, and how close each one is to unlocking your reward.",
        side: "top",
      },
      {
        target: "rf-earnings",
        title: "Recent earnings",
        description: "Every reward you've received. Rewards are credited automatically.",
        side: "top",
      },
      REPLAY,
    ],
  },

  ledger: {
    path: "/ledger",
    seenKey: "stockex.tour.ledger.v1",
    // Entries load after the page; the "Loading…" box isn't the list.
    ready: "lg-list",
    steps: [
      {
        title: "Ledger 📒",
        description: "Every rupee in and out of your account, line by line, with a running balance.",
      },
      {
        target: "lg-sources",
        title: "Choose what to see",
        description:
          "All, just your Trading account, or just your Games wallet. Trading adds opening and closing balance; Games adds tickets bought and winnings.",
        side: "bottom",
      },
      {
        target: "lg-list",
        title: "Your entries",
        description:
          "Newest first: the date, category, details, debit (money out), credit (money in) and the balance after each entry. Trading entries cover the last month; older ones are in Reports.",
        side: "top",
      },
      {
        target: "lg-pages",
        title: "More entries",
        description: "Move between pages and choose how many entries to show per page.",
        side: "top",
      },
      REPLAY,
    ],
  },

  positions: {
    path: "/positions",
    seenKey: "stockex.tour.positions.v1",
    steps: [
      {
        title: "Positions 📈",
        description: "Track your open trades and their live profit or loss, and close them when you're ready.",
      },
      {
        target: "ps-summary",
        title: "At a glance",
        description:
          "How many positions you have open, and your M2M: the live, not-yet-booked profit or loss on all of them together.",
        side: "bottom",
      },
      {
        target: "ps-squareoff",
        title: "Square off all",
        description: "Closes every open position at once. You'll be asked to confirm first.",
        side: "bottom",
      },
      {
        target: "ps-accounts",
        title: "Pick a wallet",
        description:
          "All shows trades from every wallet. Pick NSE / BSE, MCX, Crypto or Forex to see only that wallet's trades, with its balance, available funds and used margin.",
        side: "bottom",
      },
      {
        target: "ps-tabs",
        title: "Four views",
        description:
          "Position: your net holding per instrument. Active: each open trade that makes up those positions. Pending: limit and stop orders waiting to fill. Closed: finished trades with their booked P&L.",
        side: "bottom",
      },
      {
        target: "ps-list",
        title: "Manage a trade",
        description:
          "Each row shows the live price, M2M and margin. Use the pencil to set a stop loss (SL) or target (TP), or exit to close all or part of a position.",
        side: "top",
      },
      REPLAY,
    ],
  },

  terminal: {
    path: "/terminal",
    seenKey: "stockex.tour.terminal.v1",
    steps: [
      {
        title: "Trading Terminal 💹",
        description:
          "Your trading chart, order ticket and positions on one screen. Here's how to find an instrument and place a trade.",
      },
      {
        target: "tm-market",
        title: "Market list",
        description: "Opens or closes the list of instruments on the left.",
        side: "bottom",
      },
      {
        target: "tm-instruments",
        title: "Find an instrument",
        description: "Search for a stock, index, commodity, crypto or forex pair, then tap it to open its chart.",
        side: "right",
      },
      {
        target: "tm-account",
        title: "Trading wallet",
        description:
          "The wallet this order is paid from. Tap to switch between NSE / BSE, MCX, Crypto and Forex. With NSE / BSE you also get the option chain here.",
        side: "bottom",
      },
      {
        target: "tm-tabs",
        title: "Chart tabs",
        description: "Each instrument you open gets its own tab. Use + to add one and × to close it.",
        side: "bottom",
      },
      {
        target: "tm-chart",
        title: "Live chart",
        description:
          "The live chart for the selected instrument. Use the chart's own toolbar to change the timeframe, add indicators or draw.",
        side: "left",
      },
      {
        target: "tm-ordertype",
        title: "Market or Limit",
        description:
          "Market buys or sells straight away at the current price. Limit waits until the price reaches the level you set.",
        side: "left",
      },
      {
        target: "tm-side",
        title: "Sell or Buy",
        description: "Pick a side. Each card shows the price you'd trade at right now.",
        side: "left",
      },
      {
        target: "tm-size",
        title: "How much",
        description: "Set the size in lots (or quantity). Use − and + to adjust.",
        side: "left",
      },
      {
        target: "tm-sltp",
        title: "Take Profit & Stop Loss",
        description:
          "Optional. Take Profit closes the trade at your target price; Stop Loss closes it to limit a loss. Leave them empty to skip.",
        side: "left",
      },
      {
        target: "tm-margin",
        title: "Margin",
        description: "The margin this order needs, what's already in use, and what you have available in this wallet.",
        side: "left",
      },
      {
        target: "tm-submit",
        title: "Place the order",
        description: "The button shows the side and size, so you can check it before you tap.",
        side: "left",
      },
      {
        target: "tm-bottom",
        title: "Positions & wallet",
        description:
          "Your positions, active trades, pending orders and history for this wallet, with your balance, margin and open P&L along the bottom.",
        side: "top",
      },
      {
        target: "tm-views",
        title: "Chart, options, news",
        description: "Switch between the chart, the option chain (for F&O instruments) and the latest news.",
        side: "bottom",
      },
      {
        target: "tm-quick",
        title: "Sell or Buy",
        description: "Trade at the current price, or tap the briefcase to see your positions.",
        side: "top",
      },
      REPLAY,
    ],
  },
} satisfies Record<string, Tour>;

export type TourId = keyof typeof TOURS;

/** The tour for a page path, if it has one. */
export function tourForPath(pathname: string): TourId | undefined {
  return (Object.keys(TOURS) as TourId[]).find((id) => TOURS[id].path === pathname);
}

function seenKey(id: TourId): string {
  const key = TOURS[id].seenKey;
  const user = useAuthStore.getState().user?.id;
  return user ? `${key}:${user}` : key;
}

function visible(el: Element | null): el is HTMLElement {
  if (!el || !(el instanceof HTMLElement)) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
}

/** Height a popover needs beside its element (tallest popover + arrow + gap). */
const POPOVER_ROOM = 200;

/** Whether a scrolling ancestor (not the page itself) cuts part of `el` off. */
function clippedByScroller(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    if (p.scrollHeight <= p.clientHeight) continue;
    // "hidden" too: driver.js sets overflow:hidden on the box while highlighting.
    if (!/auto|scroll|hidden/.test(getComputedStyle(p).overflowY)) continue;
    const pr = p.getBoundingClientRect();
    if (r.top < pr.top - 1 || r.bottom > pr.bottom + 1) return true;
  }
  return false;
}

function findTarget(marker: string): HTMLElement | undefined {
  return Array.from(document.querySelectorAll(`[data-tour="${marker}"]`)).find(visible) as
    | HTMLElement
    | undefined;
}

export function markTourSeen(id: TourId) {
  try {
    localStorage.setItem(seenKey(id), new Date().toISOString());
  } catch {
    /* storage blocked: the tour may show again next visit */
  }
}

export function hasSeenTour(id: TourId): boolean {
  try {
    return !!localStorage.getItem(seenKey(id));
  } catch {
    return true; // can't remember → don't auto-start on every visit
  }
}

export async function startTour(id: TourId) {
  const { driver } = await import("driver.js");

  // Wait (up to ~8s) for late-loading content, so its steps aren't skipped.
  const ready = (TOURS[id] as Tour).ready;
  for (let i = 0; ready && !findTarget(ready) && i < 27; i++) {
    await new Promise((r) => setTimeout(r, 300));
  }

  const steps = (TOURS[id].steps as TourStep[]).flatMap((s) => {
    if (!s.target) {
      return [{ popover: { title: s.title, description: s.description } }];
    }
    const el = findTarget(s.target);
    if (!el) return [];
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
    // driver.js only scrolls when an element is off-screen, and only to
    // centre it. That leaves two gaps: an element tucked under the sticky
    // top bar counts as "visible", and a centred element may have no room
    // for the popover on its side, so driver.js lays the popover over it.
    // Scroll so the element sits clear of the top bar / phone bottom bar
    // with a popover's worth of room on the side the step asks for.
    onHighlightStarted: (el, step) => {
      const bar = document.querySelector("header");
      if (!(el instanceof HTMLElement) || bar?.contains(el)) return;
      // Inside a scrolling box (e.g. the terminal order panel) part of the
      // element can be cut off by the box edge while still "on screen", and
      // the highlight then spans whatever sits below it. Scroll the box first.
      if (clippedByScroller(el)) el.scrollIntoView({ block: "nearest" });
      const side = step.popover?.side;
      const top = bar ? bar.getBoundingClientRect().bottom : 0;
      const nav = findTarget("nav-bottom");
      const bottom = nav ? nav.getBoundingClientRect().top : window.innerHeight;
      const minTop = top + 8 + (side === "top" ? POPOVER_ROOM : 0);
      const maxBottom = bottom - 8 - (side === "bottom" ? POPOVER_ROOM : 0);
      const r = el.getBoundingClientRect();
      if (r.top >= minTop && r.bottom <= maxBottom) return;
      el.style.scrollMarginTop = `${minTop}px`;
      el.scrollIntoView({ block: "start" });
    },
    // Finishing OR skipping both count as "seen".
    onDestroyed: () => markTourSeen(id),
  });
  tour.drive();
}
