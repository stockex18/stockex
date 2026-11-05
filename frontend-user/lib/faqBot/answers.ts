/**
 * StockEx Buddy (no-AI) — the stored questions and answers.
 *
 * Every reply the bot gives comes from this file: there is no AI and no
 * outside API. Clicking a question shows its answer; a typed question is
 * matched against each entry's `keywords` (lib/faqBot/match.ts). To change
 * what the bot says, edit the answers here — keep them short, factual and in
 * line with the site's own pages. Page paths (/demo, /faq …) listed in
 * BOT_PAGES become links in the panel; **bold** shows as bold.
 *
 * Safe to import from the browser — no secrets here.
 */

export type TopicKey = "help-center" | "faqs" | "trading-guides" | "support";

export interface QA {
  id: string;
  q: string;
  a: string;
  /**
   * Words / phrases that point to this answer when typed (lowercase).
   * Single words match whole words only; phrases match anywhere. Hinglish
   * spellings are welcome — visitors type them.
   */
  keywords: string[];
}

export const QAS: QA[] = [
  // ── About StockEx ──────────────────────────────────────────────────
  {
    id: "what-is",
    q: "What is StockEx?",
    a: "StockEx is an online trading app for Indian markets — equity, Futures & Options, commodities (MCX) and indices — plus global markets like forex, crypto and metals, all from one terminal. It works in your browser and as an installable app. See what you can trade: /trading",
    keywords: ["stockex", "about", "stockex kya", "who are you", "company", "platform"],
  },
  {
    id: "what-trade",
    q: "What can I trade on StockEx?",
    a: "Indian equity (delivery and intraday), Futures & Options, commodities on MCX and indices, plus global markets like forex, crypto and metals — all from a single account. More here: /trading",
    keywords: ["trade", "segment", "segments", "crypto", "forex", "gold", "silver", "commodity", "commodities", "mcx", "equity", "stocks", "shares", "nse", "bse", "markets"],
  },
  {
    id: "account-types",
    q: "Which accounts do you offer?",
    a: "Two: a **Real Account** to trade every market with your own funds, and a **Demo Account** to practise on the same live prices with virtual funds — no KYC and no deposit needed. Compare them: /account-types",
    keywords: ["account type", "account types", "types of account", "real account", "which account"],
  },
  {
    id: "safe",
    q: "Is StockEx safe to use?",
    a: "Your account is protected by your password and mobile verification, and money moves only through the bank / UPI details shown in your Wallet. Never share your password or OTP with anyone — the StockEx team will never ask for them. For anything about your own account, contact: /contact",
    keywords: ["safe", "safety", "secure", "security", "trust", "genuine", "fraud", "scam", "legit"],
  },

  // ── Getting started ────────────────────────────────────────────────
  {
    id: "open-account",
    q: "How do I open an account?",
    a: "Tap **Open Account** at the top of the page (or go to /register), enter your name, mobile and email, and pick the broker you want to join under. Your account starts as a **demo** so you can look around; switch to a real account from inside the app when you're ready.",
    keywords: ["open account", "new account", "sign up", "signup", "register", "registration", "join", "account kholna", "account khol", "create account"],
  },
  {
    id: "switch-real",
    q: "How do I switch from demo to a real account?",
    a: "Log in, then tap **Switch to Real Account** in the app. Your login and broker stay the same; the demo trades are cleared and your real account starts at ₹0 — add funds from the Wallet to begin trading.",
    keywords: ["switch", "convert", "real account", "live account", "demo to real", "real me"],
  },
  {
    id: "demo",
    q: "Is there a demo account?",
    a: "Yes! The **Demo Account** lets you practise on live NSE, BSE and MCX prices with virtual money — no KYC, no deposit and no risk. Start here: /demo",
    keywords: ["demo", "practice", "practise", "virtual", "paper trading", "paper trade", "free trial", "trial", "test"],
  },
  {
    id: "kyc",
    q: "Do I need KYC?",
    a: "Not for the **Demo Account**. For a **Real Account**, KYC is required — you complete it online from inside the app. Questions about your KYC status? Contact: /contact",
    keywords: ["kyc", "pan", "aadhaar", "aadhar", "documents", "document", "verification", "verify"],
  },
  {
    id: "install",
    q: "How do I install the app?",
    a: "Open stockex.in in your phone's browser and tap **Install app** at the top of the page, then follow the prompt to add StockEx to your home screen. It opens like a normal app after that. Only install StockEx from stockex.in — never from a file or link someone sends you.",
    keywords: ["install", "download", "app", "apk", "play store", "playstore", "mobile app", "android", "iphone", "ios"],
  },
  {
    id: "login-help",
    q: "I can't log in — what should I do?",
    a: "Check your mobile number / email and password first. If you've forgotten the password, reset it here: /forgot-password. Still stuck? Contact our team: /contact",
    keywords: ["login", "log in", "signin", "sign in", "cant login", "can't login", "unable to login", "locked", "blocked", "login nahi"],
  },
  {
    id: "forgot-password",
    q: "I forgot my password",
    a: "No problem — reset it here: /forgot-password. If that doesn't work, contact our team: /contact",
    keywords: ["forgot", "forget", "password", "reset password", "change password", "bhool"],
  },

  // ── Money ──────────────────────────────────────────────────────────
  {
    id: "deposit",
    q: "How do I add money (deposit)?",
    a: "Log in and go to **Wallet → Deposit**. Pay to the bank / UPI details shown there, then enter the **UTR / reference number** of your payment. Our team verifies it and credits your wallet.",
    keywords: ["deposit", "add money", "add fund", "add funds", "fund", "funds", "top up", "topup", "upi", "utr", "paise dal", "paisa dal", "paise kaise dale", "dalna", "daalna", "jama", "recharge"],
  },
  {
    id: "deposit-pending",
    q: "My deposit isn't showing yet",
    a: "Deposits are credited after our team verifies the payment. Please check that you entered the correct **UTR / reference number** in the Wallet. If it's still not showing, use the **Support / WhatsApp** option inside the app (or /contact if you can't log in) — they can check your payment.",
    keywords: ["not credited", "not showing", "pending deposit", "deposit pending", "deposit not", "money not received", "nahi aaya", "credit nahi"],
  },
  {
    id: "withdraw",
    q: "How do I withdraw money?",
    a: "Log in, go to **Wallet → Withdraw** and request a withdrawal to your saved bank / UPI. Our team reviews it; if a request is ever rejected, the reason is shown on it. For a specific withdrawal, use the **Support / WhatsApp** option in the app.",
    keywords: ["withdraw", "withdrawal", "payout", "nikal", "nikalna", "cash out", "take out", "transfer to bank"],
  },
  {
    id: "charges",
    q: "What are the charges and brokerage?",
    a: "Charges depend on your account and broker, and any charges are shown before you place an order. For the latest brokerage, margins and offers, please ask our team: /contact",
    keywords: ["charges", "charge", "brokerage", "fees", "fee", "cost", "price", "pricing", "commission", "hidden"],
  },
  {
    id: "margin",
    q: "Do you give margin / leverage?",
    a: "Yes, margin is available on many segments. It lets you take a bigger position with less money — but it magnifies losses as much as gains. Margin levels depend on the segment and your account; ask our team for details: /contact",
    keywords: ["margin", "leverage", "exposure"],
  },

  // ── Markets & trading basics ───────────────────────────────────────
  {
    id: "market-hours",
    q: "What are the market hours?",
    a: "Indian equity and F&O trade **9:15 AM – 3:30 PM IST**, Monday to Friday. MCX commodities trade from 9:00 AM until late night. Markets are closed on weekends and exchange holidays.",
    keywords: ["market hours", "timing", "timings", "open time", "close time", "holiday", "holidays", "kab khul", "kab band", "market open", "market close"],
  },
  {
    id: "market-limit",
    q: "Market vs Limit orders — what's the difference?",
    a: "A **Market** order buys or sells straight away at the best available price — fast, but the exact price isn't guaranteed. A **Limit** order only fills at your price or better — you control the price, but it may not fill at all.\nExample: a stock is at ₹100. A market buy fills around ₹100 now; a limit buy at ₹95 waits until the price drops to ₹95. Practise both on /demo",
    keywords: ["market order", "limit order", "order type", "order types", "sl-m", "slm"],
  },
  {
    id: "stop-loss",
    q: "What is a stop-loss?",
    a: "A **stop-loss** closes your trade automatically if the price moves against you to a level you choose — it caps your loss.\nExample: you buy at ₹100 and set a stop-loss at ₹95; if the price falls to ₹95, the position is closed, limiting the loss to about ₹5 per share. Learn more: /education",
    keywords: ["stop loss", "stoploss", "stop-loss", "sl"],
  },
  {
    id: "intraday-delivery",
    q: "Delivery vs intraday trading",
    a: "**Delivery**: you pay the full amount and keep the shares as long as you like.\n**Intraday**: you open and close the trade the same day, usually with margin — which magnifies gains *and* losses — and open positions are squared off before the market closes. Try both risk-free on /demo",
    keywords: ["intraday", "delivery", "mis", "cnc", "square off", "squareoff", "same day"],
  },
  {
    id: "options",
    q: "How do options work, simply?",
    a: "An option gives the buyer the **right, not the obligation**, to buy (a **call**) or sell (a **put**) at a fixed price before expiry. The buyer pays a **premium** — that's the most a buyer can lose. Sellers collect the premium but take on bigger risk. Our free courses explain it step by step: /education",
    keywords: ["option", "options", "call", "put", "premium", "strike", "f&o", "fno", "expiry", "ce", "pe"],
  },
  {
    id: "futures",
    q: "What are futures?",
    a: "A **future** is an agreement to buy or sell at a fixed price on a future date. You trade it with margin, so small price moves make big profits *or* losses, and positions are marked to market every day. Learn the basics: /education",
    keywords: ["future", "futures", "derivative", "derivatives", "lot", "lot size"],
  },
  {
    id: "learn",
    q: "Where can I learn trading?",
    a: "Start with our free lessons and videos at /education, then practise what you learn with virtual money on /demo. We explain how trading works — we don't give tips or buy/sell calls.",
    keywords: ["learn", "learning", "course", "courses", "education", "tutorial", "video", "beginner", "sikhna", "seekhna", "guide"],
  },
  {
    id: "tips",
    q: "Do you give trading tips or calls?",
    a: "No. StockEx doesn't give tips, targets or buy/sell calls, and nothing here is investment advice. Trading involves risk — please decide carefully. To learn how trading works, see /education.",
    keywords: ["tip", "tips", "calls", "recommend", "recommendation", "which stock", "kaunsa share", "target", "advice", "suggest"],
  },

  // ── Extras ─────────────────────────────────────────────────────────
  {
    id: "nifty-games",
    q: "What are Nifty Games?",
    a: "**Nifty Games** are fun prediction games built around the live Nifty index — for example, calling whether it goes up or down in a short window. See all the games here: /nifty-games",
    keywords: ["game", "games", "nifty game", "nifty games", "up down", "updown", "jackpot", "predict", "prediction", "bracket", "number game"],
  },
  {
    id: "referral",
    q: "How does Refer & Earn work?",
    a: "With **Refer & Earn**, you invite friends to StockEx with your referral link and earn rewards when they join and trade. You'll find your link after you log in. New here? Open an account: /register",
    keywords: ["refer", "referral", "referrals", "invite", "earn", "friend", "friends", "reward", "rewards", "bonus"],
  },
  {
    id: "broker-partner",
    q: "How can I become a broker or partner?",
    a: "Brokers and partners can join through the StockEx **Broker programme**. To talk to the team about it, reach out here: /contact (or email partners@stockex.com).",
    keywords: ["broker", "partner", "partnership", "franchise", "sub broker", "subbroker", "ib", "business"],
  },
  {
    id: "support",
    q: "How do I reach the support team?",
    a: "If you have an account, log in and use the **Support / WhatsApp** option inside the app. Otherwise, reach the team here: /contact or email support@stockex.com. We answer Monday to Saturday, in English and Hindi.",
    keywords: ["support", "contact", "help", "helpline", "whatsapp", "phone", "number", "email", "human", "agent", "team", "complaint", "complain", "customer care", "baat"],
  },
];

