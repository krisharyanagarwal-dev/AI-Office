"""
Golden dataset testing for THE CLAUDE COMPANY.

Tests dispatch results against a pre-registered dataset of
known-good question/answer pairs.
"""

import json
from typing import Callable, Dict, List


def load_golden_dataset(path: str) -> list:
    """Load golden dataset from JSONL file.

    Each line is a JSON object with:
        - claim: The question/prompt text
        - expected_answer: Expected answer text
        - expected_agent: Expected agent_id
        - category: Category of the finding

    Args:
        path: Path to JSONL file

    Returns:
        List of finding dicts
    """
    findings = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                findings.append(json.loads(line))
    return findings


def run_golden_dataset_test(dispatch_func: Callable,
                            dataset_path: str) -> dict:
    """Run golden dataset test.

    Runs each golden dataset entry through the dispatch function
    and compares the answer to the expected answer.

    Args:
        dispatch_func: Function that takes a prompt and returns a result dict
        dataset_path: Path to golden dataset JSONL file

    Returns:
        Dict with total, passed, failed, accuracy, and per-result details
    """
    dataset = load_golden_dataset(dataset_path)

    passed = 0
    failed = 0
    results = []

    for finding in dataset:
        prompt = finding.get("claim", "")
        expected = finding.get("expected_answer", "")

        result = dispatch_func(prompt)
        actual = result.get("result", {}).get("text", "") \
            if isinstance(result.get("result"), dict) \
            else str(result.get("result", ""))

        passed_flag = _answers_match(expected, actual)

        if passed_flag:
            passed += 1
        else:
            failed += 1

        results.append({
            "prompt": prompt,
            "expected": expected,
            "actual": actual,
            "passed": passed_flag,
            "agent": finding.get("expected_agent", ""),
            "category": finding.get("category", ""),
        })

    total = len(dataset)
    accuracy = passed / total if total > 0 else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "accuracy": accuracy,
        "results": results,
    }


def _answers_match(expected: str, actual: str) -> bool:
    """Check if actual answer matches expected answer.

    Uses simple keyword overlap for comparison.
    """
    if not expected or not actual:
        return expected == actual

    expected_words = set(expected.lower().split())
    actual_words = set(actual.lower().split())

    if not expected_words:
        return True

    overlap = len(expected_words & actual_words) / len(expected_words)
    return overlap >= 0.6


def create_golden_dataset(output_path: str) -> str:
    """Create a golden dataset file with sample entries.

    Args:
        output_path: Path to write the dataset file

    Returns:
        Path to the created file
    """
    sample_findings = [
        {
            "claim": "What is the fleet completion rate?",
            "expected_answer": "100%",
            "expected_agent": "strategy-advisor",
            "category": "fleet_status",
        },
        {
            "claim": "What is the current error rate?",
            "expected_answer": "0.0%",
            "expected_agent": "strategy-advisor",
            "category": "fleet_status",
        },
        {
            "claim": "How many pools are available?",
            "expected_answer": "6",
            "expected_agent": "strategy-advisor",
            "category": "fleet_status",
        },
    ]

    with open(output_path, "w") as f:
        for finding in sample_findings:
            f.write(json.dumps(finding) + "\n")

    return output_path