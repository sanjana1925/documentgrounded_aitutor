"""
Evaluation harness: baseline RAG vs agentic RAG on a verified golden dataset.

    python evaluate.py --dataset golden_dataset_chem.json --session <session_id> --document chem.pdf --arm both
    python evaluate.py ... --judge        # also run LLM-as-judge faithfulness / relevancy (extra LLM calls)
    python evaluate.py ... --langsmith    # also create LangSmith dataset + one experiment per arm

Only examples that verify against the indexed document are scored. If none do, nothing is written and the
metrics stay "Not evaluated yet" - numbers are never guessed. Results go to evaluation_report.json (schema v2).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from backend.main import EMBEDDING_MODEL_NAME  # noqa: F401  (importing backend.main loads .env and configures tracing)

from google import genai

from backend import config
from backend.container import get_container
from backend.evaluation.dataset import load_dataset, split_verified
from backend.evaluation.langsmith_experiment import run_experiments
from backend.evaluation.report import save_report
from backend.services.evaluation_service import EvaluationService, build_report, default_embedder
from backend.services.llm_service import GeminiLLM
from backend.services.retrieval_service import Scope


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(config.DATA_DIR / "golden_dataset_chem.json"))
    parser.add_argument("--session", default="default", help="session id the document was indexed under")
    parser.add_argument("--document", help="document name (defaults to the dataset's source_document)")
    parser.add_argument("--arm", choices=["baseline", "agentic", "both"], default="both")
    parser.add_argument("--judge", action="store_true", help="add LLM-as-judge faithfulness and relevancy")
    parser.add_argument("--judge-model", default="", help="Gemini model that scores faithfulness (default: the answering model, i.e. self-judging)")
    parser.add_argument("--langsmith", action="store_true", help="also run LangSmith experiments")
    parser.add_argument("--langsmith-only", action="store_true", help="skip the local run/report and only run LangSmith experiments")
    parser.add_argument("--prefix", default="tutor-eval")
    parser.add_argument("--pause", type=float, default=3.0, help="seconds between questions (rate limits)")
    parser.add_argument("--retries", type=int, default=2, help="retries per question on provider errors such as 429")
    parser.add_argument("--backoff", type=float, default=15.0, help="seconds to wait before the first retry (grows each retry)")
    parser.add_argument("--report", default=str(config.DATA_DIR / "evaluation_report.json"))
    args = parser.parse_args()

    items = load_dataset(Path(args.dataset))
    if not items:
        print(f"No examples found in {args.dataset}. Not evaluated yet.")
        return 2

    document = args.document or items[0]["source_document"]
    scope = Scope(args.session, document)
    container = get_container()
    verified, rejected = split_verified(container.retrieval, scope, items)
    print(f"{len(verified)}/{len(items)} examples verified against '{document}' (session '{args.session}').")
    for r in rejected:
        print(f"  not verified: #{r['id']} - {'; '.join(r['verification']['reasons'])}")
    if not verified:
        print("\nNot evaluated yet: no example could be verified against an indexed document, so nothing was scored")
        print("and the existing report (if any) was left untouched. Index the source PDF, or build a dataset with:")
        print("  python -m backend.evaluation.build_golden --session <id> --document <name>.pdf")
        return 2

    judge_llm = None
    if args.judge_model:
        judge_llm = GeminiLLM(genai.Client(api_key=os.environ.get("GEMINI_API_KEY")), args.judge_model)
    if args.judge:
        judge_name = args.judge_model or config.ANSWER_MODEL
        print(f"LLM judge: {judge_name}" + ("  (same model that writes the answers: scores may be flattering; use --judge-model)" if not args.judge_model else ""))
    service = EvaluationService(container.llm, container.retrieval, container.graph, default_embedder(), judge_llm=judge_llm)
    arms = {"baseline": ["baseline_rag"], "agentic": ["agentic_rag"], "both": ["baseline_rag", "agentic_rag"]}[args.arm]
    results = {}
    for arm in ([] if args.langsmith_only else arms):
        print(f"\n=== {arm} ===")

        def show(row):
            if row.get("errored"):
                print(f"[{row['id']}] ERRORED (excluded from metrics): {row['error']}")
                return
            print(f"[{row['id']}] recall@{service.top_k}={row['retrieval_recall_at_k']} sim={row['answer_similarity']} "
                  f"grounded={row['groundedness_score']}/shared={row['groundedness_shared']} evidence_chunks={row['evidence_chunks']} "
                  f"llm_calls={row['llm_calls']} tools={row['tool_calls']} {row['latency_seconds']}s {'(abstained)' if row['abstained'] else ''}")

        results[arm] = service.run(arm, scope, verified, judge=args.judge, pause=args.pause, retries=args.retries, backoff=args.backoff, on_row=show)

    dataset_info = {
        "path": args.dataset, "document": document, "total_examples": len(items), "verified_examples": len(verified),
        "unverified": [{"id": r["id"], "reasons": r["verification"]["reasons"]} for r in rejected],
        "origins": sorted({i.get("origin", "unspecified") for i in verified}),
        "answer_model": config.ANSWER_MODEL,
        "judge_model": (args.judge_model or config.ANSWER_MODEL) if args.judge else None,
    }
    report = build_report(results, dataset_info, service.top_k) if results else None
    if report:
        save_report(report, Path(args.report))
        print(f"\nReport saved to {args.report}")
        print(json.dumps({arm: report["arms"][arm]["system_evaluation"] for arm in report["arms"]}, indent=2))
        if "comparison" in report:
            print("\nComparison (agentic - baseline):")
            for key, c in report["comparison"].items():
                print(f"  {key}: baseline={c['baseline']} agentic={c['agentic']} delta={c['delta']}")

    if args.langsmith or args.langsmith_only:
        outcome = run_experiments(
            service, scope, verified, arms, args.prefix, judge=args.judge, pause=args.pause,
            retries=args.retries, backoff=args.backoff, judge_pause=args.pause / 2,
        )
        print("\nLangSmith:", json.dumps(outcome, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
