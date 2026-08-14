import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/landing/ui/button';
import { Sparkles, Flame, ArrowRight, CheckCircle2 } from 'lucide-react';
import Link from 'next/link';
import { joinStockexSections } from '@/data/joinStockexAccounts';

function useScrollReveal(threshold = 0.12) {
  const ref = useRef(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold, rootMargin: '0px 0px -40px 0px' }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  return { ref, inView };
}

function revealFromTop(inView, delayMs = 0) {
  return {
    opacity: inView ? 1 : 0,
    transform: inView ? 'translateY(0) scale(1)' : 'translateY(-2.5rem) scale(0.97)',
    transition: `opacity 0.75s ease-out ${delayMs}ms, transform 0.75s cubic-bezier(0.22, 1, 0.36, 1) ${delayMs}ms`,
  };
}

// `/accounts/<slug>` was never built as a route — and it can't be, because
// the dashboard already owns `/accounts` (app/(dashboard)/accounts) and a
// second route at that path is a build-time collision in Next. Every one
// of these cards was a 404. Map each account to the marketing page that
// actually covers it instead.
const ACCOUNT_DETAIL_URL = {
  'stockex-trading': '/standard',
  'stockex-brokerage': '/ib-management',
  'stockex-casino': '/nifty-games',
};

const detailHref = (slug) => ACCOUNT_DETAIL_URL[slug] ?? '/account-types';

function AccountCard({ account }) {
  const Icon = account.icon;
  const detailUrl = detailHref(account.slug);

  // Flat white card, hairline border, one ink icon tile. The "featured"
  // and "casino" cards keep their badges — the hierarchy signal is real —
  // but express it with the ink/lime pair instead of the old fuchsia →
  // purple → pink ramp, glow ring and pulsing sparkle.
  return (
    <Link
      href={detailUrl}
      className={`group relative flex flex-col bg-white rounded-2xl p-8 border transition-all duration-300 hover:-translate-y-1 cursor-pointer ${account.cardStyle}`}
    >
      {account.featured && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <span className="bg-[#C6F642] text-[#101210] text-[10px] font-bold tracking-[0.1em] px-3.5 py-1.5 rounded-full">
            POPULAR
          </span>
        </div>
      )}

      {account.casino && (
        <div className="absolute -top-3 right-5">
          <span className="inline-flex items-center gap-1 bg-[#141614] text-white text-[10px] font-bold tracking-[0.1em] px-3 py-1.5 rounded-full">
            <Flame className="w-3 h-3" /> HOT
          </span>
        </div>
      )}

      <div className="relative w-14 h-14 rounded-2xl flex items-center justify-center mb-6 bg-[#141614]">
        <Icon className="w-7 h-7 text-[#C6F642]" />
      </div>

      <h3 className="relative text-xl font-bold mb-2.5 text-[#0E100E]">{account.title}</h3>
      <p className="relative text-[15px] leading-relaxed text-[#606862] mb-7">
        {account.description}
      </p>

      <div className="relative space-y-3 mb-8">
        {account.features.map((feature, idx) => (
          <div key={idx} className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 bg-[#F0F3F0]">
              <feature.icon className="w-3.5 h-3.5 text-[#0E100E]" />
            </div>
            <span className="text-sm text-[#3A403C]">{feature.text}</span>
          </div>
        ))}
      </div>

      {/* Span, not <button> — see the note on the other card: the card is
          the link, this is only its label. */}
      <Button
        asChild
        className={`mt-auto w-full py-6 font-semibold rounded-full pointer-events-none ${account.buttonStyle}`}
      >
        <span aria-hidden="true">
          {account.buttonText}
          <ArrowRight className="w-4 h-4 ml-2 opacity-70" />
        </span>
      </Button>
    </Link>
  );
}

