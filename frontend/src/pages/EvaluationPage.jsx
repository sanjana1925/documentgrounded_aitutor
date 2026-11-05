import { useEffect, useState, useCallback } from "react";
import {
  ShieldAlert,
  CheckCircle2,
  Info,
  Search,
  Sparkles,
  Gauge,
  ChevronDown,
  Lock,
} from "lucide-react";
import Shell from "../components/Shell";
import SectionHeader from "../components/SectionHeader";
import StickerCard from "../components/StickerCard";
import EmptyState from "../components/EmptyState";
import { PrimaryButton } from "../components/Button";
import { useApp } from "../store";
import { fetchDashboard, fetchEvaluation } from "../lib/api";

function MetricGroup({ icon: Icon, title, metrics }) {
  return (
    <StickerCard className="p-5 grid-lines">
      <div className="flex items-center gap-2 mb-4">
        <Icon size={18} strokeWidth={2.5} className="text-violet" />
        <h3 className="font-heading font-extrabold">{title}</h3>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {metrics.map(([label, value, hint]) => (
          <div key={label} title={hint}>
            <p className="text-xs font-semibold text-muted-fg">{label}</p>
            <p className="font-heading text-xl font-extrabold">{value ?? "N/A"}</p>
          </div>
        ))}
      </div>
    </StickerCard>
  );
}

