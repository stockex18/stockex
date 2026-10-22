"use client";

// Guided page tours for the broker panel, built on driver.js. Same engine as
// the user app (frontend-user/components/tour/tours.ts); only the steps and
// the auth store differ.
//
// - Shown to BROKER accounts only. Super admins and sub-admins share these
//   pages but never get a tour or the "?" button (see isTourAudience).
// - driver.js is imported lazily inside startTour(), so it never runs on the
//   server (no hydration mismatch) and costs nothing until a tour starts.
// - Elements are found by `data-tour="…"` markers rather than CSS classes.
//   A marker may appear more than once (e.g. a desktop table and a phone card
//   list); the first one that is actually visible is used.
// - Steps whose element isn't visible right now are skipped: desktop and
//   phone layouts show different things, and a broker may not have every
//   permission (Payments tabs are hidden per permission).
// - "Seen" is remembered PER ACCOUNT and PER TOUR (seenKey + ":" + admin id)
//   in this browser's localStorage. Bump a tour's version suffix to show it
//   to everyone again after a redesign.
//
// To add a tour: put data-tour markers on the page and add an entry to
// TOURS. <TourAuto /> in the (admin) layout starts it on the first visit.

import "driver.js/dist/driver.css";
import type { AdminUser } from "@/types";
import { useAdminAuthStore } from "@/stores/authStore";

type TourStep = {
  /** data-tour marker; omit for a centred, element-less step */
  target?: string;
  title: string;
  /** "{links}" is replaced with the target's link labels, as shown (the
   *  phone bottom bar's buttons depend on the broker's permissions). */
  description: string;
  side?: "top" | "bottom" | "left" | "right";
};