function BrokerBenefitCard({ account }) {
  const Icon = account.icon;
  const detailUrl = detailHref(account.slug);

  // The one genuinely dark card on the page. It used to paint itself with
  // a navy gradient plus two blurred cyan/blue orbs and a radial wash, and
  // then set NAVY text on top of it — the headings were already near-
  // invisible before the restyle. It is now a flat ink surface with an
  // explicitly light type ramp, so contrast is a property of the markup
  // rather than something the cascade has to rescue.
  return (
    <Link
      href={detailUrl}
      className={`group relative block rounded-2xl bg-[#101210] border transition-colors duration-300 cursor-pointer overflow-hidden ${account.cardStyle}`}
    >
      <div className="relative p-8 lg:p-12">
        <div className="flex flex-col lg:flex-row lg:items-start gap-10">
          <div className="lg:max-w-sm shrink-0">
            <div className="w-14 h-14 rounded-2xl bg-[#C6F642] flex items-center justify-center mb-6">
              <Icon className="w-7 h-7 text-[#101210]" />
            </div>
            <h3 className="text-2xl lg:text-3xl font-bold text-white mb-3">{account.title}</h3>
            <p className="text-[15px] leading-relaxed text-white/55">{account.description}</p>
          </div>

          <div className="flex-1 grid sm:grid-cols-2 gap-10">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/40 mb-5">
                What you get
              </p>
              <div className="space-y-3.5">
                {account.features.map((feature, idx) => (
                  <div key={idx} className="flex items-start gap-3">
                    <div className="w-7 h-7 rounded-lg bg-white/[0.07] flex items-center justify-center shrink-0 mt-px">
                      <feature.icon className="w-3.5 h-3.5 text-[#C6F642]" />
                    </div>
                    <span className="text-sm text-white/80 leading-snug">{feature.text}</span>
                  </div>
                ))}
              </div>
            </div>

            {account.benefitSources?.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/40 mb-5">
                  Where it comes from
                </p>
                <div className="space-y-2.5">
                  {account.benefitSources.map((src, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3"
                    >
                      <div className="text-[13px] font-semibold text-white">{src.label}</div>
                      <div className="text-xs text-white/50 mt-1 leading-relaxed">{src.detail}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Rendered as a SPAN, not a <button>. The whole card is already an
            <a>, and a real button inside it is interactive content nested in
            a link — invalid HTML, a hydration-mismatch risk, and Chrome
            treats the button as the click target so the card's own link
            stops firing. `asChild` keeps the button styling on a span that
            can't swallow the click. */}
        <Button
          asChild
          className={`mt-10 w-full sm:w-auto px-8 py-6 font-semibold rounded-full pointer-events-none ${account.buttonStyle}`}
        >
          <span aria-hidden="true">
            {account.buttonText}
            <ArrowRight className="w-4 h-4 ml-2 opacity-70" />
          </span>
        </Button>
      </div>
    </Link>
  );
}

function ReferralBanner({ highlight }) {
  const Icon = highlight.icon;

  return (
    // Was a dark emerald/teal wash carrying light text — which put white
    // type on a near-white panel once the greens were pulled out. Rebuilt
    // as a plain light panel with ink text, so it reads on the off-white
    // band it actually sits on.
    <div className="mt-8 rounded-2xl border border-[#E0E5E0] bg-white p-6 sm:p-8">
      <div className="flex flex-col sm:flex-row sm:items-start gap-5">
        <div className="w-12 h-12 rounded-xl bg-[#C6F642] flex items-center justify-center shrink-0">
          <Icon className="w-6 h-6 text-[#101210]" />
        </div>
        <div className="flex-1">
          <h4 className="text-lg font-bold text-[#0E100E] mb-4">{highlight.title}</h4>
          <ul className="grid sm:grid-cols-2 gap-2.5">
            {highlight.points.map((point, idx) => (
              <li key={idx} className="flex items-start gap-2.5 text-sm text-[#3A403C]">
                <CheckCircle2 className="w-4 h-4 text-[#0E100E] shrink-0 mt-0.5" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function JoinSection({ section, isFirst }) {
  const { ref, inView } = useScrollReveal();

  return (
    <div
      ref={ref}
      className={isFirst ? '' : 'pt-16 lg:pt-20 border-t border-border/60'}
    >
      <div
        className="text-center mb-10 motion-reduce:!opacity-100 motion-reduce:!translate-y-0"
        style={revealFromTop(inView, 0)}
      >
        <p className="text-sm font-semibold text-primary uppercase tracking-wider mb-2">
          {section.eyebrow}
        </p>
        <h3 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-deep-blue mb-3 text-balance">
          {section.title}
        </h3>
        <p className="text-base sm:text-lg text-muted-foreground max-w-3xl mx-auto">
          {section.subtitle}
        </p>
      </div>

      {section.layout === 'broker' ? (
        section.accounts.map((account, index) => (
          <div
            key={account.id}
            className="motion-reduce:!opacity-100 motion-reduce:!translate-y-0"
            style={revealFromTop(inView, 120 + index * 100)}
          >
            <BrokerBenefitCard account={account} />
          </div>
        ))
      ) : (
        <>
          <div className="grid md:grid-cols-2 gap-8">
            {section.accounts.map((account, index) => (
              <div
                key={account.id}
                className="motion-reduce:!opacity-100 motion-reduce:!translate-y-0"
                style={revealFromTop(inView, 120 + index * 120)}
              >
                <AccountCard account={account} />
              </div>
            ))}
          </div>
          {section.referralHighlight && (
            <div
              className="motion-reduce:!opacity-100 motion-reduce:!translate-y-0"
              style={revealFromTop(inView, 360)}
            >
              <ReferralBanner highlight={section.referralHighlight} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function AccountsSection() {
  return (
    // Anchor target for the nav's "Accounts" item (/#accounts).
    <section id="accounts" className="scroll-mt-24 py-20 lg:py-28 bg-secondary/50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="space-y-4">
          {joinStockexSections.map((section, idx) => (
            <JoinSection key={section.id} section={section} isFirst={idx === 0} />
          ))}
        </div>
      </div>
    </section>
  );
}
