import {
  LineChart,
  GraduationCap,
  Clock,
  Zap,
  UserPlus,
  Coins,
  Share2,
  ShieldCheck,
  Wallet,
  RefreshCw,
} from 'lucide-react';

/* StockEx offers exactly TWO accounts: one real, one demo.
 *
 * This file used to define three — Broker A/C, Trading and Prediction
 * Games — and the landing page presented all three as account types.
 * Brokerage and Games are PRODUCTS, not accounts: they still have their
 * own pages (/ib-management, /nifty-games) and their own nav entries,
 * they are simply no longer offered as separate accounts to open.
 *
 * If a third account is ever added, add it here and to the `accounts`
 * array below — `AccountsSection` renders whatever this exports. */

const realAccount = {
  id: 'real',
  slug: 'stockex-real',
  icon: LineChart,
  title: 'Real Account',
  description:
    'Trade every market with real funds — options, stocks, commodities & crypto from one terminal.',
  features: [
    { icon: LineChart, text: 'Every segment — NSE, BSE, MCX, options, crypto & forex' },
    { icon: Zap, text: 'Unlimited trading opportunity with real-time data' },
    { icon: Clock, text: 'Crypto trading available 23 hours: 00:00 – 23:00' },
    { icon: ShieldCheck, text: 'Priority support, dedicated manager & API access as you scale' },
    { icon: Share2, text: 'Referral rewards — earn on your friends’ trading activity' },
  ],
  buttonText: 'Open Real Account',
  buttonStyle: 'bg-[#003E85] hover:bg-[#00529E] text-white',
  cardStyle: 'border-[#E0E5E0] hover:border-[#141614]',
  featured: true,
  signupHref: '/register',
  ctaLabel: 'Open Real Account',
};

const demoAccount = {
  id: 'demo',
  slug: 'stockex-demo',
  icon: GraduationCap,
  title: 'Demo Account',
  description:
    'Practise on live NSE, BSE & MCX prices with virtual funds — no KYC, no deposit, no risk.',
  features: [
    { icon: Wallet, text: 'Virtual funds — nothing of yours is ever at stake' },
    { icon: LineChart, text: 'Live market prices and the full order set: Market, Limit, SL, SL-M' },
    { icon: RefreshCw, text: 'Unlimited resets — start over whenever a strategy needs a clean run' },
    { icon: UserPlus, text: 'No KYC and no deposit to begin' },
  ],
  buttonText: 'Try Demo Account',
  buttonStyle: 'bg-[#141614] hover:bg-[#2C312C] text-white',
  cardStyle: 'border-[#E0E5E0] hover:border-[#141614]',
  signupHref: '/register',
  ctaLabel: 'Try Demo Account',
};

export const joinStockexAccounts = [realAccount, demoAccount];

export const joinStockexSections = [
  {
    id: 'client',
    eyebrow: 'Two accounts',
    title: 'Open your StockEx account',
    subtitle:
      'One real account to trade every market, and a demo account to practise on live prices with virtual funds. Both open in minutes.',
    accounts: [realAccount, demoAccount],
    layout: 'client',
    referralHighlight: {
      icon: Coins,
      title: 'Referral rewards',
      points: [
        'Share your unique referral link after signup',
        'Earn when friends trade on NSE, BSE, MCX, options or crypto',
        'Passive income — your network works while you trade',
      ],
    },
  },
];

export function getJoinAccountBySlug(slug) {
  return joinStockexAccounts.find((a) => a.slug === slug) ?? null;
}
