import { useEffect, useRef, useState } from "react"
import { TrendingUp, BarChart3, Coins, Banknote, ArrowUpRight } from "lucide-react"
import { StartTradingDialog } from "@/components/landing/auth-dialogs"

// TODO(content): Multi-Asset Indian section — final copy is still pending.
// The four market cards below are the existing placeholder content; do not
// treat them as signed off. Replace when the wording arrives.
// One treatment for all four cards. Each used to carry its own hue
// (blue / emerald / amber / violet) left over from the pre-restyle
// palette. The hue-collapse layer flattens most of those, but it maps
// `text-emerald-*` to the accent — so the Indices card alone came out
// highlighted, which read as a bug rather than a decision.
const markets = [
  {
    icon: TrendingUp,
    title: "Stocks",
    description: "Trade Indian equities like Reliance, TCS, Infosys with real-time market data.",
    iconClass: "bg-white/[0.06] text-[#4D94E6]",
    cardClass:
      "border-white/[0.08] bg-white/[0.02] hover:border-white/20",
    titleClass: "text-white",
    accentClass: "from-[#003E85] to-[#4D94E6]",
    glowClass: "bg-[#4D94E6]/15",
  },
  {
    icon: BarChart3,
    title: "Indices",
    description: "Trade NIFTY 50, BANK NIFTY, SENSEX with tight spreads and fast execution.",
    iconClass: "bg-white/[0.06] text-[#4D94E6]",
    cardClass:
      "border-white/[0.08] bg-white/[0.02] hover:border-white/20",
    titleClass: "text-white",
    accentClass: "from-[#003E85] to-[#4D94E6]",
    glowClass: "bg-[#4D94E6]/15",
  },
  {
    icon: Coins,
    title: "Commodities",
    description: "Gold, Silver, Crude Oil and Natural Gas with competitive pricing.",
    iconClass: "bg-white/[0.06] text-[#4D94E6]",
    cardClass:
      "border-white/[0.08] bg-white/[0.02] hover:border-white/20",
    titleClass: "text-white",
    accentClass: "from-[#003E85] to-[#4D94E6]",
    glowClass: "bg-[#4D94E6]/15",
  },
  {
    icon: Banknote,
    title: "Currency",
    description: "USDINR, EURINR, GBPINR, JPYINR with deep liquidity.",
    iconClass: "bg-white/[0.06] text-[#4D94E6]",
    cardClass:
      "border-white/[0.08] bg-white/[0.02] hover:border-white/20",
    titleClass: "text-white",
    accentClass: "from-[#003E85] to-[#4D94E6]",
    glowClass: "bg-[#4D94E6]/15",
  },
]

function useScrollReveal(threshold = 0.12) {
  const ref = useRef(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true)
          observer.disconnect()
        }
      },
      { threshold, rootMargin: "0px 0px -48px 0px" }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold])

  return { ref, inView }
}

function revealStyle(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? "translateX(0) scale(1)" : "translateX(3rem) scale(0.96)",
    transition: `opacity 0.75s ease-out ${delayMs}ms, transform 0.75s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  }
}

export function MarketAccessSection() {
  const { ref, inView } = useScrollReveal()

  return (
    <section
      ref={ref}
      // Anchor target for the nav's "Trading" item (/#markets). scroll-mt
      // clears the fixed nav pill so the heading isn't hidden under it.
      id="markets"
      className="relative scroll-mt-24 py-20 lg:py-28 overflow-hidden bg-gradient-to-b from-[#060d18] via-[#0a1628] to-[#060d18]"
    >
      <div className="absolute inset-0 pointer-events-none opacity-40 bg-[radial-gradient(ellipse_at_20%_30%,rgba(59,130,246,0.15),transparent_50%),radial-gradient(ellipse_at_80%_70%,rgba(16,185,129,0.1),transparent_45%)]" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div
          className="text-center mb-16 motion-reduce:!opacity-100 motion-reduce:!translate-x-0"
          style={revealStyle(inView, 0)}
        >
          <p className="text-sm font-semibold text-cyan-400 uppercase tracking-wider mb-3">Markets</p>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-white mb-4 text-balance">
            Multi-Asset Indian Market Access
          </h2>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto">
            Access India's top financial markets through a single integrated platform.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {markets.map((market, index) => (
            <div
              key={market.title}
              className="motion-reduce:!opacity-100 motion-reduce:!translate-x-0"
              style={revealStyle(inView, 120 + index * 100)}
            >
              <StartTradingDialog
                trigger={
                  <div
                    className={`group relative rounded-2xl border p-6 cursor-pointer h-full overflow-hidden transition-all duration-500 hover:-translate-y-3 hover:shadow-2xl ${market.cardClass}`}
                  >
                    <div
                      className={`absolute -top-12 -right-12 w-32 h-32 rounded-full blur-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 ${market.glowClass}`}
                    />

                    <div
                      className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${market.accentClass} scale-x-0 group-hover:scale-x-100 origin-left transition-transform duration-500`}
                    />

                    <div className="relative flex items-start justify-between mb-6">
                      <div
                        className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all duration-500 group-hover:scale-110 group-hover:rotate-3 ${inView ? "animate-market-icon-float" : ""} ${market.iconClass}`}
                        style={{ animationDelay: `${index * 0.4}s` }}
                      >
                        <market.icon className="w-8 h-8" />
                      </div>
                      <div className="w-9 h-9 rounded-full border border-white/10 flex items-center justify-center text-gray-500 group-hover:border-white/30 group-hover:text-white group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all duration-300">
                        <ArrowUpRight className="w-4 h-4" />
                      </div>
                    </div>

                    <h3 className={`relative text-xl font-bold mb-3 transition-colors duration-300 ${market.titleClass}`}>
                      {market.title}
                    </h3>
                    <p className="relative text-gray-400 text-sm leading-relaxed group-hover:text-gray-300 transition-colors duration-300">
                      {market.description}
                    </p>

                    <div
                      className={`relative mt-5 h-0.5 w-12 rounded-full bg-gradient-to-r ${market.accentClass} group-hover:w-full transition-all duration-500`}
                    />
                  </div>
                }
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
