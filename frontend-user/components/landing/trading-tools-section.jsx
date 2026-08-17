import { useEffect, useRef, useState } from "react"
import Link from 'next/link';
import { Calculator, PieChart, BarChart2, Grid3X3, ArrowUpRight } from "lucide-react"

// Smart Trading Tools.
// TODO(content): the final tool list is still pending. Brokerage Calculator
// and P&L Calculator are confirmed; the other two below stay as placeholders
// until the list is signed off.
const tools = [
  {
    icon: Calculator,
    title: "Brokerage Calculator",
    description: "Calculate your trading costs including brokerage, STT, and other charges.",
    href: "/tools/brokerage-calculator",
    iconClass: "bg-gradient-to-br from-blue-500 to-cyan-400 text-white shadow-lg shadow-blue-500/30",
    cardClass:
      "border-blue-500/25 bg-gradient-to-br from-blue-950/50 via-slate-900/90 to-slate-950 hover:border-blue-400/60 hover:shadow-blue-500/25",
    titleClass: "text-blue-300 group-hover:text-blue-200",
    accentClass: "from-blue-500 to-cyan-400",
    glowClass: "bg-blue-500/20",
  },
  {
    icon: PieChart,
    title: "Profit & Loss Calculator",
    description: "Estimate your potential profits and losses before placing trades.",
    href: "/tools/profit-loss-calculator",
    iconClass: "bg-gradient-to-br from-emerald-500 to-green-400 text-white shadow-lg shadow-emerald-500/30",
    cardClass:
      "border-emerald-500/25 bg-gradient-to-br from-emerald-950/40 via-slate-900/90 to-slate-950 hover:border-emerald-400/60 hover:shadow-emerald-500/25",
    titleClass: "text-emerald-300 group-hover:text-emerald-200",
    accentClass: "from-emerald-500 to-green-400",
    glowClass: "bg-emerald-500/20",
  },
  {
    icon: BarChart2,
    title: "Margin Calculator",
    description: "Calculate margin requirements for your positions across segments.",
    href: "/tools/margin-calculator",
    iconClass: "bg-gradient-to-br from-amber-500 to-orange-400 text-white shadow-lg shadow-amber-500/30",
    cardClass:
      "border-amber-500/25 bg-gradient-to-br from-amber-950/35 via-slate-900/90 to-slate-950 hover:border-amber-400/60 hover:shadow-amber-500/25",
    titleClass: "text-amber-300 group-hover:text-amber-200",
    accentClass: "from-amber-500 to-orange-400",
    glowClass: "bg-amber-500/20",
  },
  {
    icon: Grid3X3,
    title: "Market Heatmap",
    description: "Visualize market performance with interactive sector heatmaps.",
    href: "/tools/market-heatmap",
    iconClass: "bg-gradient-to-br from-violet-500 to-fuchsia-400 text-white shadow-lg shadow-violet-500/30",
    cardClass:
      "border-violet-500/25 bg-gradient-to-br from-violet-950/40 via-slate-900/90 to-slate-950 hover:border-violet-400/60 hover:shadow-violet-500/25",
    titleClass: "text-violet-300 group-hover:text-violet-200",
    accentClass: "from-violet-500 to-fuchsia-400",
    glowClass: "bg-violet-500/20",
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

function revealUp(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? "translateY(0) scale(1)" : "translateY(2.5rem) scale(0.96)",
    transition: `opacity 0.75s ease-out ${delayMs}ms, transform 0.75s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  }
}

export function TradingToolsSection() {
  const { ref, inView } = useScrollReveal()

  return (
    <section
      ref={ref}
      className="relative py-20 lg:py-28 overflow-hidden bg-gradient-to-b from-[#060d18] via-[#0a1628] to-[#060d18]"
    >
      <div className="absolute inset-0 pointer-events-none opacity-40 bg-[radial-gradient(ellipse_at_50%_20%,rgba(99,102,241,0.15),transparent_50%),radial-gradient(ellipse_at_80%_80%,rgba(34,211,238,0.1),transparent_45%)]" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div
          className="text-center mb-16 motion-reduce:!opacity-100"
          style={revealUp(inView, 0)}
        >
          <p className="text-sm font-semibold uppercase tracking-wider mb-3 text-transparent bg-clip-text bg-gradient-to-r from-violet-400 to-cyan-400">
            Tools
          </p>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-4 text-balance leading-tight">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-blue-300 to-violet-300 animate-gradient-text">
              Smart Trading
            </span>
            <br />
            <span className="text-white">Tools</span>
          </h2>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto">
            Powerful calculators and analysis tools to make{" "}
            <span className="text-cyan-300/90 font-medium">informed trading decisions</span>.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {tools.map((tool, index) => (
            <div
              key={tool.title}
              className="motion-reduce:!opacity-100"
              style={revealUp(inView, 120 + index * 100)}
            >
              <Link
                href={tool.href}
                className={`group relative block rounded-2xl border p-6 h-full overflow-hidden transition-all duration-500 hover:-translate-y-3 hover:shadow-2xl ${tool.cardClass}`}
              >
                <div
                  className={`absolute -top-12 -right-12 w-32 h-32 rounded-full blur-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 ${tool.glowClass}`}
                />

                <div
                  className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${tool.accentClass} scale-x-0 group-hover:scale-x-100 origin-left transition-transform duration-500`}
                />

                <div className="relative flex items-start justify-between mb-6">
                  <div
                    className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all duration-500 group-hover:scale-110 group-hover:rotate-3 ${inView ? "animate-market-icon-float" : ""} ${tool.iconClass}`}
                    style={{ animationDelay: `${index * 0.4}s` }}
                  >
                    <tool.icon className="w-8 h-8" />
                  </div>
                  <div className="w-9 h-9 rounded-full border border-white/10 flex items-center justify-center text-gray-500 group-hover:border-white/30 group-hover:text-white group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all duration-300">
                    <ArrowUpRight className="w-4 h-4" />
                  </div>
                </div>

                <h3 className={`relative text-lg font-bold mb-3 transition-colors duration-300 ${tool.titleClass}`}>
                  {tool.title}
                </h3>
                <p className="relative text-gray-400 text-sm leading-relaxed group-hover:text-gray-300 transition-colors duration-300">
                  {tool.description}
                </p>

                <div
                  className={`relative mt-5 h-0.5 w-12 rounded-full bg-gradient-to-r ${tool.accentClass} group-hover:w-full transition-all duration-500`}
                />
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
