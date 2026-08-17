import { useState, useEffect, useRef } from "react"
import { TrendingUp, TrendingDown, Radio } from "lucide-react"
import { formatCoins } from "@/utils/stockexCoins"

// DATA SOURCES for this "Real-Time Market" section:
//   • NSE / BSE / MCX quotes → Zerodha API
//   • Crypto, currency and forex quotes → the crypto/FX feed
// Kept as a dev note rather than on-page copy: naming the upstream vendor
// is a commercial decision, not marketing copy, and the brief marks the
// API list as internal ("not to display as-is"). The rows below are still
// representative sample quotes — wiring this section to the live feed is
// separate work.

const categoryStyle = {
  Stocks: {
    avatar: "bg-white/[0.06] text-[#4D94E6] border-white/10",
    badge: "bg-[#4D94E6]/12 text-[#4D94E6] border-[#4D94E6]/25",
  },
  Indices: {
    avatar: "bg-white/[0.06] text-[#4D94E6] border-white/10",
    badge: "bg-[#4D94E6]/12 text-[#4D94E6] border-[#4D94E6]/25",
  },
  Commodities: {
    avatar: "bg-white/[0.06] text-[#4D94E6] border-white/10",
    badge: "bg-[#4D94E6]/12 text-[#4D94E6] border-[#4D94E6]/25",
  },
  Currency: {
    avatar: "bg-white/[0.06] text-[#4D94E6] border-white/10",
    badge: "bg-[#4D94E6]/12 text-[#4D94E6] border-[#4D94E6]/25",
  },
}

// One accent for the selected tab, not five. A per-tab colour ramp
// (cyan → blue → emerald → amber → violet) made the filter row look like
// a legend for categories that don't otherwise carry colour anywhere on
// the page. Selection is a single state, so it gets a single treatment:
// solid lime, ink label.
const TAB_ACTIVE = "bg-[#003E85] text-white"
const TAB_IDLE =
  "bg-white/[0.05] text-white/55 border border-white/10 hover:text-white hover:bg-white/[0.09]"

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

