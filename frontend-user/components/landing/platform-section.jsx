import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/landing/ui/button"
import { Check, Monitor, Smartphone, Globe } from "lucide-react"
import Link from 'next/link';

const features = [
  { text: "Advanced charts with technical indicators", color: "from-cyan-500 to-blue-500" },
  { text: "Real-time order execution", color: "from-emerald-500 to-green-400" },
  { text: "Portfolio management tools", color: "from-violet-500 to-purple-400" },
  { text: "Secure login with 2FA", color: "from-amber-500 to-orange-400" },
]

const platforms = [
  {
    icon: Globe,
    name: "Web",
    desc: "Trade from any browser",
    iconClass: "text-cyan-400",
    cardClass: "border-cyan-500/20 bg-cyan-500/5 hover:border-cyan-400/40 hover:bg-cyan-500/10",
  },
  {
    icon: Smartphone,
    name: "Mobile",
    desc: "iOS & Android apps",
    iconClass: "text-violet-400",
    cardClass: "border-violet-500/20 bg-violet-500/5 hover:border-violet-400/40 hover:bg-violet-500/10",
  },
  {
    icon: Monitor,
    name: "Desktop",
    desc: "Windows & Mac",
    iconClass: "text-blue-400",
    cardClass: "border-blue-500/20 bg-blue-500/5 hover:border-blue-400/40 hover:bg-blue-500/10",
  },
]

function useScrollReveal(threshold = 0.15) {
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

function revealLeft(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? "translateX(0)" : "translateX(-2.5rem)",
    transition: `opacity 0.7s ease-out ${delayMs}ms, transform 0.7s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  }
}

export function PlatformSection() {
  const { ref, inView } = useScrollReveal()

  return (
    <section
      ref={ref}
      // Anchor target for the nav's "Platforms" item (/#platform).
      id="platform"
      className="relative scroll-mt-24 py-20 lg:py-28 overflow-hidden bg-gradient-to-b from-[#060d18] via-[#0a1628] to-[#060d18]"
    >
      <div className="absolute inset-0 pointer-events-none opacity-35 bg-[radial-gradient(ellipse_at_10%_50%,rgba(34,211,238,0.12),transparent_45%),radial-gradient(ellipse_at_90%_40%,rgba(99,102,241,0.12),transparent_40%)]" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div>
            <p
              className="text-sm font-semibold uppercase tracking-wider mb-3 text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-400 motion-reduce:!opacity-100"
              style={revealLeft(inView, 0)}
            >
              Platform
            </p>

            <h2
              className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-6 text-balance leading-tight motion-reduce:!opacity-100"
              style={revealLeft(inView, 80)}
            >
              <span className="text-white">Advanced </span>
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-blue-400 to-violet-400 animate-gradient-text">
                STOCKEX
              </span>
              <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-200 via-sky-300 to-cyan-300">
                Trading Platform
              </span>
            </h2>

            <p
              className="text-lg text-gray-400 mb-8 motion-reduce:!opacity-100"
              style={revealLeft(inView, 160)}
            >
              Experience powerful trading technology designed for Indian markets with{" "}
              <span className="text-cyan-300/90 font-medium">real-time data</span> and{" "}
              <span className="text-violet-300/90 font-medium">seamless execution</span>.
            </p>

            <ul className="space-y-4 mb-8">
              {features.map((feature, index) => (
                <li
                  key={feature.text}
                  className="flex items-center gap-3 motion-reduce:!opacity-100"
                  style={revealLeft(inView, 240 + index * 70)}
                >
                  <div
                    className={`w-7 h-7 rounded-full bg-gradient-to-br ${feature.color} flex items-center justify-center flex-shrink-0 shadow-lg`}
                  >
                    <Check className="w-4 h-4 text-white" />
                  </div>
                  <span className="text-gray-200 font-medium group-hover:text-white transition-colors">
                    {feature.text}
                  </span>
                </li>
              ))}
            </ul>

            <div
              className="flex flex-wrap gap-4 mb-8 motion-reduce:!opacity-100"
              style={revealLeft(inView, 520)}
            >
              {platforms.map((platform) => (
                <div
                  key={platform.name}
                  className={`flex items-center gap-3 rounded-xl px-4 py-3 border transition-all duration-300 hover:-translate-y-1 hover:shadow-lg ${platform.cardClass}`}
                >
                  <platform.icon className={`w-5 h-5 ${platform.iconClass}`} />
                  <div>
                    <div className="text-sm font-semibold text-white">{platform.name}</div>
                    <div className="text-xs text-gray-400">{platform.desc}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="motion-reduce:!opacity-100" style={revealLeft(inView, 600)}>
              <Button
                asChild
                size="lg"
                // Was a cyan→blue→violet gradient. The hue-collapse layer
                // flattens those Tailwind fills to a white/8% wash, so on
                // this dark band the section's primary CTA rendered as a
                // barely-visible chip. A solid accent fill can't be
                // collapsed, and it is the same button the rest of the site
                // uses. Lighter step, because it sits on ink.
                className="bg-[#4D94E6] hover:bg-[#6DA8F0] text-[#0E100E] px-8 hover:-translate-y-0.5 transition-all duration-300"
              >
                <Link href="/login">Access Platform</Link>
              </Button>
            </div>
          </div>

          <div
            className="relative motion-reduce:!opacity-100"
            style={{
              opacity: inView ? 1 : 0,
              transform: inView ? "translateX(0) scale(1)" : "translateX(2.5rem) scale(0.97)",
              transition: "opacity 0.8s ease-out 200ms, transform 0.8s cubic-bezier(0.22, 1, 0.36, 1) 200ms",
            }}
          >
            <div className="rounded-3xl shadow-2xl shadow-blue-500/10 overflow-hidden border border-white/10 ring-1 ring-cyan-500/20">
              <img
                src="/images/indices-1.jpg"
                alt="STOCKEX Trading Platform"
                className="w-full object-cover object-bottom"
                style={{ marginTop: "-60px" }}
              />
            </div>

            <div className="absolute -bottom-4 -left-4 bg-slate-900/95 backdrop-blur-sm rounded-2xl shadow-xl px-4 py-3 flex items-center gap-3 border border-cyan-500/30">
              <div className="w-10 h-10 bg-gradient-to-br from-amber-400 to-yellow-500 rounded-full flex items-center justify-center shadow-lg shadow-amber-500/30">
                <span className="text-slate-900 font-bold text-sm">SX</span>
              </div>
              <div>
                <div className="text-sm font-semibold text-white">STOCKEX</div>
                <div className="text-xs text-gray-400">Web • Mobile • Desktop</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
