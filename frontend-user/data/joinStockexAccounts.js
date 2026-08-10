import {
  Building2,
  TrendingUp,
  Dices,
  Network,
  Users,
  LineChart,
  Clock,
  Zap,
  Trophy,
  Target,
  Sparkles,
  Wallet,
  Gamepad2,
  UserPlus,
  BarChart3,
  Coins,
  Share2,
  Layers,
} from 'lucide-react';

const brokerageAccount = {
  id: 'brokerage',
  slug: 'stockex-brokerage',
  icon: Building2,
  title: 'Stockex Brokerage',
  description: 'Run your own brokerage — earn brokerage, game share & network income from every client under you.',
  features: [
    { icon: TrendingUp, text: 'Brokerage on every client trade — NSE, BSE, MCX, options, crypto, forex & games' },
    { icon: Gamepad2, text: 'Game profit share when clients play skill-based games' },
    { icon: UserPlus, text: 'Referral earnings when your clients invite friends' },
    { icon: Network, text: 'Sub-broker network — earn from their client book too' },
    { icon: Wallet, text: 'Distributed cash account — funds from super admin to grow your book' },
    { icon: Layers, text: 'Full admin dashboard — limits, segments, users & sub-brokers' },
  ],
  benefitSources: [
    { label: 'Client trading', detail: 'Brokerage on open & close of every order in your book' },
    { label: 'Games wallet', detail: 'Hierarchy share when clients bet, win or play casino rounds' },
    { label: 'Referral chain', detail: 'Commission when referred users trade or play games' },
    { label: 'Sub-broker book', detail: 'Override income from brokers & sub-brokers you create' },
  ],
  buttonText: 'Explore Brokerage',
  buttonStyle: 'bg-[#C6F642] hover:bg-[#b8ea2e] text-[#101210]',
  cardStyle: 'border-white/10 hover:border-white/20',
  signupHref: '/broker/login?register=true',
  ctaLabel: 'Start as Broker',
  vlog: {
    tagline: 'Turn every client trade into your recurring income stream.',
    heroGradient: 'from-[#101210] via-[#181B18] to-[#101210]',
    accent: 'text-[#C6F642]',
    accentBg: 'bg-yellow-accent',
    chapters: [
      {
        title: 'What is Stockex Brokerage?',
        body: 'Stockex Brokerage is built for entrepreneurs who want to run a real brokerage business — not just trade for themselves. You onboard clients, they trade on the platform, and you earn brokerage on every order they place. It is a scalable, network-driven income model.',
      },
      {
        title: 'Earn on every client trade',
        body: 'Every time your client buys or sells — NSE, BSE, MCX, options, crypto, forex — or plays skill-based games, you earn brokerage. The more active your book, the more you make. No ceiling on how large your client base can grow.',
      },
      {
        title: 'Grow your broker network',
        body: 'Build a broker network under you. Recruit subbrokers, assign territories, and share revenue. Your network works for you even when you are offline — classic brokerage scale, powered by Stockex technology.',
      },
      {
        title: 'Full control dashboard',
        body: 'Create and manage subbrokers, track client activity, monitor P&L, and control limits — all from one admin dashboard. White-label ready, professional, and built for Indian markets.',
      },
    ],
    summary: [
      'Recurring brokerage income from client trades',
      'Multi-level broker & subbroker network',
      'Admin tools to manage clients and limits',
      'White-label platform — your brand, our tech',
    ],
  },
};

const tradingAccount = {
  id: 'trading',
  slug: 'stockex-trading',
  icon: LineChart,
  title: 'STOCKEX TRADING',
  description: 'Trade every market — options, stocks, commodities & crypto from one terminal.',
  features: [
    { icon: LineChart, text: 'NSE, BSE, MCX, options, crypto & forex' },
    { icon: Zap, text: 'Unlimited trading opportunity with real-time data' },
    { icon: Clock, text: 'Indian sessions, commodity hours & 24/7 crypto' },
    { icon: Share2, text: 'Referral rewards — earn when friends you invite trade' },
  ],
  buttonText: 'Explore Trading',
  buttonStyle: 'bg-[#C6F642] hover:bg-[#b8ea2e] text-[#101210]',
  cardStyle: 'border-[#E0E5E0] hover:border-[#141614]',
  featured: true,
  signupHref: '/login?register=true',
  ctaLabel: 'Open Trading Account',
  vlog: {
    tagline: 'One platform. Every market. Unlimited opportunities.',
    heroGradient: 'from-[#0B3C6D] via-[#1565C0] to-[#0D47A1]',
    accent: 'text-[#C6F642]',
    accentBg: 'bg-yellow-accent',
    chapters: [
      {
        title: 'All markets in one terminal',
        body: 'Trade NSE & BSE equities, index & stock options, MCX commodities, crypto spot pairs, and forex — all from a single Stockex terminal. No switching apps, no fragmented experience.',
      },
      {
        title: 'Options, stocks, commodities & crypto',
        body: 'Whether you scalp options, swing stocks, trade crude & gold, or catch crypto moves — Stockex gives you the charts, margin engine, and execution speed you need.',
      },
      {
        title: 'Unlimited trading opportunity',
        body: 'No artificial caps on how much you can trade. With proper margin and risk controls, you can scale your strategy as your skill and capital grow.',
      },
      {
        title: 'Referral income on trading',
        body: 'Share your referral link with friends. When they register and trade, you earn referral commission on their trading activity — passive income while you focus on the markets.',
      },
    ],
    summary: [
      'NSE, BSE, MCX, options, crypto & forex',
      'Professional charts & order types',
      'Real-time quotes and fast execution',
      'Referral rewards on friend trading activity',
    ],
  },
};

