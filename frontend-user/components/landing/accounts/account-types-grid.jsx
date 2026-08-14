
import { Button } from "@/components/landing/ui/button"
import Link from 'next/link';
import { Check, Star, Zap, Target, TrendingUp } from "lucide-react"

const accountTypes = [
  {
    name: "Standard Account",
    badge: "Beginner-Friendly",
    icon: Star,
    color: "bg-blue-500",
    features: [
      { label: "Minimum Deposit", value: "$100" },
      { label: "Platform", value: "MT5" },
      { label: "Commission", value: "$0" },
      { label: "Spread (Major FX)", value: "2.2 � 2.5 pips" },
      { label: "Leverage", value: "Up to 1:1000*" },
      { label: "Support", value: "24/5" },
    ],
    description: "Best for new traders looking for simplicity and zero commission.",
    highlighted: false,
  },
  {
    name: "Pro Account",
    badge: "Most Popular",
    icon: TrendingUp,
    color: "bg-primary",
    features: [
      { label: "Minimum Deposit", value: "$500" },
      { label: "Platform", value: "MT5" },
      { label: "Commission", value: "Low" },
      { label: "Spread (Major FX)", value: "1.0 � 1.5 pips" },
      { label: "Leverage", value: "Up to 1:1000*" },
      { label: "Support", value: "24/5 Priority" },
    ],
    description: "Designed for consistent and disciplined traders with advanced features.",
    highlighted: true,
  },
  {
    name: "RAW Account",
    badge: "True Market Access",
    icon: Zap,
    color: "bg-orange-500",
    features: [
      { label: "Minimum Deposit", value: "$1,000" },
      { label: "Platform", value: "MT5" },
      { label: "Commission", value: "Yes" },
      { label: "Spread (Major FX)", value: "From 0.0 pips" },
      { label: "Leverage", value: "Up to 1:1000*" },
      { label: "Support", value: "24/5 Priority" },
    ],
    description: "Ideal for scalpers & algorithmic strategies with raw spreads.",
    highlighted: false,
  },
  {
    name: "Zero Spread",
    badge: "Institutional-Grade",
    icon: Target,
    color: "bg-purple-500",
    features: [
      { label: "Minimum Deposit", value: "$1,000" },
      { label: "Platform", value: "MT5" },
      { label: "Commission", value: "Fixed" },
      { label: "Spread (Major FX)", value: "Zero" },
      { label: "Leverage", value: "Up to 1:1000*" },
      { label: "Support", value: "24/5 VIP" },
    ],
    description: "Designed for high-volume traders with zero markup pricing.",
    highlighted: false,
  },
]

export function AccountTypesGrid() {
  return (
    <section className="py-16 lg:py-24 bg-background">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl lg:text-4xl font-bold text-foreground mb-4">
            Find the Trading Account That&apos;s Right for You
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Compare our account types and choose the one that best fits your trading style and experience level.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
          {accountTypes.map((account, index) => (
            <div
              key={index}
              className={`relative bg-white border rounded-2xl p-6 transition-all duration-300 hover:shadow-xl hover:-translate-y-1 ${
                account.highlighted 
                  ? "border-primary shadow-lg ring-2 ring-primary/20" 
                  : "border-border hover:border-primary/30"
              }`}
            >
              {account.highlighted && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-white text-xs font-semibold px-3 py-1 rounded-full">
                  Most Popular
                </div>
              )}

              <div className={`w-12 h-12 ${account.color} rounded-xl flex items-center justify-center mb-4`}>
                <account.icon className="w-6 h-6 text-white" />
              </div>

              <h3 className="text-xl font-bold text-foreground mb-1">{account.name}</h3>
              <p className="text-sm text-primary font-medium mb-4">{account.badge}</p>

              <ul className="space-y-3 mb-6">
                {account.features.map((feature, featureIndex) => (
                  <li key={featureIndex} className="flex justify-between text-sm">
                    <span className="text-muted-foreground">{feature.label}</span>
                    <span className="font-medium text-foreground">{feature.value}</span>
                  </li>
                ))}
              </ul>

              <p className="text-sm text-muted-foreground mb-6">{account.description}</p>

              {/* `/login?register=true` was a dead param — the login page
                  never reads it, so "Open Account" landed people on a
                  sign-IN form. Signup lives at /register. */}
              <Button
                asChild
                className={`w-full ${account.highlighted ? "bg-primary hover:bg-primary/90 text-white" : ""}`}
                variant={account.highlighted ? "default" : "outline"}
              >
                <Link href="/register">Open Account</Link>
              </Button>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

