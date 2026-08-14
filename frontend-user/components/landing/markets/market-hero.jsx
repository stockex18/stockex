
import { Button } from "@/components/landing/ui/button"
import Link from 'next/link';
import { ArrowRight, Download } from "lucide-react"


export function MarketHero({
  headline,
  subhead,
  ctaPrimary = "Open Account",
  ctaSecondary = "Download Platform",
  ctaSecondaryHref = "/platforms",
}) {
  return (
    <section className="relative pt-24 lg:pt-32 pb-16 lg:pb-20 overflow-hidden">
      {/* Background Image */}
      <img src="/images/bg-hero-fintech.jpg"
        alt=""
        
        className="object-cover" />
      {/* Dark Overlay */}
      <div className="absolute inset-0 bg-gradient-to-br from-black/80 via-black/70 to-black/60" />

      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-white leading-tight mb-6 text-balance">
            {headline}
          </h1>
          <p className="text-lg text-white/80 mb-8 leading-relaxed text-pretty">
            {subhead}
          </p>
          <div className="flex flex-col sm:flex-row gap-4">
            <Button asChild size="lg" className="bg-primary hover:bg-primary/90 text-white px-8 py-6 text-base font-semibold">
              <Link href="/register">
                {ctaPrimary}
                <ArrowRight className="w-5 h-5 ml-2" />
              </Link>
            </Button>
            {/* Was a bare <Button> — no Link, no onClick, so clicking it did
                nothing at all. Points at the platforms hub, which is where
                someone after "the platform" actually needs to land. */}
            <Button asChild size="lg" className="bg-white hover:bg-white/90 text-deep-blue px-8 py-6 text-base font-semibold">
              <Link href={ctaSecondaryHref}>
                <Download className="w-5 h-5 mr-2" />
                {ctaSecondary}
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}