const casinoAccount = {
  id: 'casino',
  slug: 'stockex-casino',
  icon: Dices,
  title: 'STOCKEX TRADING CASINO',
  description: 'Skill-based games tied to live markets — fast rounds, jackpots & daily challenges.',
  features: [
    { icon: Clock, text: 'Make money every 15 minutes — fast game rounds' },
    { icon: Trophy, text: 'NIFTY bracket, BTC jackpot, number games & more' },
    { icon: Zap, text: 'Real-time payouts tied to live market prices' },
    { icon: UserPlus, text: 'Referral rewards — earn when friends play games' },
  ],
  buttonText: 'Enter the Casino',
  buttonStyle: 'bg-[#141614] hover:bg-[#2C312C] text-white',
  cardStyle: 'border-[#E0E5E0] hover:border-[#141614]',
  casino: true,
  signupHref: '/login?register=true',
  ctaLabel: 'Play Games Now',
  vlog: {
    tagline: 'Where trading meets thrill — skill games, live rounds, real wins.',
    heroGradient: 'from-[#101210] via-[#181B18] to-[#101210]',
    accent: 'text-[#C6F642]',
    accentBg: 'bg-gradient-to-r from-fuchsia-500 to-pink-500',
    chapters: [
      {
        title: 'Make money every 15 minutes',
        body: 'Fast-paced game rounds reset every 15 minutes. Predict NIFTY direction, bracket challenges, jackpot rounds — quick decisions, quick results. Perfect for traders who love action.',
      },
      {
        title: 'All-day games & challenges',
        body: 'From morning session to late-night crypto games — the casino never sleeps. Daily challenges, leaderboards, and tournaments keep the energy high all day long.',
      },
      {
        title: 'Why skill-based games?',
        body: 'Every game is tied to real market movement — not random luck. Your market reading skill is your edge. Dedicated games wallet keeps casino play separate from your trading ledger.',
      },
      {
        title: 'Referral income on games',
        body: 'Invite friends to play. When they bet and win in games, you earn referral commission on their games activity — grow your network and your earnings together.',
      },
    ],
    summary: [
      '15-minute fast rounds with live results',
      'Skill-based games tied to real markets',
      'Leaderboards, jackpots & daily challenges',
      'Referral rewards on friend games activity',
    ],
  },
};

/** @deprecated use joinStockexSections — kept for vlog pages & lookups */
export const joinStockexAccounts = [brokerageAccount, tradingAccount, casinoAccount];

export const joinStockexSections = [
  {
    id: 'broker',
    eyebrow: 'For entrepreneurs',
    title: 'Join Stockex as a Broker',
    subtitle:
      'Build your brokerage business — earn brokerage from client trades, game share from casino play, and override income from your sub-broker network.',
    accounts: [brokerageAccount],
    layout: 'broker',
  },
  {
    id: 'client',
    eyebrow: 'For traders & players',
    title: 'Join Stockex as a Client',
    subtitle:
      'Trade every market or play skill-based games — and earn referral rewards when you invite friends to trade or play.',
    accounts: [tradingAccount, casinoAccount],
    layout: 'client',
    referralHighlight: {
      icon: Coins,
      title: 'Referral rewards on trading & games',
      points: [
        'Share your unique referral link after signup',
        'Earn when friends trade on NSE, BSE, MCX, options or crypto',
        'Earn when friends play skill-based casino games',
        'Passive income — your network works while you trade or play',
      ],
    },
  },
];

export function getJoinAccountBySlug(slug) {
  return joinStockexAccounts.find((a) => a.slug === slug) ?? null;
}
