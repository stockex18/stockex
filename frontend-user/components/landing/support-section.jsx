import { Headphones, HelpCircle, BookOpen, MessageCircle } from "lucide-react"
import { TalkToTeamDialog } from "@/components/landing/auth-dialogs"

const supportFeatures = [
  {
    icon: Headphones,
    title: "Help Center",
    description: "Browse our comprehensive help articles",
  },
  {
    icon: HelpCircle,
    title: "FAQs",
    description: "Find answers to common questions",
  },
  {
    icon: BookOpen,
    title: "Trading Guides",
    description: "Learn trading strategies and tips",
  },
  {
    icon: MessageCircle,
    title: "24/7 Support",
    description: "Chat with our support team any time, day or night",
  },
]

export function SupportSection() {
  return (
    <section className="theme-light py-20 lg:py-28 bg-secondary/50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="text-center mb-16">
          <p className="text-sm font-semibold text-primary uppercase tracking-wider mb-3">Support</p>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-deep-blue mb-4">
            24/7 Customer Support
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            We're here to help you succeed. Get support whenever you need it.
          </p>
        </div>

        {/* Support Features */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
          {supportFeatures.map((feature, index) => (
            <TalkToTeamDialog
              key={index}
              trigger={
                <div className="bg-white rounded-2xl p-6 text-center hover:shadow-lg transition-all duration-300 border border-border cursor-pointer">
                  <div className="w-14 h-14 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-4">
                    <feature.icon className="w-7 h-7 text-primary" />
                  </div>
                  <h3 className="text-lg font-bold text-deep-blue mb-2">{feature.title}</h3>
                  <p className="text-sm text-muted-foreground">{feature.description}</p>
                </div>
              }
            />
          ))}
        </div>
      </div>
    </section>
  )
}