type Tour = {
  /** Page the tour belongs to; the header "?" button replays it there. */
  path: string;
  seenKey: string;
  /**
   * Marker(s) of content that loads after the page; the tour waits until
   * any one of them shows up. If none does, the tour doesn't start and
   * isn't marked seen, so it runs once the content exists.
   */
  ready?: string | string[];
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
    seenKey: "stockex.broker.tour.dashboard.v1",
    steps: [
      {
        title: "Welcome to your broker panel",
        description:
          "A quick 1-minute tour of your dashboard. Use Next / Back, or press Esc to skip. You can restart it any time from the ? button at the top.",
      },
      {
        target: "db-stats",
        title: "Your book at a glance",
        description:
          "Live totals for your clients: how many you have, who traded today, their combined wallet balance, margin in use, today's turnover and the brokerage it earned. Pending deposits and withdrawals are waiting for your approval. Refreshes every 10 seconds.",
        side: "bottom",
      },
      {
        target: "db-referral",
        title: "Your referral link",
        description:
          "Share this link with new clients. Anyone who registers through it is added under you automatically. Tap Copy to grab it.",
        side: "bottom",
      },
      {
        target: "db-risk",
        title: "Risk monitor",
        description:
          "Clients whose open losses are using up a large share of their margin. Check it during market hours so you can contact them before they get stopped out.",
        side: "top",
      },
      {
        target: "nav-sidebar",
        title: "Everything else",
        description:
          "Your other pages live here, grouped into sections: My Account, Users, Payments, Money, Risk & Settings, Trading, Reports, Management and System. Each page has its own short tour from the ? button at the top.",
        side: "right",
      },
      {
        // Phones: no sidebar; the bottom bar stands in for it.
        target: "nav",
        title: "Everything else",
        description:
          "Your most-used pages are along the bottom: {links}. Tap More for all the other pages. Each page has its own short tour from the ? button at the top.",
        side: "top",
      },
      REPLAY,
    ],
  },
  users: {
    path: "/users",
    seenKey: "stockex.broker.tour.users.v1",
    steps: [
      {
        title: "Your clients",
        description: "Every client account in your book, with live balances and P&L. Here's a quick look around.",
      },
      {
        target: "us-new",
        title: "Add a client",
        description: "Create a new client account yourself, for someone who hasn't signed up through your referral link.",
        side: "bottom",
      },
      {
        target: "us-mode",
        title: "Live and demo",
        description:
          "Switch between real clients and demo accounts. Demo money is virtual and never touches real P&L or payments.",
        side: "bottom",
      },
      {
        target: "us-filters",
        title: "Find a client",
        description: "Search by client code, email, mobile or name, and filter by status: Active, Pending, Blocked or Closed.",
        side: "bottom",
      },
      {
        target: "us-list",
        title: "Client list",
        description:
          "Balance and open P&L update live. On each client, L opens their ledger (where you can adjust their wallet), S shows live trading stats and P shows their open positions.",
        side: "top",
      },
      REPLAY,
    ],
  },
  payments: {
    path: "/payments",
    seenKey: "stockex.broker.tour.payments.v1",
    steps: [
      {
        title: "Payments",
        description:
          "Where your clients' money requests land: deposits to approve, withdrawals to pay out, settlement requests, and the bank details and rules behind them.",
      },
      {
        target: "pay-tabs",
        title: "Payment queues",
        description: "Each tab is one queue of client money requests. You only see the tabs your account is allowed to use.",
        side: "bottom",
      },
      {
        target: "pay-tab-deposits",
        title: "Deposits",
        description:
          "Clients' deposit requests. Check the payment proof, then approve to credit their wallet or reject with a reason.",
        side: "bottom",
      },
      {
        target: "pay-tab-withdrawals",
        title: "Withdrawals",
        description:
          "Check the client's bank details and pay them, then approve with the UTR number to debit their wallet. Or reject with a reason.",
        side: "bottom",
      },
      {
        target: "pay-tab-settlements",
        title: "Settlement requests",
        description:
          "A client with auto-settlement off whose losses take their wallet below zero lands here, and can't place new trades until you act. Approve sets their balance to 0 and books the shortfall as settlement outstanding, which comes out of their next deposit.",
        side: "bottom",
      },
      {
        target: "pay-tab-history",
        title: "History",
        description:
          "A read-only record of every deposit and withdrawal across your clients. Filter by type, status, client or UTR.",
        side: "bottom",
      },
      {
        target: "pay-tab-rejected",
        title: "Rejected",
        description: "A read-only list of every rejected deposit and withdrawal request, with the reason it was rejected.",
        side: "bottom",
      },
      {
        target: "pay-tab-banks",
        title: "Bank accounts",
        description:
          "The bank accounts, UPI IDs and QR codes your clients see on their deposit screen. Keep these up to date so money lands in the right place.",
        side: "bottom",
      },
      {
        target: "pay-tab-rules",
        title: "Rules",
        description:
          "Minimum and maximum amounts, daily limits, and allowed days and hours for your clients' deposits and withdrawals. Leave a field blank to use the setting from the admin above you.",
        side: "bottom",
      },
      REPLAY,
    ],
  },
  fundRequests: {
    path: "/fund-requests",
    seenKey: "stockex.broker.tour.fund-requests.v1",
    steps: [
      {
        title: "Fund requests",
        description:
          "Requests go up, funds come down. This is where you top up your own balance and handle requests from the people under you.",
      },
      {
        target: "fr-request",
        title: "Ask for funds",
        description:
          "Need more balance to fund your clients? Request it from the admin above you. It shows under My requests until they approve or reject it.",
        side: "bottom",
      },
      {
        target: "fr-send",
        title: "Send to another admin",
        description:
          "Move part of your own balance to another admin or broker by their ID (ADM… or BRK…). It arrives instantly, so double-check the ID first.",
        side: "bottom",
      },
      {
        target: "fr-incoming",
        title: "Incoming requests",
        description: "Fund requests from the people under you. Approve to send them the amount from your balance, or reject.",
        side: "top",
      },
      {
        target: "fr-mine",
        title: "My requests",
        description: "Everything you've asked for, and whether it was approved, rejected or is still pending.",
        side: "top",
      },
      REPLAY,
    ],
  },
  myWallet: {
    path: "/my-wallet",
    seenKey: "stockex.broker.tour.my-wallet.v1",
    steps: [
      {
        title: "My wallet",
        description:
          "Your own coins: the float you fund clients from, what you've earned from their trades, and settlements with your admin.",
      },
      {
        target: "mw-balances",
        title: "Your balances",
        description:
          "Available balance is your float: the coins you hand out to clients. Games earning is commission held from games; use Transfer to main to spend it. Settlement outstanding is money owed that couldn't be recovered, kept for the record.",
        side: "bottom",
      },
      {
        target: "mw-fund",
        title: "Fund your clients",
        description:
          "Add to or deduct from a client's trading balance using your own float. This moves coins only; record real cash that changed hands separately in Ledgers.",
        side: "top",
      },
      {
        target: "mw-earnings",
        title: "Trade earnings",
        description: "What you earned from each trade your clients made.",
        side: "top",
      },
      {
        target: "mw-ledger",
        title: "Recent ledger",
        description: "Funding you received, transfers and releases on your own wallet.",
        side: "top",
      },
      {
        target: "mw-pnl",
        title: "P&L-share settlements",
        description: "Each settlement between you and your admin under your P&L sharing agreement.",
        side: "top",
      },
      REPLAY,
    ],
  },
  positions: {
    path: "/positions",
    seenKey: "stockex.broker.tour.positions.v1",
    steps: [
      {
        title: "Positions",
        description:
          "Every open and closed position across your clients, with live P&L and the risk on each one.",
      },
      {
        target: "pos-summary",
        title: "P&L at a glance",
        description:
          "Open PNL is the live profit or loss on your clients' open positions. The two weekly cards show realised profit or loss after brokerage, for this week (from Sunday) and last week.",
        side: "bottom",
      },
      {
        target: "pos-tabs",
        title: "Open and closed trades",
        description: "Switch between live positions and closed ones.",
        side: "bottom",
      },
      {
        target: "pos-filters",
        title: "Filter and search",
        description:
          "Narrow the list by product (MIS intraday, NRML carry, CNC delivery) or order type, or search by client code, name or symbol.",
        side: "bottom",
      },
      {
        target: "pos-list",
        title: "Positions",
        description:
          "A row turns amber once a position has lost a quarter of its margin, and red at half. Click a row for its full breakdown, or square off a single position at market price.",
        side: "top",
      },
      REPLAY,
    ],
  },
  pnlSharing: {
    path: "/management/pnl-sharing",
    seenKey: "stockex.broker.tour.pnl-sharing.v1",
    // Either the agreement header or the "no agreement" notice: the tour
    // runs as soon as the agreement has finished loading, either way.
    ready: ["ps-header", "ps-empty"],
    steps: [
      {
        title: "P&L sharing",
        description:
          "How your clients' profit, loss and brokerage are split between you and your admin, and every settlement so far.",
      },
      {
        target: "ps-empty",
        title: "No agreement yet",
        description:
          "Your admin hasn't set up a P&L sharing agreement with you. Once they do, your terms, the running split and every settlement show up here.",
        side: "bottom",
      },
      {
        target: "ps-header",
        title: "Your agreement",
        description:
          "Your share percentage, what's shared (P&L and brokerage, or brokerage only), and how and how often it settles. Your admin sets these terms, so this page is read-only.",
        side: "bottom",
      },
      {
        target: "ps-period",
        title: "Pick a period",
        description: "See the running numbers for today, this week or this month.",
        side: "bottom",
      },
      {
        target: "ps-card",
        title: "Current period",
        description: "Your clients' net P&L and brokerage for the period, and how it splits between you and your admin.",
        side: "top",
      },
      {
        target: "ps-history",
        title: "Settlement history",
        description: "Every past settlement under this agreement.",
        side: "top",
      },
      REPLAY,
    ],
  },
  accounts: {
    path: "/accounts-dashboard",
    seenKey: "stockex.broker.tour.accounts.v1",
    steps: [
      {
        title: "Accounts",
        description: "Your book's profit and loss for any week, client by client. Here's how to read it.",
      },
      {
        target: "acc-search",
        title: "Search",
        description: "Find a client by their user ID.",
        side: "bottom",
      },
      {
        target: "acc-tabs",
        title: "Pick a view",
        description:
          "All Users is every client in your book. Sub-Brokers shows one card per sub-broker; open a card for their totals and clients. Account 2 is the fixed brokerage you earn on your sub-brokers' volume.",
        side: "bottom",
      },
      {
        target: "acc-dates",
        title: "Pick a week",
        description:
          "Choose a week from the list, or set your own From and To dates. Every number on the page recalculates for that window. Clear it to see lifetime totals.",
        side: "bottom",
      },
      {
        target: "acc-totals",
        title: "Your totals",
        description:
          "Actual P&L is what your book made: your clients' P&L turned around (their loss is your gain), plus the brokerage they paid, minus settlement. Below it: users, sharing, deposits and withdrawals for the period.",
        side: "top",
      },
      {
        target: "acc-users",
        title: "Client by client",
        description:
          "Each client's P&L, brokerage and settlement for the period. Search for one, or download everything as Excel or PDF.",
        side: "top",
      },
      REPLAY,
    ],
  },
  moneyTransactions: {
    path: "/money-transactions",
    seenKey: "stockex.broker.tour.money-transactions.v1",
    steps: [
      {
        title: "Money transactions",
        description:
          "How much money each client moved in and out over a period, with totals that always add up.",
      },
      {
        target: "money-tabs",
        title: "Money in and out",
        description:
          "By User shows the money each client moved. By Broker rolls deposits up by sub-broker.",
        side: "bottom",
      },
      {
        target: "money-filters",
        title: "Search and period",
        description: "Find a client by name or code, and choose the period: a preset, or your own From and To dates.",
        side: "bottom",
      },
      {
        target: "mt-kpis",
        title: "Totals",
        description:
          "Deposits and added funds coming in, withdrawals and deductions going out, the net, and what was settled. They always add up to the rows below.",
        side: "bottom",
      },
      {
        target: "mt-list",
        title: "Per client",
        description: "One row per client who moved money in the period. Click a row to open their full ledger.",
        side: "top",
      },
      REPLAY,
    ],
  },
  brokerDeposits: {
    path: "/broker-deposits",
    seenKey: "stockex.broker.tour.broker-deposits.v1",
    steps: [
      {
        title: "Broker deposits",
        description:
          "Your clients' deposits rolled up by the sub-broker they sit under, for any period you choose.",
      },
      {
        target: "money-tabs",
        title: "Deposits by sub-broker",
        description: "This view rolls your clients' deposits up by the sub-broker they sit under. By User switches back to one row per client.",
        side: "bottom",
      },
      {
        target: "money-filters",
        title: "Search and period",
        description: "Find a sub-broker by name or code, and choose the period.",
        side: "bottom",
      },
      {
        target: "bd-kpis",
        title: "Totals",
        description: "Total deposits and admin-added funds for the period, and how many sub-brokers and clients they came from.",
        side: "bottom",
      },
      {
        target: "bd-list",
        title: "Sub-broker tree",
        description:
          "Each sub-broker with their clients' deposits. Tap the arrow to open the sub-brokers under them; 'direct' is the part from their own clients.",
        side: "top",
      },
      REPLAY,
    ],
  },
  transactionHistory: {
    path: "/transaction-history",
    seenKey: "stockex.broker.tour.transaction-history.v1",
    steps: [
      {
        title: "Transaction history",
        description: "Every wallet movement for your clients, with the balance after each one.",
      },
      {
        target: "th-filters",
        title: "Trading or games",
        description: "Show everything, trading money only, or one game at a time.",
        side: "bottom",
      },
      {
        target: "th-list",
        title: "Entries",
        description:
          "Green is money in, red is money out. Each entry shows the client, what it was for, and their balance right after.",
        side: "top",
      },
      REPLAY,
    ],
  },
  ledgers: {
    path: "/ledgers",
    seenKey: "stockex.broker.tour.ledgers.v1",
    steps: [
      {
        title: "Ledgers",
        description:
          "Your account books for real money: cash, bank, UPI and anyone you deal with. Coins live on My Wallet; nothing here moves coins.",
      },
      {
        target: "lg-actions",
        title: "Set up your books",
        description:
          "New ledger creates an account. Mark it as a payment mode (Cash, Bank, UPI…) and every movement recorded with that mode posts to it automatically. Firm header is the name printed on your ledger PDFs.",
        side: "bottom",
      },
      {
        target: "lg-tab-accounts",
        title: "Accounts",
        description: "Every ledger you've created, each with its own statement and running balance.",
        side: "bottom",
      },
      {
        target: "lg-tab-entry",
        title: "Admin entry",
        description: "Record real money you received from, or paid to, another admin or broker, and through which ledger.",
        side: "bottom",
      },
      {
        target: "lg-tab-daybook",
        title: "Day Book",
        description: "Every voucher in a period, both sides of each shown together.",
        side: "bottom",
      },
      {
        target: "lg-tab-coins",
        title: "Trial Balance — Coins",
        description: "Coins held across every wallet, with proof that debits equal credits.",
        side: "bottom",
      },
      {
        target: "lg-tab-trial",
        title: "Trial Balance — Cash",
        description: "Every account's closing balance, with proof that debits equal credits.",
        side: "bottom",
      },
      {
        target: "lg-accounts",
        title: "Open an account",
        description:
          "Pick a ledger to see its statement with a running balance, filter by date, add or remove entries, and download it as a PDF.",
        side: "top",
      },
      REPLAY,
    ],
  },
  risk: {
    path: "/risk-management",
    seenKey: "stockex.broker.tour.risk.v1",
    steps: [
      {
        title: "Risk management",
        description:
          "Automatic protection for your clients' wallets. These rules run on their own all day; you set them once.",
      },
      {
        target: "rk-global",
        title: "Your default",
        description:
          "Applies to all your clients. Stop-out warning alerts a client when their loss reaches this % of their balance; Stop-out closes all their positions at this %. Exit-only blocks new trades. Hold timers set how long a trade must stay open before the client can close it.",
        side: "right",
      },
      {
        target: "rk-user",
        title: "One client",
        description:
          "Pick a client to give them different values. Blank fields follow your default. You can also copy another client's settings in one click.",
        side: "left",
      },
      {
        target: "rk-wallet",
        title: "Per wallet",
        description:
          "Different rules for each trading wallet: NSE/BSE, MCX, Crypto and Forex. Blank means the default applies.",
        side: "top",
      },
      REPLAY,
    ],
  },
  segmentSettings: {
    path: "/segment-settings",
    seenKey: "stockex.broker.tour.segment-settings.v1",
    steps: [
      {
        title: "Segment settings",
        description:
          "Trading limits and charges for your clients: lot sizes, margins, brokerage, spreads and more. Settings flow down: segment, then script, then client. The most specific one wins.",
      },
      {
        target: "seg-tab-segments",
        title: "Segments",
        description: "Defaults for each segment, like NSE Futures or MCX Options. They apply to every instrument in it.",
        side: "bottom",
      },
      {
        target: "seg-tab-scripts",
        title: "Scripts",
        description: "Override a single symbol inside a segment. Leave a field empty to use the segment value.",
        side: "bottom",
      },
      {
        target: "seg-tab-users",
        title: "Users",
        description: "Pick one client and give them their own values.",
        side: "bottom",
      },
      {
        target: "seg-categories",
        title: "What to edit",
        description:
          "Switch between groups of settings: lot and quantity limits, value, margin, options, brokerage, limit distance, spread, blocked scripts and expiry-day rules.",
        side: "bottom",
      },
      {
        target: "seg-matrix",
        title: "Edit and save",
        description: "Change the values in the table for each segment, then save.",
        side: "top",
      },
      REPLAY,
    ],
  },
  expiry: {
    path: "/option-chain",
    seenKey: "stockex.broker.tour.expiry.v1",
    steps: [
      {
        title: "Expiry settings",
        description:
          "Choose which underlyings and how many expiries your clients see on their option chain.",
      },
      {
        target: "exp-locked",
        title: "Locked",
        description:
          "The super admin has locked expiry settings for your account. You can see them here, but can't change them until they allow it.",
        side: "bottom",
      },
      {
        target: "exp-status",
        title: "Default or your own",
        description:
          "Your clients use the platform default until you customise it. This line tells you which one they see right now.",
        side: "bottom",
      },
      {
        target: "exp-underlyings",
        title: "Underlyings",
        description:
          "The chips across the top of your clients' option chain, like Nifty or Bank Nifty, and how many expiry months each one shows. Turn on the switch to customise them.",
        side: "bottom",
      },
      {
        target: "exp-window",
        title: "Expiries per exchange",
        description:
          "How many expiries your clients see for each exchange when a script has no setting of its own. 1 = the nearest expiry only.",
        side: "top",
      },
      {
        target: "exp-save",
        title: "Save",
        description: "Save your changes. Reset to default drops your customisation so your clients go back to the platform default.",
        side: "bottom",
      },
      REPLAY,
    ],
  },
  orders: {
    path: "/orders",
    seenKey: "stockex.broker.tour.orders.v1",
    steps: [
      {
        title: "Orders",
        description:
          "Every order your clients place: pending, executed and rejected, refreshed live.",
      },
      {
        target: "ord-today",
        title: "Today so far",
        description: "Trades filled today (buy and sell) and orders still pending. Refreshes every 10 seconds.",
        side: "bottom",
      },
      {
        target: "ord-tabs",
        title: "Order queues",
        description:
          "Pending orders wait for their price. Executed have filled, with the reason (client, stop loss, target, stop-out…). Rejected shows why each was refused. SL / TP lists orders with a stop loss or target.",
        side: "bottom",
      },
      {
        target: "ord-search",
        title: "Search",
        description: "Find orders by client name, client code or symbol. Your search stays as you switch tabs.",
        side: "bottom",
      },
      {
        target: "ord-list",
        title: "Orders",
        description: "Your clients' orders for the chosen tab, with the date and time of each.",
        side: "top",
      },
      REPLAY,
    ],
  },
  deliveryPledge: {
    path: "/delivery-pledge",
    seenKey: "stockex.broker.tour.delivery-pledge.v1",
    steps: [
      {
        title: "Delivery and pledge",
        description:
          "Your clients' equity delivery trades, the shares they've pledged for margin, and how much of each client's pledge limit is in use.",
      },
      {
        target: "dp-tabs",
        title: "Three views",
        description:
          "Delivery Orders are your clients' equity delivery buys and sells. Pledged Holdings are shares pledged for margin. Pledge Summary shows each client's pledge limit, how much is used, and any gap.",
        side: "bottom",
      },
      {
        target: "dp-side",
        title: "Buys or sells",
        description: "On Delivery Orders, show buys and sells together, or only one side.",
        side: "bottom",
      },
      {
        target: "dp-list",
        title: "Details",
        description:
          "On Pledge Summary, watch 'Loss % of cash': amber from 50%, red from 80%. Those clients may need a call.",
        side: "top",
      },
      REPLAY,
    ],
  },
  marketWatch: {
    path: "/marketwatch",
    seenKey: "stockex.broker.tour.marketwatch.v1",
    steps: [
      {
        title: "Market watch",
        description:
          "Live prices for the instruments you follow, segment by segment. Place orders for your clients straight from here.",
      },
      {
        target: "mkt-segments",
        title: "Pick a segment",
        description: "Each segment keeps its own list of instruments.",
        side: "bottom",
      },
      {
        target: "mkt-search",
        title: "Add instruments",
        description: "Type at least 2 letters to search this segment, then tap + to add a symbol to your list.",
        side: "bottom",
      },
      {
        target: "mkt-list",
        title: "Live quotes",
        description:
          "Bid, ask, last price and the day's change, live. Click a row to place an order for one or more of your clients. The bin removes a symbol.",
        side: "top",
      },
      REPLAY,
    ],
  },
  tradebook: {
    path: "/reports/tradebook",
    seenKey: "stockex.broker.tour.tradebook.v1",
    steps: [
      {
        title: "Tradebook PDF",
        description:
          "Build a client's full trading statement as a PDF, for any date range, ready to send.",
      },
      {
        target: "tb-user",
        title: "Pick a client",
        description: "Search by name, code, email or mobile and choose the client.",
        side: "bottom",
      },
      {
        target: "tb-dates",
        title: "Date range",
        description: "Optional. Leave both blank for the client's full history.",
        side: "bottom",
      },
      {
        target: "tb-download",
        title: "Download",
        description: "Builds the tradebook as a PDF you can send to the client.",
        side: "bottom",
      },
      {
        target: "tb-info",
        title: "What's inside",
        description: "Closed trades, money totals, open positions, pending orders and the client's balance and margin.",
        side: "top",
      },
      REPLAY,
    ],
  },
  demo: {
    path: "/demo",
    seenKey: "stockex.broker.tour.demo.v1",
    steps: [
      {
        title: "Demo signups",
        description: "People who signed up for a demo account and chose you as their broker.",
      },
      {
        target: "demo-kind",
        title: "Users or brokers",
        description: "Demo clients, or demo brokers who signed up under you.",
        side: "bottom",
      },
      {
        target: "demo-status",
        title: "Converted or not",
        description:
          "Not converted are still on virtual money: good people to follow up with. Converted have switched to a real account.",
        side: "bottom",
      },
      {
        target: "demo-list",
        title: "Contact details",
        description: "Name, email and mobile for each, with when they signed up or converted.",
        side: "top",
      },
      REPLAY,
    ],
  },
  subBrokers: {
    path: "/management/brokers",
    seenKey: "stockex.broker.tour.sub-brokers.v1",
    steps: [
      {
        title: "Sub-brokers",
        description: "Brokers working under you. Their clients count toward your book.",
      },
      {
        target: "sb-new",
        title: "Add a sub-broker",
        description:
          "Create a sub-broker and choose what they can access and their P&L and brokerage share. You can only give them permissions you have yourself. Male or Female is required: it decides whether clients find them under the Male brokers or Female brokers tab at signup.",
        side: "bottom",
      },
      {
        target: "sb-search",
        title: "Search",
        description: "Find a sub-broker in the list.",
        side: "bottom",
      },
      {
        target: "sb-list",
        title: "Your sub-brokers",
        description:
          "Click a row for their profile. The ⋮ menu lets you log in as them, edit permissions, set their segment settings, block or approve them, reset their password or delete them.",
        side: "top",
      },
      REPLAY,
    ],
  },
  platformSettings: {
    path: "/settings/platform",
    seenKey: "stockex.broker.tour.platform-settings.v1",
    steps: [
      {
        title: "Platform settings",
        description:
          "Your own preferences: how the panel looks, how new clients find you, and the alerts you get.",
      },
      {
        target: "st-theme",
        title: "Theme",
        description: "Light, dark, or follow your device.",
        side: "bottom",
      },
      {
        target: "st-place",
        title: "Get found by new clients",
        description:
          "New clients searching for a broker at signup find you by brand name, city and PIN code, so fill in all three. Clients see your brand, never your own name; with no brand you show as your broker code. Choose Female to be listed under the Female brokers tab; otherwise you're under Male brokers.",
        side: "top",
      },
      {
        target: "st-alerts",
        title: "Live alerts",
        description:
          "A pop-up and a sound when a client sends a deposit or withdrawal request. Use Test to check your browser lets the sound play.",
        side: "bottom",
      },
      REPLAY,
    ],
  },
  support: {
    path: "/support",
    seenKey: "stockex.broker.tour.support.v1",
    steps: [
      {
        title: "Support",
        description:
          "What your clients see when they need help: your WhatsApp number and the terms they accept.",
      },
      {
        target: "sup-whatsapp",
        title: "Your support number",
        description:
          "The WhatsApp number your clients reach from the Contact support and Add funds buttons. Include the country code. Leave it blank to use your admin's number.",
        side: "bottom",
      },
      {
        target: "sup-terms",
        title: "Terms & Conditions",
        description:
          "Optional terms your clients must accept once after signing up. Whenever you change the text, they're asked to accept it again.",
        side: "top",
      },
      REPLAY,
    ],
  },
  audit: {
    path: "/audit",
    seenKey: "stockex.broker.tour.audit.v1",
    steps: [
      {
        title: "Audit logs",
        description: "A record of who did what and when across your book, with IP address and device.",
      },
      {
        target: "au-search",
        title: "One client's activity",
        description: "Search for a client to see everything they did, or that was done to their account.",
        side: "bottom",
      },
      {
        target: "au-presets",
        title: "Quick filters",
        description: "Show one kind of event, such as trade edits, admin closes, reopens, deletes or deposits.",
        side: "bottom",
      },
      {
        target: "au-dates",
        title: "Dates",
        description: "Limit the log to a date range.",
        side: "bottom",
      },
      {
        target: "au-list",
        title: "Events",
        description: "Each event with who did it, to whom, what changed, and when.",
        side: "top",
      },
      REPLAY,
    ],
  },
  adminActions: {
    path: "/admin-actions",
    seenKey: "stockex.broker.tour.admin-actions.v1",
    steps: [
      {
        title: "Admin actions",
        description:
          "A record of sensitive changes on your clients' accounts: who deleted or edited what, and when.",
      },
      {
        target: "aa-tabs",
        title: "Sensitive changes",
        description:
          "Deleted users, deleted positions and edited positions, each with who did it and when (IST).",
        side: "bottom",
      },
      {
        target: "aa-list",
        title: "Before and after",
        description:
          "For edits, each value is shown as before → after; the ones that changed are highlighted. Deleted positions show the P&L that was reversed.",
        side: "top",
      },
      REPLAY,
    ],
  },
} satisfies Record<string, Tour>;

