import { Button } from "@/components/landing/ui/button"
import { Wallet, Activity, Shield, Monitor, TrendingUp, BarChart3 } from "lucide-react"
import Link from 'next/link';

const features = [
  // 10 lakh — matches `_DEMO_FUND` in backend/app/services/demo_service.py.
  { icon: Wallet, text: "10,00,000 virtual balance" },
  { icon: Activity, text: "Real-time market simulation" },
  { icon: Shield, text: "Risk-free practice" },
  { icon: Monitor, text: "Full platform access" },
]

export function DemoTradingSection() {
  return (
    <section className="py-20 lg:py-28 gradient-blue">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Left Content */}
          <div className="text-center lg:text-left">
            <p className="text-sm font-semibold text-yellow-accent uppercase tracking-wider mb-3">Demo Account</p>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-white mb-6 text-balance">
              Practice Trading with a Demo Account
            </h2>
            <p className="text-lg text-white/80 mb-8">
              Start learning trading with virtual money and real market simulation. Perfect your strategies without risking real capital.
            </p>

            {/* Features */}
            <div className="grid grid-cols-2 gap-4 mb-8">
              {features.map((feature, index) => (
                <div key={index} className="flex items-center gap-3 bg-white/10 rounded-xl p-4">
                  <div className="w-10 h-10 bg-yellow-accent/20 rounded-lg flex items-center justify-center">
                    <feature.icon className="w-5 h-5 text-yellow-accent" />
                  </div>
                  <span className="text-white text-sm font-medium">{feature.text}</span>
                </div>
              ))}
            </div>

            {/* Demo signup lives on the REGISTER page (`?demo=1`), which
                creates a personal demo account and logs in. The old
                `/login?demo=true` was a no-op — the login page never read
                that param, so this button just dropped you on a plain
                login form. */}
            {/* `asChild` so this renders ONE <a>, not a <button> inside an
                <a> — the nested form makes the button the activation target
                and the link never fires. */}
            <Button asChild size="lg" className="bg-yellow-accent hover:bg-yellow-500 text-deep-blue font-semibold px-8 py-6 text-lg">
              <Link href="/register?demo=1">Open Demo Account</Link>
            </Button>
          </div>

          {/* Right - Dashboard Preview */}
          <div className="hidden lg:block">
            <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-6 border border-white/20">
              {/* Dashboard Header */}
              <div className="flex items-center justify-between mb-6">
                <div>
                  <p className="text-white/60 text-sm">Demo Account Balance</p>
                  <p className="text-3xl font-bold text-white">10,00,000.00</p>
                </div>
                <div className="text-right">
                  <p className="text-white/60 text-sm">Today's P&L</p>
                  <p className="text-xl font-bold text-profit-green">+2,450.00</p>
                </div>
              </div>

              {/* Portfolio Summary */}
              <div className="grid grid-cols-3 gap-4 mb-6">
                <div className="bg-white/5 rounded-xl p-4 text-center">
                  <p className="text-white/60 text-xs mb-1">Open Positions</p>
                  <p className="text-white font-bold text-lg">5</p>
                </div>
                <div className="bg-white/5 rounded-xl p-4 text-center">
                  <p className="text-white/60 text-xs mb-1">Total Trades</p>
                  <p className="text-white font-bold text-lg">24</p>
                </div>
                <div className="bg-white/5 rounded-xl p-4 text-center">
                  <p className="text-white/60 text-xs mb-1">Win Rate</p>
                  <p className="text-profit-green font-bold text-lg">68%</p>
                </div>
              </div>

              {/* Sample Positions */}
              <div className="space-y-3">
                {[
                  { name: "RELIANCE", qty: 10, pnl: "+850", up: true },
                  { name: "NIFTY 50 FUT", qty: 1, pnl: "+1,200", up: true },
                  { name: "GOLD", qty: 5, pnl: "-320", up: false },
                ].map((position, index) => (
                  <div key={index} className="flex items-center justify-between bg-white/5 rounded-xl p-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center">
                        <BarChart3 className="w-4 h-4 text-white" />
                      </div>
                      <div>
                        <p className="text-white font-medium text-sm">{position.name}</p>
                        <p className="text-white/60 text-xs">Qty: {position.qty}</p>
                      </div>
                    </div>
                    <div className={`flex items-center gap-1 ${position.up ? "text-profit-green" : "text-loss-red"}`}>
                      <TrendingUp className={`w-4 h-4 ${!position.up && "rotate-180"}`} />
                      <span className="font-semibold">{position.pnl}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
