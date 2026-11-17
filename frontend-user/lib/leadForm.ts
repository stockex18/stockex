/**
 * The callback-request form's choices and checks, shared by the /start page
 * (components/start/LeadForm.tsx) and StockEx Buddy's form after its mobile
 * OTP (components/landing/FaqBot.tsx). A new question goes here once and the
 * server's lead_service gets the same values.
 */

export const digits = (s: string) => s.replace(/\D/g, "");

// Same choices, same values as the server's TradingExperience.
export const EXPERIENCE = [
  { value: "NEW", label: "New to trading" },
  { value: "UNDER_1Y", label: "Less than 1 year" },
  { value: "Y1_3", label: "1–3 years" },
  { value: "OVER_3Y", label: "More than 3 years" },
];
// Who the enquiry is for — added at the client's request so the team knows
// which account to talk about on the call. Same values as the server's EnquiryFor.
export const ENQUIRY_FOR = [
  { value: "ADMIN", label: "Admin" },
  { value: "BROKER", label: "Broker" },
  { value: "USER", label: "User" },
];
export const QUESTION_MAX = 500;
// A first check only; the server does the real validation.
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export interface LeadFieldValues {
  name: string;
  email: string;
  city: string;
  experience: string;
  enquiryFor: string;
  consent: boolean;
}

/** The first field the server would refuse, or null. Mobile is checked by
 *  each form itself (typed on /start, already verified in the chat). */
export function leadFieldProblem(v: LeadFieldValues): string | null {
  if (v.name.trim().length < 2) return "Please enter your full name.";
  if (!EMAIL_RE.test(v.email.trim())) return "Enter a valid email address.";
  if (v.city.trim().length < 2) return "Please enter your city.";
  if (!v.experience) return "Please choose your trading experience.";
  if (!v.enquiryFor) return "Please choose who the enquiry is for.";
  if (!v.consent) return "Please allow us to contact you.";
  return null;
}
