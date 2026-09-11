import type { Metadata } from "next";
import { ArrowRight, Download, Globe, LogIn, Monitor, Smartphone } from "lucide-react";
import {
  MpButton,
  MpCard,
  MpHeading,
  MpPageHero,
  MpSection,
} from "@/components/marketing/mp-ui";
import { ADMIN_URL } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Broker Login & Broker App | StockEx",
  description:
    "StockEx brokers: sign in on the website, or install the StockEx Broker app on your phone or computer.",
};

/**
 * Where a broker lands from the nav. Two ways to work, side by side:
 *
 *   website  sign straight in to the broker panel
 *   app      the same panel installed to the home screen
 *
 * Both open the broker's OWN login on the panel's domain (/broker/login),
 * never the admin login. The app is the broker PWA — installed separately
 * from the admin app, so both can sit on one phone. A PWA can only be
 * installed from its own origin, so "Download" sends the broker there with
 * `?install=1`, where the install button is waiting and highlighted.
 */
const LOGIN_URL = `${ADMIN_URL}/broker/login`;
const INSTALL_URL = `${ADMIN_URL}/broker/login?install=1`;

const WAYS = [
  {
    icon: Globe,
    title: "Use it on the website",
    body: "Nothing to install. Sign in from any browser and manage your clients, positions and payments straight away.",
    cta: "Broker Login",
    href: LOGIN_URL,
    primary: false,
  },
  {
    icon: Smartphone,
    title: "Install the Broker app",
    body: "The same panel on your home screen — opens full-screen like a native app and keeps you signed in.",
    cta: "Download Broker App",
    href: INSTALL_URL,
    primary: true,
  },
];

const STEPS = [
  {
    icon: Smartphone,
    title: "Android",
    body: "Open Download Broker App in Chrome and tap Install. If no prompt appears, use ⋮ menu → Install app.",
  },
  {
    icon: Smartphone,
    title: "iPhone",
    body: "Open it in Safari, tap the Share icon, then Add to Home Screen.",
  },
  {
    icon: Monitor,
    title: "Computer",
    body: "In Chrome or Edge, click the install icon at the right end of the address bar.",
  },
];

export default function BrokerPage() {
  return (
    <>
      <MpPageHero
        eyebrow="For Brokers"
        title="Run your book from the web or the app"
        lead="Sign in on the website, or install the StockEx Broker app on your phone or computer. Same account, same panel — pick whichever suits you."
        media={
          <div className="grid place-items-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/icons/broker-app-256.png"
              alt="StockEx Broker app icon"
              width={256}
              height={256}
              className="size-64 drop-shadow-2xl"
            />
          </div>
        }
      >
        <MpButton href={LOGIN_URL} size="lg">
          <LogIn className="size-4" />
          Broker Login
        </MpButton>
        <MpButton href={INSTALL_URL} variant="secondary" size="lg">
          <Download className="size-4" />
          Download Broker App
        </MpButton>
      </MpPageHero>

      {/* Two ways to work */}
      <MpSection light>
        <div id="app" className="scroll-mt-28">
          <MpHeading align="center" eyebrow="Two ways" title="Website or app — your choice" />
          <div className="mx-auto mt-12 grid max-w-4xl gap-5 md:grid-cols-2">
            {WAYS.map((w) => (
              <MpCard
                key={w.title}
                className={
                  "flex flex-col gap-4 " + (w.primary ? "ring-2 ring-mp-primary/40" : "")
                }
              >
                <div className="flex items-center gap-3">
                  {w.primary ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src="/icons/broker-app-256.png"
                      alt=""
                      width={48}
                      height={48}
                      className="size-12"
                    />
                  ) : (
                    <span className="grid size-12 place-items-center rounded-2xl bg-mp-primary/10 text-mp-primary">
                      <w.icon className="size-6" />
                    </span>
                  )}
                  <h3 className="font-display text-lg font-semibold text-mp-text">{w.title}</h3>
                </div>
                <p className="flex-1 text-sm leading-[1.6] text-mp-text-mut">{w.body}</p>
                <MpButton href={w.href} variant={w.primary ? "primary" : "secondary"}>
                  {w.cta}
                  <ArrowRight className="size-4" />
                </MpButton>
              </MpCard>
            ))}
          </div>
        </div>
      </MpSection>

      {/* How to install */}
      <MpSection>
        <MpHeading align="center" eyebrow="Install" title="Installing the Broker app" />
        <div className="mt-12 grid gap-5 sm:grid-cols-3">
          {STEPS.map((s) => (
            <MpCard key={s.title} className="flex flex-col gap-4">
              <span className="grid size-12 place-items-center rounded-2xl bg-mp-primary/10 text-mp-primary">
                <s.icon className="size-6" />
              </span>
              <h3 className="font-display text-lg font-semibold text-mp-text">{s.title}</h3>
              <p className="text-sm leading-[1.6] text-mp-text-mut">{s.body}</p>
            </MpCard>
          ))}
        </div>
        <p className="mx-auto mt-8 max-w-2xl text-center text-xs leading-relaxed text-mp-text-mut">
          Opened this from WhatsApp or another app? Open it in Chrome or Safari first — built-in
          app browsers can&apos;t install web apps.
        </p>
      </MpSection>
    </>
  );
}