function revealFromLeft(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? "translateX(0)" : "translateX(-3rem)",
    transition: `opacity 0.7s ease-out ${delayMs}ms, transform 0.7s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  }
}

const instruments = [
  { name: "RELIANCE", price: 2847.5, change: 2.35, category: "Stocks", market: "NSE" },
  { name: "NIFTY 50", price: 22456.8, change: 0.85, category: "Indices", market: "NSE" },
  { name: "BANK NIFTY", price: 47892.15, change: -0.42, category: "Indices", market: "NSE" },
  { name: "GOLD", price: 71250.0, change: 1.12, category: "Commodities", market: "MCX" },
  { name: "USDINR", price: 83.42, change: -0.15, category: "Currency", market: "NSE" },
  { name: "TCS", price: 3892.4, change: 1.15, category: "Stocks", market: "NSE" },
  { name: "INFOSYS", price: 1567.8, change: -0.45, category: "Stocks", market: "NSE" },
  { name: "CRUDE OIL", price: 6542.0, change: 0.78, category: "Commodities", market: "MCX" },
]

export function PricingTableSection() {
  const [activeTab, setActiveTab] = useState("All")
  const [prices, setPrices] = useState(instruments)
  const { ref, inView } = useScrollReveal()

  useEffect(() => {
    const interval = setInterval(() => {
      setPrices((prev) =>
        prev.map((instrument) => ({
          ...instrument,
          price: instrument.price + (Math.random() - 0.5) * 0.002 * instrument.price,
          change: instrument.change + (Math.random() - 0.5) * 0.05,
        }))
      )
    }, 2000)

    return () => clearInterval(interval)
  }, [])

  const tabs = ["All", "Stocks", "Indices", "Commodities", "Currency"]

  const filteredPrices =
    activeTab === "All" ? prices : prices.filter((p) => p.category === activeTab)

  return (
    <section
      ref={ref}
      className="relative py-20 lg:py-28 overflow-hidden bg-gradient-to-b from-[#060d18] via-[#0a1628] to-[#060d18]"
    >
      {/* Animated background */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute inset-0 opacity-[0.04] animate-grid-fade bg-[linear-gradient(rgba(34,211,238,0.5)_1px,transparent_1px),linear-gradient(90deg,rgba(34,211,238,0.5)_1px,transparent_1px)] bg-[size:48px_48px]" />
        <div className="absolute top-1/4 -left-20 w-72 h-72 rounded-full bg-cyan-500/15 blur-3xl animate-orb-drift" />
        <div className="absolute bottom-1/4 -right-16 w-80 h-80 rounded-full bg-violet-500/12 blur-3xl animate-orb-drift-slow" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full bg-blue-500/8 blur-3xl animate-market-glow" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_0%,rgba(34,211,238,0.12),transparent_55%)]" />
      </div>

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div
          className="text-center mb-12 motion-reduce:!opacity-100 motion-reduce:!translate-x-0"
          style={revealFromLeft(inView, 0)}
        >
          <p className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-wider mb-3 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-emerald-400">
            <span className="relative flex h-2 w-2">
              <span className="animate-live-pulse absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            Live Data
          </p>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-4 text-balance leading-tight">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-blue-300 to-violet-300 animate-gradient-text">
              Real-Time Market
            </span>
            <br />
            <span className="text-white">Prices</span>
          </h2>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto">
            Track live prices across Indian markets with{" "}
            <span className="text-cyan-300/90 font-medium">instant updates</span>.
          </p>
        </div>

        <div
          className="flex flex-wrap justify-center gap-2 mb-8 motion-reduce:!opacity-100 motion-reduce:!translate-x-0"
          style={revealFromLeft(inView, 120)}
        >
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-2.5 rounded-full text-[13px] font-semibold transition-colors duration-200 ${
                activeTab === tab ? TAB_ACTIVE : TAB_IDLE
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        <div
          className="rounded-2xl border border-white/10 overflow-hidden shadow-2xl shadow-cyan-500/5 backdrop-blur-sm motion-reduce:!opacity-100 motion-reduce:!translate-x-0"
          style={revealFromLeft(inView, 220)}
        >
          <div className="flex items-center justify-between px-4 sm:px-6 py-3 bg-slate-900/80 border-b border-white/10">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Radio className="w-3.5 h-3.5 text-emerald-400 animate-live-pulse" />
              <span>Streaming market feed</span>
            </div>
            <span className="text-[10px] uppercase tracking-wider text-cyan-400/80 font-semibold">
              Updated live
            </span>
          </div>

          <div className="overflow-x-auto bg-slate-900/60">
            <table className="w-full min-w-[600px]">
              <thead>
                <tr className="bg-gradient-to-r from-cyan-600/90 via-blue-600/90 to-violet-600/90 text-white">
                  <th className="text-left py-4 px-6 text-sm font-semibold">Instrument</th>
                  <th className="text-right py-4 px-6 text-sm font-semibold">Price</th>
                  <th className="text-right py-4 px-6 text-sm font-semibold">Change</th>
                  <th className="text-right py-4 px-6 text-sm font-semibold">Market</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filteredPrices.map((instrument, index) => {
                  const style = categoryStyle[instrument.category] || categoryStyle.Stocks
                  const isUp = instrument.change >= 0

                  return (
                    <tr
                      key={`${instrument.name}-${index}`}
                      className="group hover:bg-white/5 transition-all duration-300"
                      style={{
                        opacity: inView ? 1 : 0,
                        transform: inView ? "translateX(0)" : "translateX(-1.5rem)",
                        transition: `opacity 0.5s ease-out ${300 + index * 50}ms, transform 0.5s ease-out ${300 + index * 50}ms, background-color 0.2s`,
                      }}
                    >
                      <td className="py-4 px-6">
                        <div className="flex items-center gap-3">
                          <div
                            className={`w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0 transition-transform duration-300 group-hover:scale-110 ${style.avatar}`}
                          >
                            <span className="text-xs font-bold">{instrument.name.substring(0, 2)}</span>
                          </div>
                          <div>
                            <div className="font-semibold text-white group-hover:text-cyan-100 transition-colors">
                              {instrument.name}
                            </div>
                            <div className={`text-xs inline-block mt-0.5 px-2 py-0.5 rounded-full border ${style.badge}`}>
                              {instrument.category}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="py-4 px-6 text-right font-mono font-semibold text-cyan-100 tabular-nums">
                        {formatCoins(instrument.price)}
                      </td>
                      <td className="py-4 px-6 text-right">
                        <div
                          className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-sm font-semibold border ${
                            isUp
                              ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                          }`}
                        >
                          {isUp ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                          {isUp ? "+" : ""}
                          {instrument.change.toFixed(2)}%
                        </div>
                      </td>
                      <td className="py-4 px-6 text-right">
                        <span className="px-3 py-1 bg-slate-800 border border-white/10 rounded-full text-xs font-medium text-gray-300">
                          {instrument.market}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  )
}
