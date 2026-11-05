"use client";

/**
 * "StockEx Buddy" — the home page's help chat, with NO AI.
 *
 * A "Chat with us" pill under "▶ Watch intro" (see hero-section.jsx) opens a
 * chat panel. Every answer comes from the stored questions and answers in
 * lib/faqBot/answers.ts — there is no AI and no outside API, so it always
 * says exactly what we wrote:
 *  - tapping a question shows its stored answer;
 *  - a typed question is matched by keywords (lib/faqBot/match.ts) to the
 *    closest stored answer;
 *  - nothing matched → a reply pointing to the support team (/contact).
 * No login: it knows nothing about anyone's account.
 *
 * Mobile OTP: the panel first asks for a mobile number and a texted code
 * (OtpGate below → app/api/faq-bot/otp + /verify → FastAPI's
 * /api/v1/marketing-bot/otp + /verify). A correct code sets a signed,
 * httpOnly cookie (lib/faqBot/session.ts) that keeps the visitor verified
 * for an hour. Each code is a paid SMS.
 *
 * Topics: the four cards in the home page's support section call
 * openFaqBot(topic) (lib/faqBot/answers.ts). The panel opens with that
 * card's greeting and questions and starts a fresh conversation. Opened from
 * a card, the panel sits inside the section under the cards
 * (#stockex-buddy-dock) instead of floating, so it never covers them. Page
 * paths in answers (/demo, /faq, …) become links — only the ones listed in
 * BOT_PAGES.
 *
 * The pill copies WatchIntro's inline navbar surface so the landing
 * stylesheet's colour remap can't shift it. The panel is portalled to <body>
 * (outside the remap) and stops clicks / keys from bubbling to the hero,
 * which would otherwise start the metro sound on every tap and Enter.
 */

import { Fragment, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  Facebook,
  Instagram,
  MessageCircle,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { SOCIAL_LINKS } from "@/lib/faqBot/social";
import {
  BOT_PAGES,
  DOCK_ID,
  GENERAL_TOPIC,
  OPEN_EVENT,
  QAS,
  TOPICS,
  isTopicKey,
  qa,
  type QA,
  type TopicKey,
} from "@/lib/faqBot/answers";
import { GREETING_ANSWER, NO_MATCH_ANSWER, findAnswer, isGreeting } from "@/lib/faqBot/match";
import { cn } from "@/lib/utils";

const MAX_CHARS = 300;
// A short "typing…" pause before an answer, so it reads like a reply
// rather than text that was already on screen.
const REPLY_DELAY_MS = 450;

interface Msg {
  id: string;
  role: "user" | "bot";
  text: string;
}

let localId = 0;
function msg(role: Msg["role"], text: string): Msg {
  localId += 1;
  return { id: `m-${Date.now()}-${localId}`, role, text };
}

// https URLs, or exactly one of the BOT_PAGES paths (not part of a longer path).
const PAGE_PATHS = Object.keys(BOT_PAGES)
  .sort((a, b) => b.length - a.length) // longest first: /forgot-password before /…
  .map((p) => p.replace(/[-/]/g, (c) => "\\" + c))
  .join("|");
const LINK_RE = new RegExp(
  String.raw`(https?:\/\/[^\s<>()]+|(?<![\w/.])(?:` + PAGE_PATHS + String.raw`)(?![\w/-]))`,
  "g",
);

const SOCIAL_ICONS = { facebook: Facebook, instagram: Instagram } as const;

// Brand surfaces, matching the home navbar pill and the "Open Account" blue.
const PILL_STYLE = { backgroundColor: "rgba(10, 16, 32, 0.82)", borderColor: "rgba(255, 255, 255, 0.17)" };
const BLUE_GRADIENT = { backgroundImage: "linear-gradient(rgb(94, 123, 255), rgb(61, 73, 255))" };
// Panel surface, set inline: docked inside the home page's light support
// section, the landing stylesheet would otherwise repaint a class-based
// background light and the white text would vanish.
// (Its <p> lines set their colour inline for the same reason.)
const PANEL_STYLE = { backgroundColor: "rgba(10, 16, 32, 0.97)", borderColor: "rgba(255, 255, 255, 0.15)" };

const LINK_CLASS = "font-medium text-[#8AA0FF] underline underline-offset-2 hover:text-white";
const CHIP_CLASS =
  "rounded-lg border border-white/15 px-3 py-2 text-left text-sm hover:border-[#5E7BFF]/70 hover:bg-white/5 disabled:opacity-50";

/** Plain text with https URLs and known site paths turned into links. */
function Linkified({ text }: { text: string }) {
  const parts = text.split(LINK_RE);
  return (
    <>
      {parts.map((part, i) => {
        if (i % 2 === 0) return <Fragment key={i}>{part}</Fragment>;
        // Keep sentence punctuation outside the link.
        const trail = part.match(/[.,!?;:]+$/)?.[0] ?? "";
        const href = trail ? part.slice(0, -trail.length) : part;
        return (
          <Fragment key={i}>
            {href.startsWith("/") ? (
              <Link href={href} className={LINK_CLASS}>
                {href}
              </Link>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
                {href.replace(/^https?:\/\//, "")}
              </a>
            )}
            {trail}
          </Fragment>
        );
      })}
    </>
  );
}

/** Renders **bold** as <strong>, *italic* as plain text, and links as links. */
function RichText({ text }: { text: string }) {
  const clean = text.replace(/(^|[^*])\*(?!\*)([^*\n]+?)\*(?!\*)/g, "$1$2");
  const pieces = clean.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {pieces.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") && p.length > 4 ? (
          <strong key={i} className="font-semibold">
            <Linkified text={p.slice(2, -2)} />
          </strong>
        ) : (
          <Linkified key={i} text={p} />
        ),
      )}
    </>
  );
}