export type TourId = keyof typeof TOURS;

/** Tours are for brokers only; admins share these pages but skip them. */
export function isTourAudience(admin: AdminUser | null | undefined): boolean {
  return admin?.role === "BROKER";
}

/** The tour for a page path, if it has one. */
export function tourForPath(pathname: string | null): TourId | undefined {
  return (Object.keys(TOURS) as TourId[]).find((id) => TOURS[id].path === pathname);
}

function seenKey(id: TourId): string {
  const key = TOURS[id].seenKey;
  const admin = useAdminAuthStore.getState().admin?.id;
  return admin ? `${key}:${admin}` : key;
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
  const ready = [(TOURS[id] as Tour).ready ?? []].flat();
  const isReady = () => !ready.length || ready.some((m) => findTarget(m));
  for (let i = 0; !isReady() && i < 27; i++) {
    await new Promise((r) => setTimeout(r, 300));
  }
  if (!isReady()) return;

  const steps = (TOURS[id].steps as TourStep[]).flatMap((s) => {
    if (!s.target) {
      return [{ popover: { title: s.title, description: s.description } }];
    }
    const el = findTarget(s.target);
    if (!el) return [];
    const labels = Array.from(el.querySelectorAll("a"), (a) => a.textContent?.trim()).filter(Boolean);
    const description = s.description.replace(
      "{links}",
      labels.length > 1 ? `${labels.slice(0, -1).join(", ")} and ${labels.at(-1)}` : labels.join(""),
    );
    return [
      {
        element: el,
        popover: { title: s.title, description, side: s.side, align: "start" as const },
      },
    ];
  });
  // Nothing of this page is on screen (e.g. the broker lacks the permission
  // and sees "no access"): don't run a tour of intro text alone, and don't
  // mark it seen, so it runs once the page is available to them.
  const onPage = (TOURS[id].steps as TourStep[]).some(
    (s) => s.target && s.target !== REPLAY.target && findTarget(s.target),
  );
  if (!onPage) return;

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
    stageRadius: 12,
    smoothScroll: true,
    popoverClass: "stockex-tour",
    // driver.js only scrolls when an element is off-screen, and only to
    // centre it. That leaves two gaps: an element tucked under the sticky
    // top bar counts as "visible", and a centred element may have no room
    // for the popover on its side, so driver.js lays the popover over it.
    // Scroll so the element sits clear of the top bar / phone bottom bar
    // with a popover's worth of room on the side the step asks for.
    onHighlightStarted: (el, step) => {
      const bar = findTarget("topbar");
      if (!(el instanceof HTMLElement) || bar?.contains(el)) return;
      // The sidebar / bottom bar are fixed; scrolling the page can't move them.
      if (el.closest('[data-tour="nav"], [data-tour="nav-sidebar"]')) return;
      // Inside a scrolling box (e.g. a wide table) part of the element can be
      // cut off by the box edge while still "on screen", and the highlight
      // then spans whatever sits below it. Scroll the box first.
      if (clippedByScroller(el)) el.scrollIntoView({ block: "nearest" });
      const side = step.popover?.side;
      const top = bar ? bar.getBoundingClientRect().bottom : 0;
      const nav = document.querySelector<HTMLElement>('nav[data-tour="nav"]');
      const bottom = nav && visible(nav) ? nav.getBoundingClientRect().top : window.innerHeight;
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
