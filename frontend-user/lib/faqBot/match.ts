/**
 * StockEx Buddy (no-AI) — finds the stored answer for a typed question.
 *
 * Each entry in lib/faqBot/answers.ts lists keywords. The typed text is
 * lower-cased and stripped of punctuation; a single-word keyword must match
 * a whole word (a trailing "s" is allowed), a phrase may appear anywhere.
 * Longer keywords are more specific, so each hit scores its own length and
 * the highest total wins. No hit at all → a short "I don't know that one"
 * reply with links to /faq and /contact.
 */

import { QAS, type QA } from "./answers";

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[’`]/g, "'")
    .replace(/[^a-z0-9&'\- ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const PREPARED = QAS.map((entry) => ({
  entry,
  question: normalize(entry.q),
  keywords: entry.keywords.map(normalize).filter(Boolean),
}));

function score(text: string, words: Set<string>, keywords: string[]): number {
  let total = 0;
  for (const kw of keywords) {
    const hit = kw.includes(" ")
      ? ` ${text} `.includes(` ${kw} `) || text.includes(kw)
      : words.has(kw) || words.has(`${kw}s`) || words.has(`${kw}es`);
    if (hit) total += kw.length;
  }
  return total;
}

export interface MatchResult {
  /** The best answer, or null when nothing matched. */
  answer: QA | null;
  /** Up to `limit` other close matches, to offer as follow-up questions. */
  related: QA[];
}

export function findAnswer(text: string, limit = 3): MatchResult {
  const t = normalize(text);
  if (!t) return { answer: null, related: [] };

  // Exact question text (e.g. pasted from the list) wins outright.
  const exact = PREPARED.find((p) => p.question === t);
  if (exact) return { answer: exact.entry, related: [] };

  const words = new Set(t.split(" "));
  const ranked = PREPARED.map((p) => ({ entry: p.entry, s: score(t, words, p.keywords) }))
    .filter((r) => r.s > 0)
    .sort((a, b) => b.s - a.s); // stable: ties keep the order of answers.ts

  return {
    answer: ranked[0]?.entry ?? null,
    related: ranked.slice(1, 1 + limit).map((r) => r.entry),
  };
}

const GREETING_RE = /^(hi+|hello+|hey+|hii+|namaste|namaskar|good (morning|afternoon|evening)|hola|yo)\b/;

/** "hi", "hello sir", "namaste" … — answered with a greeting, not "sorry". */
export function isGreeting(text: string): boolean {
  const t = normalize(text);
  return GREETING_RE.test(t) && t.split(" ").length <= 4;
}

export const GREETING_ANSWER = "Hello! 👋 How can I help you today? Pick a question below or type your own.";

export const NO_MATCH_ANSWER =
  "Sorry, I don't have an answer for that yet. Try one of the questions below, browse /faq, or ask our team at /contact.";