type Verified = "unknown" | "no" | "yes";

const FIELD_CLASS =
  "w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 text-sm text-white outline-none placeholder:text-white/40 focus:border-[#5E7BFF]/70";
const MUTED = { color: "rgba(255, 255, 255, 0.7)" };

/** Mobile number → texted code → verified. Lives inside the chat panel. */
function OtpGate({ onVerified }: { onVerified: (maskedMobile: string) => void }) {
  const [step, setStep] = useState<"mobile" | "code">("mobile");
  const [mobile, setMobile] = useState("");
  const [code, setCode] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  useEffect(() => {
    if (step === "code") codeRef.current?.focus({ preventScroll: true });
  }, [step]);

  async function post(url: string, body: object) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as {
      message?: string;
      mobile?: string;
      error?: { message?: string };
    } | null;
    return { ok: res.ok, data };
  }

  async function sendCode() {
    if (mobile.length !== 10 || working) return;
    setWorking(true);
    setErr(null);
    try {
      const { ok, data } = await post("/api/faq-bot/otp", { mobile });
      if (!ok) return setErr(data?.error?.message ?? "We couldn't send the code. Please try again.");
      setNote(data?.message ?? "Code sent.");
      setCode("");
      setStep("code");
      setCooldown(60);
    } catch {
      setErr("Network problem. Please try again.");
    } finally {
      setWorking(false);
    }
  }

  async function verify() {
    if (!/^\d{4}$/.test(code) || working) return;
    setWorking(true);
    setErr(null);
    try {
      const { ok, data } = await post("/api/faq-bot/verify", { mobile, otp: code });
      if (!ok || !data?.mobile) {
        return setErr(data?.error?.message ?? "That code didn't work. Please try again.");
      }
      onVerified(data.mobile);
    } catch {
      setErr("Network problem. Please try again.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col justify-center gap-4 overflow-y-auto px-5 py-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="grid size-11 place-items-center rounded-full text-white" style={BLUE_GRADIENT}>
          <ShieldCheck className="size-5" aria-hidden />
        </span>
        <p className="text-base font-semibold" style={{ color: "#fff" }}>
          Verify your mobile to start chatting
        </p>
        <p className="text-xs" style={MUTED}>
          {step === "mobile"
            ? "We'll text you a 4-digit code. It only confirms you're a real person."
            : `Enter the 4-digit code sent to +91 ••••••${mobile.slice(-4)}.`}
        </p>
      </div>

      {step === "mobile" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void sendCode();
          }}
          className="flex flex-col gap-3"
        >
          <div className="flex items-center gap-2">
            <span className="rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 text-sm" style={MUTED}>
              +91
            </span>
            <input
              value={mobile}
              onChange={(e) => setMobile(e.target.value.replace(/\D/g, "").slice(0, 10))}
              inputMode="numeric"
              autoComplete="tel-national"
              placeholder="10-digit mobile number"
              aria-label="Mobile number"
              className={FIELD_CLASS}
            />
          </div>
          <button
            type="submit"
            disabled={mobile.length !== 10 || working}
            style={BLUE_GRADIENT}
            className="h-10 rounded-lg text-sm font-semibold text-white disabled:opacity-40"
          >
            {working ? "Sending…" : "Send code"}
          </button>
        </form>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void verify();
          }}
          className="flex flex-col gap-3"
        >
          <input
            ref={codeRef}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 4))}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="4-digit code"
            aria-label="Verification code"
            className={cn(FIELD_CLASS, "text-center tracking-[0.5em] placeholder:tracking-normal")}
          />
          <button
            type="submit"
            disabled={code.length !== 4 || working}
            style={BLUE_GRADIENT}
            className="h-10 rounded-lg text-sm font-semibold text-white disabled:opacity-40"
          >
            {working ? "Checking…" : "Verify"}
          </button>
          <div className="flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={() => {
                setStep("mobile");
                setErr(null);
                setNote(null);
              }}
              className="text-[#8AA0FF] hover:text-white"
            >
              Change number
            </button>
            <button
              type="button"
              onClick={() => void sendCode()}
              disabled={cooldown > 0 || working}
              className="text-[#8AA0FF] hover:text-white disabled:text-white/40"
            >
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
            </button>
          </div>
        </form>
      )}

      {note && !err ? (
        <p className="text-center text-xs" style={MUTED}>
          {note}
        </p>
      ) : null}
      {err ? (
        <p
          role="alert"
          className="rounded-lg border border-[#ef4444]/40 bg-[#ef4444]/10 px-3 py-2 text-center text-xs text-[#fca5a5]"
        >
          {err}
        </p>
      ) : null}
    </div>
  );
}

