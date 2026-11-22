"""
Answer consistency testing for THE CLAUDE COMPANY.

Tests that the dost produces consistent answers to the same question
across multiple runs.
"""

import re
from typing import Callable, Dict, List


def run_consistency_test(prompt: str, dispatch_func: Callable,
                         num_runs: int = 5) -> dict:
    """Run consistency test on a prompt.

    Runs the same prompt N times through the dispatch function and
    checks if answers are consistent.

    Args:
        prompt: Prompt text to test
        dispatch_func: Function that takes a prompt and returns a result dict
        num_runs: Number of times to run the prompt

    Returns:
        Dict with prompt, num_runs, answers, consistency info
    """
    answers = []

    for _ in range(num_runs):
        result = dispatch_func(prompt)
        answer = result.get("result", {}).get("text", "") \
            if isinstance(result.get("result"), dict) \
            else str(result.get("result", ""))
        answers.append(answer)

    consistency_score = _compute_consistency(answers)

    return {
        "prompt": prompt,
        "num_runs": num_runs,
        "answers": answers,
        "consistent": consistency_score >= 0.8,
        "consistency_score": consistency_score,
    }


def _compute_consistency(answers: list) -> float:
    """Compute consistency score for a list of answers.

    Uses simple word overlap between first answer and subsequent answers.

    Args:
        answers: List of answer strings

    Returns:
        Consistency score between 0.0 and 1.0
    """
    if not answers:
        return 1.0

    if len(answers) == 1:
        return 1.0

    first_words = set(answers[0].lower().split())
    total_overlap = 0.0

    for answer in answers[1:]:
        answer_words = set(answer.lower().split())
        if not answer_words:
            continue
        overlap = len(first_words & answer_words) / max(len(first_words), 1)
        total_overlap += overlap

    return total_overlap / len(answers[1:])


def check_semantic_consistency(answers: list) -> float:
    """Test semantic consistency of answers using keyword overlap.

    Args:
        answers: List of answer strings

    Returns:
        Consistency score between 0.0 and 1.0
    """
    return _compute_consistency(answers)


def run_consistency_suite(prompts: list, dispatch_func: Callable,
                          runs_per_prompt: int = 3) -> dict:
    """Run consistency suite on multiple prompts.

    Args:
        prompts: List of prompt strings
        dispatch_func: Function that takes a prompt and returns a result dict
        runs_per_prompt: Number of runs per prompt

    Returns:
        Suite results with overall consistency score
    """
    results = []
    total_consistent = 0

    for prompt in prompts:
        result = run_consistency_test(prompt, dispatch_func, runs_per_prompt)
        results.append(result)
        if result["consistent"]:
            total_consistent += 1

    overall_consistency = (
        total_consistent / len(prompts) if prompts else 1.0
    )

    return {
        "total_prompts": len(prompts),
        "consistent_prompts": total_consistent,
        "overall_consistency": overall_consistency,
        "results": results,
    }