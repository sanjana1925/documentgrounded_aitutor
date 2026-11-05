import { useCallback, useEffect, useState } from "react";
import { Brain, RotateCcw, CheckCircle2, XCircle, PartyPopper, ArrowRight } from "lucide-react";
import Shell from "../components/Shell";
import SectionHeader from "../components/SectionHeader";
import StickerCard from "../components/StickerCard";
import ProgressBar from "../components/ProgressBar";
import { PrimaryButton, SecondaryButton } from "../components/Button";
import EmptyState from "../components/EmptyState";
import { useApp } from "../store";
import { sendAgentMessage, resetQuiz } from "../lib/api";
import { parseQuizFeedback, parseQuizProgress } from "../lib/parseQuiz";

const PHASE_COLOR = { SIMPLE: "#8B5CF6", MEDIUM: "#F472B6", HIGH: "#FBBF24" };

export default function QuizPage() {
  const { currentDocument, sessionId } = useApp();
  const [resp, setResp] = useState(null);
  const [selected, setSelected] = useState(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const fetchNext = useCallback(
    async (message) => {
      if (!currentDocument) return;
      setLoading(true);
      setError("");
      try {
        const data = await sendAgentMessage({ message, filename: currentDocument, sessionId, mode: "quiz" });
        setResp(data);
        setShowFeedback(Boolean(parseQuizFeedback(data.reply)));
        setSelected(null);
      } catch (err) {
        setError(err.message || "Could not load the next question");
      } finally {
        setLoading(false);
        setSubmitting(false);
      }
    },
    [currentDocument, sessionId]
  );

  useEffect(() => {
    if (currentDocument && !resp) fetchNext("Start quiz");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentDocument]);

  async function handleReset() {
    if (!currentDocument) return;
    try {
      await resetQuiz(currentDocument, sessionId);
    } catch {
      /* best-effort reset */
    }
    setResp(null);
    setSelected(null);
    setShowFeedback(false);
    fetchNext("Start quiz");
  }

  async function handleSubmit() {
    if (selected === null || submitting) return;
    setSubmitting(true);
    await fetchNext(String(selected));
  }

  function handleContinue() {
    setShowFeedback(false);
    setSelected(null);
  }

  const quizComplete = Boolean(resp?.quiz_details?.quiz_complete);
  const question = resp?.quiz_details?.question_dict;
  const phase = resp?.quiz_details?.current_phase || "SIMPLE";
  const progress = parseQuizProgress(resp?.reply);
  const feedback = parseQuizFeedback(resp?.reply);
  const phaseColor = PHASE_COLOR[phase] || "#8B5CF6";

  return (
    <Shell title="Adaptive Quiz">
      <SectionHeader
        subtitle="Three difficulty phases that only level up once you clear the 70% benchmark."
      />

      {!currentDocument && (
        <EmptyState icon={Brain} title="Upload a document to start your first quiz" body="Index a PDF to unlock adaptive questions." />
      )}

      {currentDocument && (
        <>
          <div className="flex items-center justify-between mb-6">
            <span
              className="px-4 py-1.5 rounded-pill border-2 border-ink font-heading font-extrabold text-sm uppercase tracking-wide"
              style={{ background: `${phaseColor}33` }}
            >
              {phase}
            </span>
            <SecondaryButton icon={RotateCcw} onClick={handleReset} className="text-sm px-4 py-2 min-h-[40px]">
              Reset Quiz
            </SecondaryButton>
          </div>

          {progress.questionNumber && (
            <div className="mb-6">
              <div className="flex justify-between text-sm font-semibold mb-2">
                <span>
                  Question {progress.questionNumber}
                  {progress.questionTotal ? ` / ${progress.questionTotal}` : ""}
                </span>
              </div>
              {progress.questionTotal && (
                <ProgressBar
                  percent={(progress.questionNumber / progress.questionTotal) * 100}
                  color={phaseColor}
                  label="Quiz progress"
                />
              )}
            </div>
          )}

          {error && <p className="text-pink font-semibold mb-4">{error}</p>}
          {loading && !resp && <p className="text-muted-fg">Generating adaptive question…</p>}

          {showFeedback && feedback && (
            <StickerCard className={`p-6 mb-6 ${feedback.isCorrect ? "bg-emerald/10" : "bg-pink/10"}`}>
              <div className="flex items-center gap-3 mb-3">
                {feedback.isCorrect ? (
                  <CheckCircle2 size={26} strokeWidth={2.5} className="text-emerald" />
                ) : (
                  <XCircle size={26} strokeWidth={2.5} className="text-pink" />
                )}
                <h3 className="font-heading text-xl font-extrabold">
                  {feedback.isCorrect ? "Correct" : "Not quite"}
                </h3>
              </div>
              {!feedback.isCorrect && feedback.correctOptionText && (
                <p className="mb-2 text-sm font-semibold">Correct answer: {feedback.correctOptionText}</p>
              )}
              {feedback.explanation && <p className="text-muted-fg mb-4">{feedback.explanation}</p>}

              {feedback.phaseTransition && (
                <div className="mt-4 p-5 rounded-md border-2 border-ink bg-white text-center">
                  <PartyPopper size={28} strokeWidth={2.5} className="mx-auto mb-2 text-amber" />
                  <h4 className="font-heading text-lg font-extrabold mb-1">Phase Complete!</h4>
                  <p className="text-sm text-muted-fg mb-2">
                    Scored {feedback.phaseTransition.accuracy}% and progressed to{" "}
                    <strong>{feedback.phaseTransition.newPhase}</strong>.
                  </p>
                  {resp?.quiz_details?.weak_topics?.length > 0 && (
                    <p className="text-sm">Topics to review: {resp.quiz_details.weak_topics.join(", ")}</p>
                  )}
                </div>
              )}

              <PrimaryButton icon={ArrowRight} onClick={handleContinue} className="mt-5">
                Continue
              </PrimaryButton>
            </StickerCard>
          )}

          {!showFeedback && quizComplete && (
            <StickerCard className="p-6 sm:p-8 text-center">
              <PartyPopper size={32} strokeWidth={2.5} className="mx-auto mb-3 text-amber" />
              <h3 className="font-heading text-2xl font-extrabold mb-2">Quiz complete</h3>
              <p className="text-lg font-semibold mb-1">
                Score: {resp.quiz_score} / {resp.quiz_total} ({Math.round(resp.quiz_details.overall_accuracy)}%)
              </p>
              <p className="text-muted-fg mb-5">You need 70% to unlock the next phase. Reset to try again.</p>
              {resp.quiz_details.weak_topics?.length > 0 && (
                <p className="text-sm mb-5">Topics to review: {resp.quiz_details.weak_topics.join(", ")}</p>
              )}
              <PrimaryButton icon={RotateCcw} onClick={handleReset}>Reset Quiz</PrimaryButton>
            </StickerCard>
          )}

          {!showFeedback && question && (
            <StickerCard className="p-6 sm:p-8">
              <span className="inline-block px-3 py-1 rounded-pill border-2 border-ink bg-muted text-xs font-bold uppercase tracking-wide mb-4">
                {phase} · {question.topic}
              </span>
              <h3 className="font-heading text-2xl font-extrabold mb-6 leading-snug">{question.question}</h3>

              <div className="flex flex-col gap-3 mb-6">
                {question.options.map((opt, idx) => {
                  const isSelected = selected === idx;
                  return (
                    <button
                      key={idx}
                      onClick={() => setSelected(idx)}
                      className={`text-left px-5 py-4 rounded-md border-2 border-ink font-body font-semibold min-h-[48px] tactile
                        ${isSelected ? "bg-violet text-white shadow-sm" : "bg-white hover:border-violet hover:shadow-std"}`}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>

              <div className="flex justify-end">
                <PrimaryButton onClick={handleSubmit} disabled={selected === null || submitting}>
                  {submitting ? "Grading…" : "Submit Answer"}
                </PrimaryButton>
              </div>
            </StickerCard>
          )}
        </>
      )}
    </Shell>
  );
}