export function FaqBot() {
  const [open, setOpen] = useState(false);
  // Set when a support card opened the chat: the panel renders inside this
  // element (under the cards) instead of floating over the page.
  const [dock, setDock] = useState<HTMLElement | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [typing, setTyping] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // Mobile OTP state: unknown until the panel first opens and asks the server.
  const [verified, setVerified] = useState<Verified>("unknown");
  const [verifiedMobile, setVerifiedMobile] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const replyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Which support card opened the chat (null = the hero pill / general).
  const [topic, setTopic] = useState<TopicKey | null>(null);
  const topicRef = useRef(topic);
  topicRef.current = topic;
  const intro = topic ? TOPICS[topic] : GENERAL_TOPIC;
  const starters = intro.starters.map(qa);

  const reset = () => {
    if (replyTimer.current) clearTimeout(replyTimer.current);
    setTyping(false);
    setMessages([]);
    setShowAll(false);
  };
  const resetRef = useRef(reset);
  resetRef.current = reset;

  // A support card asked to open the chat on its topic. A different topic
  // starts a fresh conversation; the same one just reopens it.
  useEffect(() => {
    const onOpen = (e: Event) => {
      const detail = (e as CustomEvent<{ topic?: unknown; dock?: boolean }>).detail;
      const next = detail?.topic;
      setDock(detail?.dock ? document.getElementById(DOCK_ID) : null);
      if (isTopicKey(next) && next !== topicRef.current) {
        resetRef.current();
        setTopic(next);
      }
      setOpen(true);
    };
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => () => {
    if (replyTimer.current) clearTimeout(replyTimer.current);
  }, []);

  // Ask the server once, when the panel first opens, whether this browser
  // already verified a number (the session cookie is httpOnly).
  useEffect(() => {
    if (!open || verified !== "unknown") return;
    let cancelled = false;
    fetch("/api/faq-bot/verify", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: { verified?: boolean; mobile?: string }) => {
        if (cancelled) return;
        setVerified(d?.verified ? "yes" : "no");
        setVerifiedMobile(d?.mobile ?? "");
      })
      .catch(() => {
        if (!cancelled) setVerified("no");
      });
    return () => {
      cancelled = true;
    };
  }, [open, verified]);

  const changeNumber = () => {
    reset();
    setVerified("no");
    setVerifiedMobile("");
    void fetch("/api/faq-bot/verify", { method: "DELETE" });
  };

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, typing]);

  useEffect(() => {
    if (!open) return;
    // preventScroll: focusing must not jump the page; the docked panel is
    // brought into view smoothly below instead.
    inputRef.current?.focus({ preventScroll: true });
    if (dock) {
      requestAnimationFrame(() => dock.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    }
  }, [open, dock]);

  /** Show the visitor's question, then the stored answer after a short pause. */
  const reply = (question: string, answer: string) => {
    if (typing) return;
    setShowAll(false);
    setMessages((prev) => [...prev, msg("user", question)]);
    setTyping(true);
    replyTimer.current = setTimeout(() => {
      setTyping(false);
      setMessages((prev) => [...prev, msg("bot", answer)]);
    }, REPLY_DELAY_MS);
  };

  /** A tapped question: its stored answer. */
  const ask = (item: QA) => reply(item.q, item.a);

  /** A typed question: the closest stored answer by keywords. */
  const send = (text: string) => {
    const t = text.trim();
    if (!t || typing) return;
    const { answer } = findAnswer(t);
    reply(t, answer ? answer.a : isGreeting(t) ? GREETING_ANSWER : NO_MATCH_ANSWER);
    setInput("");
  };

  const lastBotId = [...messages].reverse().find((m) => m.role === "bot")?.id;

  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          // The hero starts its metro sound on any click -- not this one.
          e.stopPropagation();
          // The hero pill always opens the floating panel.
          if (!open) setDock(null);
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        aria-label={open ? "Close StockEx chat" : "Chat with StockEx"}
        style={PILL_STYLE}
        className="flex h-11 shrink-0 items-center justify-start gap-2 rounded-full border pl-1.5 pr-4 text-[13px] font-semibold text-white shadow-lg backdrop-blur-xl transition-[filter] hover:brightness-125"
      >
        <span className="relative grid size-8 place-items-center rounded-full text-white" style={BLUE_GRADIENT}>
          {/* Online dot — colours inline: the landing stylesheet repaints
              class-based ones here and the dot showed as a dark ring. */}
          <span
            className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2"
            style={{ backgroundColor: "#10b981", borderColor: "#0a1020" }}
            aria-hidden
          />
          {/* Solid white, like the ▶ in "Watch intro", so both icons read equally bright. */}
          <MessageCircle className="size-4 fill-current" aria-hidden />
        </span>
        Chat with us
      </button>

      {open &&
        createPortal(
          <div
            role="dialog"
            aria-label="StockEx chat"
            // Portals still bubble through the React tree to the hero, which
            // would start its metro sound -- stop clicks and keys here.
            onClick={(e) => e.stopPropagation()}
            style={PANEL_STYLE}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Escape") setOpen(false);
            }}
            // Docked (opened from a support card): a block under the cards.
            // Floating — phones: a sheet near the bottom; desktop: just under
            // the hero pill, its right edge on the navbar's (max-w-7xl + px-4).
            className={cn(
              "flex flex-col overflow-hidden rounded-2xl border text-left text-white backdrop-blur-xl",
              dock
                ? "relative mx-auto h-[min(520px,75dvh)] w-full max-w-2xl scroll-mt-24 shadow-xl shadow-black/20"
                : "fixed inset-x-3 bottom-3 z-[90] h-[min(560px,calc(100dvh-6rem))] shadow-2xl shadow-black/60 md:inset-x-auto md:bottom-auto md:right-[max(1rem,calc((100vw-80rem)/2+1rem))] md:top-[13rem] md:h-[min(540px,calc(100dvh-14.5rem))] md:w-[380px]",
            )}
          >
            {/* Header */}
            <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2.5">
              <div className="grid size-8 place-items-center rounded-full text-white" style={BLUE_GRADIENT}>
                <Sparkles className="size-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">
                  StockEx Buddy{topic ? <span className="font-normal text-white/60"> · {TOPICS[topic].title}</span> : null}
                </div>
                <div className="truncate text-[11px] text-white/60">
                  {verified === "yes" && verifiedMobile ? (
                    <>
                      Verified {verifiedMobile} ·{" "}
                      <button type="button" onClick={changeNumber} className="underline hover:text-white">
                        change
                      </button>
                    </>
                  ) : (
                    "Quick answers · not investment advice"
                  )}
                </div>
              </div>
              {messages.length > 0 && (
                <button
                  type="button"
                  onClick={reset}
                  aria-label="Clear chat"
                  title="Clear chat"
                  className="grid size-8 place-items-center rounded-md text-white/60 hover:bg-white/10 hover:text-white"
                >
                  <Trash2 className="size-4" />
                </button>
              )}
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close chat"
                className="grid size-8 place-items-center rounded-md text-white/60 hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" />
              </button>
            </div>

            {verified !== "yes" ? (
              verified === "unknown" ? (
                <div className="flex flex-1 items-center justify-center text-xs" style={MUTED}>
                  Loading…
                </div>
              ) : (
                <OtpGate
                  onVerified={(m) => {
                    setVerifiedMobile(m);
                    setVerified("yes");
                  }}
                />
              )
            ) : (
            <>
            {/* Messages */}
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
              {messages.length === 0 && (
                <div className="space-y-3">
                  <p className="text-sm" style={{ color: "rgba(255, 255, 255, 0.8)" }}>
                    {intro.greeting}
                  </p>
                  <div className="flex flex-col gap-2">
                    {starters.map((item) => (
                      <button key={item.id} type="button" onClick={() => ask(item)} className={CHIP_CLASS}>
                        {item.q}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m) => {
                const mine = m.role === "user";
                return (
                  <div key={m.id} className="space-y-2">
                    <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
                      <div
                        className={cn(
                          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-sm leading-relaxed",
                          mine ? "rounded-br-sm text-white" : "rounded-bl-sm bg-white/10 text-white",
                        )}
                        style={mine ? BLUE_GRADIENT : undefined}
                      >
                        {mine ? m.text : <RichText text={m.text} />}
                      </div>
                    </div>
                    {/* A plain label under the latest answer; the "See all questions"
                        dropdown below holds the questions. */}
                    {m.id === lastBotId && !typing && (
                      <p className="pl-1 text-[11px]" style={{ color: "rgba(255, 255, 255, 0.5)" }}>
                        You might also ask
                      </p>
                    )}
                  </div>
                );
              })}

              {typing && (
                <div className="flex justify-start">
                  <div className="flex gap-1 rounded-2xl rounded-bl-sm bg-white/10 px-3 py-3">
                    {[0, 150, 300].map((d) => (
                      <span
                        key={d}
                        className="size-1.5 animate-bounce rounded-full bg-white/60"
                        style={{ animationDelay: `${d}ms` }}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Every stored question, one tap away. */}
              {!typing && (
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() => setShowAll((s) => !s)}
                    aria-expanded={showAll}
                    className="flex items-center gap-1 text-xs font-medium text-[#8AA0FF] hover:text-white"
                  >
                    <ChevronDown className={cn("size-3.5 transition-transform", showAll && "rotate-180")} aria-hidden />
                    {showAll ? "Hide all questions" : `See all ${QAS.length} questions`}
                  </button>
                  {showAll && (
                    <div className="mt-2 flex flex-col gap-1.5">
                      {QAS.map((item) => (
                        <button key={item.id} type="button" onClick={() => ask(item)} className={CHIP_CLASS}>
                          {item.q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Follow us */}
            {SOCIAL_LINKS.length > 0 && (
              <div className="flex items-center gap-2 border-t border-white/10 px-3 py-2">
                <span className="text-[11px] text-white/60">Follow StockEx</span>
                {SOCIAL_LINKS.map((s) => {
                  const Icon = SOCIAL_ICONS[s.key];
                  return (
                    <a
                      key={s.key}
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 rounded-full border border-white/15 px-2.5 py-1 text-xs font-medium hover:bg-white/10"
                    >
                      <Icon className="size-3.5" aria-hidden />
                      {s.label}
                    </a>
                  );
                })}
              </div>
            )}

            {/* Composer */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
              className="border-t border-white/10 p-2"
            >
              <div className="flex items-end gap-2">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value.slice(0, MAX_CHARS))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send(input);
                    }
                  }}
                  rows={1}
                  placeholder="Type your question…"
                  className="max-h-28 min-h-[40px] flex-1 resize-none rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-white/40 focus:border-[#5E7BFF]/70"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || typing}
                  aria-label="Send"
                  style={BLUE_GRADIENT}
                  className="grid size-10 shrink-0 place-items-center rounded-lg text-white disabled:opacity-40"
                >
                  <SendHorizontal className="size-4" />
                </button>
              </div>
              <p className="mt-1 px-1 text-[10px]" style={{ color: "rgba(255, 255, 255, 0.5)" }}>
                Don&apos;t share passwords, OTPs, PAN, Aadhaar or bank details.
              </p>
            </form>
            </>
            )}
          </div>,
          dock ?? document.body,
        )}
    </>
  );
}
