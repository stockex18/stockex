import { useState, useMemo } from "react"
import Link from 'next/link';
import { ClipboardList, CheckCircle2, RotateCcw } from "lucide-react"

// TODO(content): questionnaire copy is pending. The questions below are the
// existing placeholder set — swap them when the final wording arrives.
const QUESTIONS = [
  {
    id: 1,
    text: "What is India's capital?",
    options: ["Mumbai", "Bangalore", "Delhi", "Kolkata"],
    correctIndex: 2,
  },
  {
    id: 2,
    text: "What is India's longest river?",
    options: ["Ganga", "Yamuna", "Kaveri", "Godavari"],
    correctIndex: 0,
  },
  {
    id: 3,
    text: "Who is India's current Prime Minister?",
    options: ["Narendra Modi", "Rahul Gandhi", "Amit Shah", "Yogi Adityanath"],
    correctIndex: 0,
  },
  {
    id: 4,
    text: "Which is India's largest state by land area among these?",
    options: ["Gujarat", "Maharashtra", "Chhattisgarh", "Uttar Pradesh"],
    correctIndex: 1,
  },
  {
    id: 5,
    text: "Which is India's smallest state by land area among these?",
    options: ["Goa", "Nagaland", "Kerala", "Telangana"],
    correctIndex: 0,
  },
]

export function QuestionnaireSection() {
  const [step, setStep] = useState(0)
  const [selected, setSelected] = useState(null)
  const [correctCount, setCorrectCount] = useState(0)
  const [finished, setFinished] = useState(false)

  const progressPct = useMemo(() => (correctCount / QUESTIONS.length) * 100, [correctCount])
  const current = QUESTIONS[step]
  const isLast = step === QUESTIONS.length - 1

  const handleNext = () => {
    if (selected == null) return
    const ok = selected === current.correctIndex
    const nextCorrect = correctCount + (ok ? 1 : 0)
    setCorrectCount(nextCorrect)
    if (isLast) {
      setFinished(true)
      return
    }
    setStep((s) => s + 1)
    setSelected(null)
  }

  const reset = () => {
    setStep(0)
    setSelected(null)
    setCorrectCount(0)
    setFinished(false)
  }

  const allCorrect = correctCount === QUESTIONS.length

  return (
    <section className="py-20 lg:py-28 bg-[#0a1628] text-slate-200">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-10">
          <p className="text-sm font-semibold text-sky-400 uppercase tracking-wider mb-3">
            Let&apos;s test your skills
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold text-sky-300 mb-3 text-balance">
            Questionnaire
          </h2>
          <p className="text-slate-400 text-lg max-w-xl mx-auto">
            Answer five quick questions. Each correct answer fills the progress bar by 20%.
          </p>
        </div>

        <div className="rounded-2xl border border-slate-700/80 bg-[#0d1f35] p-6 sm:p-8 shadow-xl">
          <div className="mb-8">
            <div className="flex justify-between text-xs text-slate-400 mb-2">
              <span>Progress</span>
              <span>{Math.round(progressPct)}%</span>
            </div>
            <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-400 transition-all duration-500 ease-out"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          {!finished ? (
            <>
              <div className="flex items-center gap-2 text-sky-400/90 text-sm font-medium mb-4">
                <ClipboardList className="w-4 h-4" />
                Question {step + 1} of {QUESTIONS.length}
              </div>
              <h3 className="text-xl font-semibold text-white mb-6">{current.text}</h3>
              <ul className="space-y-3 mb-8">
                {current.options.map((label, idx) => {
                  const active = selected === idx
                  return (
                    <li key={idx}>
                      <button
                        type="button"
                        onClick={() => setSelected(idx)}
                        className={`w-full text-left rounded-xl border px-4 py-3 text-sm sm:text-base transition-colors ${
                          active
                            ? "border-sky-500 bg-sky-500/15 text-white"
                            : "border-slate-600 bg-slate-900/40 text-slate-300 hover:border-slate-500"
                        }`}
                      >
                        <span className="font-semibold text-sky-400/90 mr-2">{idx + 1}.</span>
                        {label}
                      </button>
                    </li>
                  )
                })}
              </ul>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleNext}
                  disabled={selected == null}
                  className="rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-40 disabled:pointer-events-none text-[#0a1628] font-semibold px-8 py-3 transition-colors"
                >
                  {isLast ? "Finish" : "Next"}
                </button>
              </div>
            </>
          ) : (
            <div className="text-center py-4">
              {allCorrect ? (
                <>
                  <CheckCircle2 className="w-14 h-14 text-emerald-400 mx-auto mb-4" />
                  <p className="text-xl sm:text-2xl font-semibold text-white mb-2">
                    Your knowledge is excellent.
                  </p>
                  <p className="text-slate-400 mb-8">
                    Let&apos;s be our broker — take the next step and apply for the broker program.
                  </p>
                  <Link
                    // `/broker-program` was a 404 — the broker/IB page
                    // lives at /ib-management.
                    href="/ib-management"
                    className="inline-flex items-center justify-center rounded-xl bg-[#4D94E6] hover:bg-[#6DA8F0] text-[#0a1628] font-semibold px-8 py-3 transition-colors"
                  >
                    Apply for broker
                  </Link>
                </>
              ) : (
                <>
                  <p className="text-xl font-semibold text-white mb-2">
                    You scored {correctCount} out of {QUESTIONS.length}.
                  </p>
                  <p className="text-slate-400 mb-8">
                    Get all five correct to unlock the broker application path.
                  </p>
                  <button
                    type="button"
                    onClick={reset}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-500 text-white hover:bg-slate-800 px-6 py-3 transition-colors"
                  >
                    <RotateCcw className="w-4 h-4" />
                    Try again
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
