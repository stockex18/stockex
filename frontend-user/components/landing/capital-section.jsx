import { useEffect, useRef, useState } from "react"
import { Smartphone, Building2, Shield, CreditCard } from "lucide-react"
import { DepositDialog } from "@/components/landing/auth-dialogs"

// The four payment methods on offer: UPI, Net Banking, Multi Bank, RTGS.
// Styling per card is unchanged — only the labels describe the methods.
const features = [
  {
    icon: Smartphone,
    title: "UPI",
    iconClass: "bg-gradient-to-br from-cyan-500 to-teal-400 text-white shadow-cyan-500/30",
    cardClass:
      "border-cyan-500/25 bg-gradient-to-br from-cyan-950/50 via-slate-900/90 to-slate-950 hover:border-cyan-400/50 hover:shadow-cyan-500/20",
    titleClass: "text-cyan-300",
    accentClass: "from-cyan-500 to-teal-400",
    glowClass: "bg-cyan-500/25",
  },
  {
    icon: Building2,
    title: "Net Banking",
    iconClass: "bg-gradient-to-br from-blue-500 to-indigo-400 text-white shadow-blue-500/30",
    cardClass:
      "border-blue-500/25 bg-gradient-to-br from-blue-950/50 via-slate-900/90 to-slate-950 hover:border-blue-400/50 hover:shadow-blue-500/20",
    titleClass: "text-blue-300",
    accentClass: "from-blue-500 to-indigo-400",
    glowClass: "bg-blue-500/25",
  },
  {
    icon: Shield,
    title: "RTGS",
    iconClass: "bg-gradient-to-br from-emerald-500 to-green-400 text-white shadow-emerald-500/30",
    cardClass:
      "border-emerald-500/25 bg-gradient-to-br from-emerald-950/40 via-slate-900/90 to-slate-950 hover:border-emerald-400/50 hover:shadow-emerald-500/20",
    titleClass: "text-emerald-300",
    accentClass: "from-emerald-500 to-green-400",
    glowClass: "bg-emerald-500/25",
  },
  {
    icon: CreditCard,
    title: "Multi Bank",
    iconClass: "bg-gradient-to-br from-violet-500 to-purple-400 text-white shadow-violet-500/30",
    cardClass:
      "border-violet-500/25 bg-gradient-to-br from-violet-950/40 via-slate-900/90 to-slate-950 hover:border-violet-400/50 hover:shadow-violet-500/20",
    titleClass: "text-violet-300",
    accentClass: "from-violet-500 to-purple-400",
    glowClass: "bg-violet-500/25",
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
      { threshold, rootMargin: "0px 0px -40px 0px" }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold])

  return { ref, inView }
}

function revealFromLeft(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? "translateX(0) scale(1)" : "translateX(-2.5rem) scale(0.96)",
    transition: `opacity 0.7s ease-out ${delayMs}ms, transform 0.7s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  }
}

function revealFromRight(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? "translateX(0)" : "translateX(2.5rem)",
    transition: `opacity 0.7s ease-out ${delayMs}ms, transform 0.7s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  }
}

export function CapitalSection() {
  const { ref, inView } = useScrollReveal()

  return (
    <section
      ref={ref}
      className="relative py-20 lg:py-28 overflow-hidden bg-gradient-to-b from-[#060d18] via-[#0a1628] to-[#060d18]"
    >
      <div className="absolute inset-0 pointer-events-none opacity-35 bg-[radial-gradient(ellipse_at_75%_30%,rgba(34,211,238,0.12),transparent_45%),radial-gradient(ellipse_at_15%_70%,rgba(139,92,246,0.1),transparent_40%)]" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div
            className="relative order-2 lg:order-1 motion-reduce:!opacity-100"
            style={revealFromLeft(inView, 100)}
          >
            <div className="rounded-3xl p-4 sm:p-8 lg:p-10 border border-white/10 bg-slate-900/40 backdrop-blur-sm shadow-2xl shadow-cyan-500/5">
              <div className="grid grid-cols-1 xs:grid-cols-2 gap-3 sm:gap-4">
                {features.map((feature, index) => (
                  <div
                    key={feature.title}
                    className="motion-reduce:!opacity-100"
                    style={revealFromLeft(inView, 180 + index * 90)}
                  >
                    <DepositDialog
                      trigger={
                        <div
                          className={`group relative rounded-2xl p-4 sm:p-6 border cursor-pointer overflow-hidden transition-all duration-500 hover:-translate-y-2 hover:shadow-xl ${feature.cardClass}`}
                        >
                          <div
                            className={`absolute -top-10 -right-10 w-24 h-24 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 ${feature.glowClass}`}
                          />
                          <div
                            className={`absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r ${feature.accentClass} scale-x-0 group-hover:scale-x-100 origin-left transition-transform duration-500`}
                          />
                          <div
                            className={`relative w-10 h-10 sm:w-12 sm:h-12 rounded-xl flex items-center justify-center mb-3 sm:mb-4 shadow-lg transition-all duration-500 group-hover:scale-110 group-hover:rotate-3 ${inView ? "animate-market-icon-float" : ""} ${feature.iconClass}`}
                            style={{ animationDelay: `${index * 0.35}s` }}
                          >
                            <feature.icon className="w-5 h-5 sm:w-6 sm:h-6" />
                          </div>
                          <p
                            className={`relative text-xs sm:text-sm font-semibold transition-colors duration-300 group-hover:text-white ${feature.titleClass}`}
                          >
                            {feature.title}
                          </p>
                        </div>
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="order-1 lg:order-2">
            <p
              className="text-sm font-semibold uppercase tracking-wider mb-3 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-violet-400 motion-reduce:!opacity-100"
              style={revealFromRight(inView, 0)}
            >
              Payments
            </p>
            <h2
              className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-6 text-balance leading-tight motion-reduce:!opacity-100"
              style={revealFromRight(inView, 80)}
            >
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-blue-300 to-violet-300 animate-gradient-text">
                Fast & Secure
              </span>
              <br />
              <span className="text-white">Transactions</span>
            </h2>
            <p
              className="text-lg text-gray-400 mb-8 motion-reduce:!opacity-100"
              style={revealFromRight(inView, 160)}
            >
              Deposit and withdraw funds instantly with India&apos;s most trusted payment methods.{" "}
              <span className="text-emerald-300/90 font-medium">Zero deposit fees</span> with{" "}
              <span className="text-cyan-300/90 font-medium">same-day processing</span>.
            </p>

            <div
              className="flex flex-wrap gap-3 motion-reduce:!opacity-100"
              style={revealFromRight(inView, 240)}
            >
              {["UPI", "NEFT", "IMPS", "RTGS"].map((tag) => (
                <span
                  key={tag}
                  className="px-4 py-1.5 rounded-full text-xs font-semibold border border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 hover:border-cyan-400/50 transition-all duration-300"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
