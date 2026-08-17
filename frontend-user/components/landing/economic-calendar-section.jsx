
import { useState } from "react"
import { Calendar, Timer, TrendingUp, TrendingDown, Minus, ChevronDown } from "lucide-react"

const impactConfig = {
  High:   { color: "text-yellow-400",    dot: "bg-yellow-accent",    badge: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
  Medium: { color: "text-blue-400", dot: "bg-blue-500", badge: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  Low:    { color: "text-gray-400",   dot: "bg-gray-500",   badge: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
}

// LIVE Market — market-moving events.
// TODO(data): the fetch method for these events is not decided yet. The list
// below is static placeholder data — wire it to a real source once the
// provider is chosen.
const events = [
  { time: "10:00", event: "RBI Policy Decision", impact: "High", forecast: "6.50%", previous: "6.50%" },
  { time: "11:30", event: "CPI Inflation (YoY)", impact: "High", forecast: "5.2%", previous: "5.1%" },
  { time: "14:00", event: "GDP Growth Rate (QoQ)", impact: "High", forecast: "7.8%", previous: "7.6%" },
  { time: "15:30", event: "Manufacturing PMI", impact: "Medium", forecast: "56.2", previous: "55.8" },
  { time: "16:00", event: "Services PMI", impact: "Medium", forecast: "58.5", previous: "57.9" },
  { time: "17:00", event: "Trade Balance", impact: "Medium", forecast: "-$18.5B", previous: "-$19.2B" },
  { time: "18:30", event: "US Fed Rate Decision", impact: "High", forecast: "5.25%", previous: "5.25%" },
  { time: "20:00", event: "Crude Oil Inventory", impact: "Low", forecast: "-1.2M", previous: "-0.8M" },
]

function ActualBadge({ actual, forecast }) {
  if (!actual) {
    return <span className="text-muted-foreground text-sm">Pending</span>
  }
  const actualNum = parseFloat(actual)
  const forecastNum = parseFloat(forecast)
  const isBetter = !isNaN(actualNum) && !isNaN(forecastNum) && actualNum > forecastNum
  const isWorse  = !isNaN(actualNum) && !isNaN(forecastNum) && actualNum < forecastNum

  return (
    <span className={`inline-flex items-center gap-1 font-semibold text-sm ${isBetter ? "text-green-600" : isWorse ? "text-red-600" : "text-foreground"}`}>
      {isBetter ? <TrendingUp className="w-3.5 h-3.5" /> : isWorse ? <TrendingDown className="w-3.5 h-3.5" /> : <Minus className="w-3.5 h-3.5" />}
      {actual}
    </span>
  )
}

export function EconomicCalendarSection() {
  const [filter, setFilter] = useState("All")
  const [expanded, setExpanded] = useState(null)

  const filters = ["All", "High", "Medium", "Low"]

  const filtered = filter === "All" ? events : events.filter(e => e.impact === filter)

  const now = new Date()
  const timeLabel = now.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })

  return (
    <section className="py-20 lg:py-28 bg-deep-blue">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">

        {/* Header */}
        <div className="text-center mb-12">
          <p className="text-sm font-semibold text-yellow-accent uppercase tracking-wider mb-3">Economic Calendar</p>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-white mb-4 text-balance">
            Live Market-Moving Events
          </h2>
          <p className="text-lg text-white/70 max-w-2xl mx-auto">
            Stay ahead of major economic releases and central bank decisions that drive volatility.
          </p>
        </div>

        {/* Date + Live badge */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-2 text-sm text-white/70">
            <Calendar className="w-4 h-4" />
            <span>{timeLabel}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500"></span>
            </span>
            <span className="text-xs font-semibold text-green-600 uppercase tracking-wider">Live</span>
          </div>
        </div>

        {/* Impact Filters */}
        <div className="flex flex-wrap gap-2 mb-6">
          {filters.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-5 py-2 rounded-full text-sm font-medium transition-all border ${
                filter === f
                  ? f === "High"   ? "bg-yellow-accent text-deep-blue border-yellow-accent"
                  : f === "Medium" ? "bg-blue-500 text-white border-blue-500"
                  : f === "Low"    ? "bg-gray-500 text-white border-gray-500"
                  :                  "bg-yellow-accent text-deep-blue border-yellow-accent"
                  : "bg-white/10 text-white/70 border-white/20 hover:bg-white/20"
              }`}
            >
              {f !== "All" && (
                <span className={`inline-block w-2 h-2 rounded-full mr-2 ${
                  f === "High" ? "bg-yellow-300" : f === "Medium" ? "bg-blue-300" : "bg-gray-300"
                } ${filter === f ? "opacity-100" : ""}`} />
              )}
              {f}
            </button>
          ))}
        </div>

        {/* Calendar Table */}
        <div className="bg-white/10 backdrop-blur-sm rounded-2xl border border-white/20 overflow-hidden">
          {/* Desktop Header */}
          <div className="hidden md:grid grid-cols-[80px_1fr_110px_100px_100px] gap-4 px-6 py-3 bg-white/10 text-white">
            {["Time", "Event", "Impact", "Forecast", "Previous"].map(h => (
              <span key={h} className="text-xs font-semibold uppercase tracking-wide">{h}</span>
            ))}
          </div>

          <div className="divide-y divide-white/10">
            {filtered.map((event, i) => (
              <div key={i}>
                {/* Desktop Row */}
                <div className="hidden md:grid grid-cols-[80px_1fr_110px_100px_100px] gap-4 items-center px-6 py-4 hover:bg-white/5 transition-colors">
                  <div className="flex items-center gap-1.5 text-sm font-mono text-white">
                    <Timer className="w-3.5 h-3.5 text-white/60" />
                    {event.time}
                  </div>
                  <span className="text-sm font-medium text-white">{event.event}</span>
                  <div>
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${impactConfig[event.impact].badge}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${impactConfig[event.impact].dot}`} />
                      {event.impact}
                    </span>
                  </div>
                  <span className="text-sm text-white/70 font-mono">{event.forecast}</span>
                  <span className="text-sm text-white/70 font-mono">{event.previous}</span>
                </div>

                {/* Mobile Row */}
                <div className="md:hidden">
                  <button
                    className="w-full flex items-center justify-between px-4 py-4 text-left hover:bg-white/5 transition-colors"
                    onClick={() => setExpanded(expanded === i ? null : i)}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-1 h-10 rounded-full ${impactConfig[event.impact].dot}`} />
                      <div>
                        <div className="text-sm font-semibold text-white">{event.event}</div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-white/60 font-mono">{event.time}</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-semibold ${impactConfig[event.impact].color}`}>{event.impact}</span>
                      <ChevronDown className={`w-4 h-4 text-white/60 transition-transform ${expanded === i ? "rotate-180" : ""}`} />
                    </div>
                  </button>
                  {expanded === i && (
                    <div className="px-4 pb-4 grid grid-cols-3 gap-3 text-center bg-white/5">
                      {[
                        { label: "Impact",   value: <span className={`text-xs font-semibold ${impactConfig[event.impact].color}`}>{event.impact}</span> },
                        { label: "Forecast", value: <span className="text-sm font-mono text-white">{event.forecast}</span> },
                        { label: "Previous", value: <span className="text-sm font-mono text-white">{event.previous}</span> },
                      ].map(({ label, value }) => (
                        <div key={label} className="bg-white/10 rounded-xl p-3 border border-white/20">
                          <div className="text-xs text-white/60 mb-1">{label}</div>
                          {value}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Footer */}
          <div className="bg-white/5 px-6 py-4 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-2">
            <p className="text-sm text-white/60">
              All times displayed in <span className="font-semibold text-white">UTC</span>. Data updates every 60 seconds.
            </p>
            <div className="flex items-center gap-4 text-xs text-white/60">
              {["High", "Medium", "Low"].map(lvl => (
                <span key={lvl} className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${impactConfig[lvl].dot}`} />
                  {lvl} Impact
                </span>
              ))}
            </div>
          </div>
        </div>

      </div>
    </section>
  )
}
