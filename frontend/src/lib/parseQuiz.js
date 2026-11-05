// The /agent (mode=quiz) endpoint returns a single markdown "reply" string that mixes
// feedback on the previous answer with the newly generated question. The structured
// question itself is already available on quiz_details.question_dict, so the only
// thing we need to pull out of the markdown here is the feedback block and the
// "question N of 15" progress text. This is presentation-only parsing of an
// existing, unchanged API response — no backend behavior is touched.

export function parseQuizFeedback(replyText) {
  if (!replyText) return null;
  let marker = replyText.indexOf("📊 `");
  if (marker === -1) marker = replyText.indexOf("🏁"); // final turn: feedback, then the result, no next question
  const feedbackText = marker === -1 ? "" : replyText.slice(0, marker).replace(/^-+\s*/, "").trim();
  if (!feedbackText) return null;

  const isCorrect = feedbackText.includes("✅");
  const isIncorrect = feedbackText.includes("❌");
  if (!isCorrect && !isIncorrect) return null;

  const correctOptionMatch = feedbackText.match(/\(Correct option:\s*\*\*(.*?)\*\*\)/);
  const explanationMatch = feedbackText.match(/\*([^*]+)\*(?!\*)/);
  const transitionMatch = feedbackText.match(
    /Benchmark Achieved!\*\*\s*You scored\s*\*\*([\d.]+)%\*\*\s*and progressed to the\s*\*\*(\w+)\*\*/
  );

  return {
    isCorrect,
    correctOptionText: correctOptionMatch ? correctOptionMatch[1] : null,
    explanation: explanationMatch ? explanationMatch[1].trim() : "",
    phaseTransition: transitionMatch
      ? { accuracy: transitionMatch[1], newPhase: transitionMatch[2] }
      : null,
  };
}

export function parseQuizProgress(replyText) {
  if (!replyText) return { questionNumber: null, questionTotal: null };
  const match = replyText.match(/Question \*\*(\d+)\*\*(?: of (\d+))?/);
  return {
    questionNumber: match ? Number(match[1]) : null,
    questionTotal: match && match[2] ? Number(match[2]) : null,
  };
}