export default function EvaluationPage() {
  const { currentDocument, sessionId } = useApp();

  const [dash, setDash] = useState(null);
  const [report, setReport] = useState(null);
  const [dashLoading, setDashLoading] = useState(true);
  const [error, setError] = useState("");
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [unlocked, setUnlocked] = useState(false);
  const [password, setPassword] = useState("");
  const [pwError, setPwError] = useState("");
  const [unlocking, setUnlocking] = useState(false);

  // Each data source has its own loading flag so no section shows a conclusion ("no risk", "no
  // recommendations") before the data behind it has actually arrived.
  const load = useCallback(() => {
    setError("");
    if (!currentDocument) {
      setDash(null);
      setDashLoading(false);
      return;
    }
    setDashLoading(true);
    fetchDashboard(currentDocument, sessionId)
      .then(setDash)
      .catch((err) => {
        setDash(null);
        setError(err.message || "Could not load your performance data");
      })
      .finally(() => setDashLoading(false));
  }, [currentDocument, sessionId]);

  useEffect(load, [load]);

  // The benchmark is password-protected on the server; the password is held in memory only, so a
  // page reload locks it again.
  const unlock = (e) => {
    e.preventDefault();
    setPwError("");
    setUnlocking(true);
    fetchEvaluation(password)
      .then((r) => {
        setReport(r);
        setUnlocked(true);
        setPassword("");
      })
      .catch((err) => setPwError(err.message || "Could not unlock the benchmark"))
      .finally(() => setUnlocking(false));
  };

  const sys = report?.system_evaluation;
  const k = sys?.top_k ?? 4;
  const hasLearnerData = !dashLoading && dash && dash.status !== "no_data" && dash.total_attempted > 0;
  const weakTopics = hasLearnerData ? dash.weak_topics || [] : [];
  const topicsChecked = hasLearnerData
    ? Object.values(dash.topic_stats || {}).filter((t) => t.attempts >= 2).length
    : 0;

  return (
    <Shell title="Evaluation">
      <SectionHeader
        subtitle="Your performance analysis, where you're at risk, and what to improve next."
      />

      {currentDocument && dashLoading && <p className="text-muted-fg">Loading performance analysis…</p>}
      {error && <p className="text-pink font-semibold mb-4">{error}</p>}

      {!currentDocument && (
        <EmptyState
          icon={ShieldAlert}
          title="No performance data yet"
          body="Upload a document and take an adaptive quiz to unlock at-risk detection, a personalized learning path, and feedback stats."
        />
      )}

      {currentDocument && !dashLoading && !error && !hasLearnerData && (
        <EmptyState
          icon={ShieldAlert}
          title="Take an adaptive quiz to unlock performance analysis"
          body={`No quiz attempts recorded yet for ${currentDocument}.`}
        />
      )}

      {hasLearnerData && (
        <div className="flex flex-col gap-10 mb-12">
          {/* --- Identifying at-risk topics -------------------------------- */}
          <section>
            <div className="flex items-center gap-2 mb-1">
              <ShieldAlert size={20} strokeWidth={2.5} className="text-pink" />
              <h3 className="font-heading text-xl font-extrabold">Identifying At-Risk Topics</h3>
            </div>
            <p className="text-sm text-muted-fg mb-4">
              Topics below 60% accuracy are flagged early so you can intervene before they compound.
            </p>
            {weakTopics.length === 0 && topicsChecked === 0 ? (
              <StickerCard className="p-5 bg-amber/10 flex items-center gap-3">
                <Info size={22} strokeWidth={2.5} className="text-amber-900 shrink-0" />
                <p className="font-semibold">
                  Not enough answers per topic yet. Answer at least 2 questions on a topic and it can be checked
                  against the 60% threshold.
                </p>
              </StickerCard>
            ) : weakTopics.length === 0 ? (
              <StickerCard className="p-5 bg-emerald/10 flex items-center gap-3">
                <CheckCircle2 size={22} strokeWidth={2.5} className="text-emerald shrink-0" />
                <p className="font-semibold">
                  No topics currently at risk ({topicsChecked} topic{topicsChecked === 1 ? "" : "s"} checked, all at or above 60%).
                </p>
              </StickerCard>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {weakTopics.map((topic) => {
                  const stats = dash.topic_stats?.[topic];
                  return (
                    <StickerCard key={topic} className="p-5 bg-pink/5">
                      <p className="font-heading font-extrabold mb-1">{topic}</p>
                      {stats && (
                        <p className="text-sm text-muted-fg">
                          {stats.accuracy.toFixed(1)}% accuracy across {stats.attempts} attempts
                          {" · "}
                          {(60 - stats.accuracy).toFixed(1)} points below the 60% threshold
                        </p>
                      )}
                    </StickerCard>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}

      {/* --- Secondary: technical RAG benchmark (password protected) ----------- */}
      {!unlocked && (
        <section className="border-t-2 border-border pt-6">
          <div className="flex items-center gap-2 mb-2 font-heading font-extrabold text-lg">
            <Lock size={18} strokeWidth={2.5} className="text-muted-fg" />
            System Benchmark (RAG Evaluation)
          </div>
          <p className="text-sm text-muted-fg mb-4">Enter the password to view the benchmark.</p>
          <form onSubmit={unlock} className="flex flex-col sm:flex-row gap-3 max-w-md">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              aria-label="Benchmark password"
              autoComplete="off"
              className="flex-1 min-h-[42px] px-4 rounded-md border-2 border-ink bg-white font-body focus:outline-none focus:ring-2 focus:ring-violet"
            />
            <PrimaryButton type="submit" disabled={!password || unlocking} className="text-sm px-5 py-2 min-h-[42px]">
              {unlocking ? "Checking…" : "Unlock"}
            </PrimaryButton>
          </form>
          {pwError && <p className="text-pink font-semibold text-sm mt-3" role="alert">{pwError}</p>}
        </section>
      )}

      {unlocked && sys && (
        <section className="border-t-2 border-border pt-6">
          <button
            className="flex items-center gap-2 mb-4 font-heading font-extrabold text-lg"
            onClick={() => setShowBenchmark((v) => !v)}
          >
            <Gauge size={18} strokeWidth={2.5} className="text-muted-fg" />
            System Benchmark (RAG Evaluation)
            <ChevronDown size={18} strokeWidth={2.5} className={`transition-transform ${showBenchmark ? "rotate-180" : ""}`} />
          </button>

          {showBenchmark && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 mb-10">
                <MetricGroup
                  icon={Search}
                  title="Retrieval"
                  metrics={[
                    [`Recall@${k}`, sys.avg_retrieval_recall_at_k, `Share of questions whose source chunk is in the first search's top ${k}`],
                    [`Precision@${k}`, sys.avg_retrieval_precision_at_k, `Share of the top ${k} chunks that are relevant`],
                  ]}
                />
                <MetricGroup
                  icon={Sparkles}
                  title="Generation"
                  metrics={[
                    ["Answer Similarity", sys.avg_answer_similarity, "Embedding similarity to the reference answer"],
                    ["Groundedness", sys.avg_groundedness_score, "Word overlap with the evidence the system used"],
                    ["Groundedness (equal evidence)", sys.avg_groundedness_shared, "Same overlap, but against the same top-k evidence for every system"],
                    ["Faithfulness (LLM judge)", sys.avg_faithfulness_llm_judge, "A model scores whether every claim is supported. Only present when the run used --judge"],
                  ]}
                />
                <MetricGroup
                  icon={Gauge}
                  title="System"
                  metrics={[
                    ["Avg Latency (s)", sys.avg_latency_seconds == null ? null : Number(sys.avg_latency_seconds).toFixed(1)],
                    ["Questions Evaluated", sys.num_questions],
                    ["Answered", sys.num_answered == null ? null : `${sys.num_answered} / ${sys.num_questions}`, "Similarity, groundedness and faithfulness are averaged over answered questions only"],
                    ["Declined", sys.safe_fallback_rate == null ? null : `${Math.round(sys.safe_fallback_rate * 100)}%`, "Share of questions the tutor refused or could not answer"],
                  ]}
                />
              </div>

              <StickerCard className="p-5 mb-10">
                <div className="flex items-center gap-2 mb-3">
                  <Info size={18} strokeWidth={2.5} className="text-violet" />
                  <h4 className="font-heading font-extrabold">How these are measured</h4>
                </div>
                <ul className="text-sm text-muted-fg space-y-1.5 list-disc pl-5">
                  <li>This benchmark is run offline with <code>python evaluate.py</code> on questions checked against your document. It is not recalculated while you chat.</li>
                  <li><strong>Recall / Precision</strong> test search only: did the first search find the right chunk?</li>
                  <li><strong>Answer Similarity</strong> compares meaning with a reference answer. It is a closeness score, not proof of correctness.</li>
                  <li><strong>Groundedness</strong> is a word-overlap heuristic. <strong>Equal evidence</strong> scores every system against the same top-{k} chunks, so a system that gathers more text is not favoured.</li>
                  <li><strong>Faithfulness</strong> is judged by a model and appears only when the run used <code>--judge</code>.</li>
                  <li>Declined questions are left out of the similarity, groundedness and faithfulness averages. Check "Answered" and "Declined" to see how many.</li>
                  {sys.num_questions < 20 && (
                    <li>Only {sys.num_questions} questions were scored, so one question moves an average a lot. Treat small differences as noise.</li>
                  )}
                </ul>
              </StickerCard>

              {report.results?.length > 0 && (
                <div>
                  <h4 className="font-heading text-lg font-extrabold mb-4">Benchmark Details per Question</h4>
                  <StickerCard className="overflow-x-auto">
                    <table className="w-full text-left border-collapse min-w-[720px]">
                      <thead>
                        <tr className="border-b-2 border-ink text-xs uppercase font-bold text-muted-fg">
                          <th className="px-4 py-3">ID</th>
                          <th className="px-4 py-3">Question</th>
                          <th className="px-4 py-3">Topic</th>
                          <th className="px-4 py-3">Difficulty</th>
                          <th className="px-4 py-3">Recall@{k}</th>
                          <th className="px-4 py-3">Similarity</th>
                          <th className="px-4 py-3">Groundedness</th>
                          <th className="px-4 py-3">Latency (s)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.results.map((r) => (
                          <tr key={r.id} className="border-b border-border last:border-0">
                            <td className="px-4 py-3">{r.id}</td>
                            <td className="px-4 py-3 max-w-xs truncate">{r.question}</td>
                            <td className="px-4 py-3">{r.topic}</td>
                            <td className="px-4 py-3">{r.difficulty}</td>
                            <td className="px-4 py-3">{r.retrieval_recall_at_k}</td>
                            {r.abstained ? (
                              <td className="px-4 py-3" colSpan={2}>
                                <span className="px-2.5 py-1 rounded-pill border-2 border-pink bg-pink/10 text-pink text-xs font-bold uppercase">
                                  Refused
                                </span>
                              </td>
                            ) : (
                              <>
                                <td className="px-4 py-3">{r.answer_similarity}</td>
                                <td className="px-4 py-3">{r.groundedness_score}</td>
                              </>
                            )}
                            <td className="px-4 py-3">{r.latency_seconds == null ? "" : Number(r.latency_seconds).toFixed(1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </StickerCard>
                </div>
              )}
            </>
          )}
        </section>
      )}
    </Shell>
  );
}
