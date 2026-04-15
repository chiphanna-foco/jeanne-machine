"""Eval harness for the relevance classifier.

Loads labeled documents from a JSONL file and evaluates the classifier's
precision and recall against gold-standard labels.

Target metrics (from §6 of the build plan):
- Precision ≥ 0.90 (no false positives in digest)
- Recall ≥ 0.75

Usage:
    pytest tests/eval/test_classifier.py -v

Set ANTHROPIC_API_KEY in the environment or .env to run live evals.
For CI without API access, set SKIP_LIVE_EVAL=1 to skip.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


EVAL_DATA_PATH = Path(__file__).parent / "labeled_documents.jsonl"
SKIP_LIVE = os.environ.get("SKIP_LIVE_EVAL", "0") == "1"


def load_labeled_docs() -> list[dict]:
    """Load the labeled evaluation dataset."""
    if not EVAL_DATA_PATH.exists():
        pytest.skip(f"Eval dataset not found at {EVAL_DATA_PATH}")

    docs = []
    with open(EVAL_DATA_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


@pytest.fixture(scope="module")
def labeled_docs():
    return load_labeled_docs()


@pytest.mark.skipif(SKIP_LIVE, reason="SKIP_LIVE_EVAL=1")
@pytest.mark.asyncio
async def test_classifier_precision_and_recall(labeled_docs):
    """Run the classifier on all labeled docs and check precision ≥ 0.90, recall ≥ 0.75."""
    from enrichment.classifier import classify_document

    true_positives = 0
    false_positives = 0
    false_negatives = 0
    true_negatives = 0

    results = []

    for doc in labeled_docs:
        text = doc["text"]
        expected_relevant = doc["relevant"]

        classification = await classify_document(text)
        predicted_relevant = classification["relevant"] and classification["confidence"] >= 0.6

        results.append(
            {
                "id": doc.get("id", "?"),
                "expected": expected_relevant,
                "predicted": predicted_relevant,
                "confidence": classification["confidence"],
                "topics_expected": doc.get("topics", []),
                "topics_predicted": classification.get("topics", []),
            }
        )

        if expected_relevant and predicted_relevant:
            true_positives += 1
        elif not expected_relevant and predicted_relevant:
            false_positives += 1
        elif expected_relevant and not predicted_relevant:
            false_negatives += 1
        else:
            true_negatives += 1

    total = len(labeled_docs)
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 1.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 1.0

    print(f"\n{'='*60}")
    print(f"Classifier Eval Results ({total} documents)")
    print(f"{'='*60}")
    print(f"  True Positives:  {true_positives}")
    print(f"  False Positives: {false_positives}")
    print(f"  True Negatives:  {true_negatives}")
    print(f"  False Negatives: {false_negatives}")
    print(f"  Precision:       {precision:.3f} (target ≥ 0.90)")
    print(f"  Recall:          {recall:.3f} (target ≥ 0.75)")
    print(f"{'='*60}")

    # Log any misclassifications for debugging
    misclassified = [r for r in results if r["expected"] != r["predicted"]]
    if misclassified:
        print(f"\nMisclassified ({len(misclassified)}):")
        for r in misclassified:
            label = "FP" if r["predicted"] else "FN"
            print(f"  [{label}] id={r['id']} conf={r['confidence']:.2f}")

    assert precision >= 0.90, f"Precision {precision:.3f} below target 0.90"
    assert recall >= 0.75, f"Recall {recall:.3f} below target 0.75"


def test_eval_data_format(labeled_docs):
    """Verify the eval dataset has the expected format."""
    assert len(labeled_docs) >= 10, f"Expected at least 10 labeled docs, got {len(labeled_docs)}"

    for i, doc in enumerate(labeled_docs):
        assert "text" in doc, f"Doc {i} missing 'text' field"
        assert "relevant" in doc, f"Doc {i} missing 'relevant' field"
        assert isinstance(doc["relevant"], bool), f"Doc {i} 'relevant' must be bool"
        if doc["relevant"]:
            assert "topics" in doc, f"Relevant doc {i} should have 'topics'"
            assert len(doc["topics"]) > 0, f"Relevant doc {i} should have at least one topic"