const BY_ID = new Map(QAS.map((x) => [x.id, x]));

/** The entry with this id (throws on a typo, so a bad id fails loudly in dev). */
export function qa(id: string): QA {
  const hit = BY_ID.get(id);
  if (!hit) throw new Error(`faqBot: unknown question id "${id}"`);
  return hit;
}

export interface Topic {
  /** Shown in the panel header, e.g. "StockEx Buddy · FAQs". */
  title: string;
  greeting: string;
  /** Question ids offered as buttons when the chat opens. */
  starters: string[];
}

/** The hero "Chat with us" pill — no topic. */
export const GENERAL_TOPIC: Omit<Topic, "title"> = {
  greeting:
    "Hi! 👋 I'm StockEx Buddy. Pick a question below or type your own — I'll find the answer.",
  starters: ["what-is", "open-account", "demo", "nifty-games", "deposit", "support"],
};

/** The four cards in the home page's "24/7 Customer Support" section. */
export const TOPICS: Record<TopicKey, Topic> = {
  "help-center": {
    title: "Help Center",
    greeting:
      "Hi! 👋 Welcome to the StockEx Help Center. Pick a topic below or type your question.",
    starters: ["open-account", "install", "deposit", "withdraw", "login-help", "switch-real"],
  },
  faqs: {
    title: "FAQs",
    greeting: "Hi! 👋 Here are the questions people ask most — tap one, or type your own.",
    starters: ["demo", "what-trade", "market-hours", "kyc", "charges", "nifty-games"],
  },
  "trading-guides": {
    title: "Trading Guides",
    greeting:
      "Hi! 👋 I can explain trading basics in plain language. I explain how things work — I don't give tips or calls.",
    starters: ["market-limit", "stop-loss", "intraday-delivery", "options", "futures", "learn"],
  },
  support: {
    title: "24/7 Support",
    greeting:
      "Hi! 👋 Tell me what you need help with. For anything about your own account, I'll point you to the right team.",
    starters: ["deposit-pending", "withdraw", "forgot-password", "support", "safe"],
  },
};

