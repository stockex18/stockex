
import { Button } from "@/components/landing/ui/button"
import Link from 'next/link';
import { ArrowRight } from "lucide-react"


export function CTABar({ title, description, ctaText = "Open Account" }) {
  return (
    <section className="py-16 lg:py-20 bg-primary">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col lg:flex-row items-center justify-between gap-6">
          <div className="text-center lg:text-left">
            <h2 className="text-2xl lg:text-3xl font-bold text-white mb-2">{title}</h2>
            {description && (
              <p className="text-white/80">{description}</p>
            )}
          </div>
          <Button
            asChild
            size="lg"
            className="bg-white text-primary hover:bg-white/90 px-8 py-6 text-base font-semibold"
          >
            <Link href="/register">
              {ctaText}
              <ArrowRight className="w-5 h-5 ml-2" />
            </Link>
          </Button>
        </div>
      </div>
    </section>
  )
}