export const TOPIC_KEYS = Object.keys(TOPICS) as TopicKey[];

export function isTopicKey(v: unknown): v is TopicKey {
  return typeof v === "string" && (TOPIC_KEYS as string[]).includes(v);
}

/**
 * Site pages answers may mention. Answers are plain text, so the panel turns
 * exactly these paths (and https URLs) into links — nothing else.
 */
export const BOT_PAGES: Record<string, string> = {
  "/register": "Open a new account",
  "/login": "Log in",
  "/forgot-password": "Reset a forgotten password",
  "/demo": "Demo account (practise with virtual money)",
  "/education": "Free trading courses and lessons",
  "/faq": "Frequently asked questions",
  "/contact": "Contact the StockEx team",
  "/nifty-games": "Nifty Games",
  "/account-types": "Account types",
  "/trading": "What you can trade",
};

/** Event the support cards fire to open the bot on a topic. */
export const OPEN_EVENT = "stockex-buddy:open";

/**
 * Element the chat panel can sit inside instead of floating — the support
 * section puts one under its cards, so the panel never covers them.
 */
export const DOCK_ID = "stockex-buddy-dock";

/**
 * Open StockEx Buddy (if it is on the page), optionally on a topic.
 * `dock: true` shows the panel inside the #stockex-buddy-dock element.
 */
export function openFaqBot(topic?: TopicKey, opts: { dock?: boolean } = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: { topic, dock: Boolean(opts.dock) } }));
}
