"""
Prompt mutation testing for THE CLAUDE COMPANY.

Tests that dispatch prompts are robust to minor variations -
if a prompt is slightly rephrased, the answer should remain
consistent (same meaning, similar answer).
"""

import random
import string
from typing import Callable, Dict, List


def mutate_prompt(prompt: str, mutation_type: str) -> str:
    """Mutate a prompt using the specified mutation type.

    Args:
        prompt: Original prompt text
        mutation_type: One of "synonym", "reorder", "add_noise",
                       "remove_punctuation", "change_case"

    Returns:
        Mutated prompt string
    """
    if mutation_type == "synonym":
        # Simple synonym replacement for common words
        synonyms = {
            "what": "which",
            "is": "are",
            "the": "this",
            "fleet": "system",
            "status": "state",
            "completion": "completion_rate",
            "rate": "percentage",
            "error": "mistake",
            "error_rate": "error_percentage",
        }
        words = prompt.split()
        mutated = []
        for word in words:
            lower = word.lower()
            if lower in synonyms:
                mutated.append(synonyms[lower])
            else:
                mutated.append(word)
        return " ".join(mutated)

    elif mutation_type == "reorder":
        words = prompt.split()
        if len(words) > 3:
            mid = len(words) // 2
            return " ".join(words[mid:] + words[:mid])
        return prompt

    elif mutation_type == "add_noise":
        return prompt + " (please answer accurately)"

    elif mutation_type == "remove_punctuation":
        return prompt.translate(str.maketrans("", "", string.punctuation))

    elif mutation_type == "change_case":
        return prompt.swapcase()

    return prompt


def run_mutation_test(prompt: str, dispatch_func: Callable,
                      num_mutations: int = 5) -> dict:
    """Run mutation test on a dispatch prompt.

    Args:
        prompt: Original prompt text
        dispatch_func: Function that takes a prompt and returns a result dict
        num_mutations: Number of mutated variants to test

    Returns:
        Dict with mutation test results including original answer,
        mutated answers, consistency score, and mutation statistics.
    """
    # Get original answer
    original_result = dispatch_func(prompt)
    original_answer = original_result.get("result", {}).get("text", "") \
        if isinstance(original_result.get("result"), dict) \
        else str(original_result.get("result", ""))

    mutated_answers = []
    mutations_passed = 0

    mutation_types = ["synonym", "reorder", "add_noise",
                      "remove_punctuation", "change_case"]

    for i in range(num_mutations):
        mutation_type = mutation_types[i % len(mutation_types)]
        mutated_prompt = mutate_prompt(prompt, mutation_type)
        mutated_result = dispatch_func(mutated_prompt)
        mutated_answer = mutated_result.get("result", {}).get("text", "") \
            if isinstance(mutated_result.get("result"), dict) \
            else str(mutated_result.get("result", ""))

        mutated_answers.append({
            "mutation_type": mutation_type,
            "prompt": mutated_prompt,
            "answer": mutated_answer,
        })

        # Simple consistency check: if original answer contains key
        # phrases that also appear in mutated answer, count as passed
        if original_answer and mutated_answer:
            original_words = set(original_answer.lower().split())
            mutated_words = set(mutated_answer.lower().split())
            overlap = len(original_words & mutated_words) / max(
                len(original_words), 1
            )
            if overlap >= 0.5:
                mutations_passed += 1

    consistency_score = mutations_passed / num_mutations if num_mutations > 0 else 1.0

    return {
        "original_prompt": prompt,
        "original_answer": original_answer,
        "mutated_answers": mutated_answers,
        "mutations_passed": mutations_passed,
        "total_mutations": num_mutations,
        "consistency_score": consistency_score,
    }


def check_prompt_stability(prompt: str, dispatch_func: Callable) -> dict:
    """Test prompt stability by running mutation test.

    Args:
        prompt: Original prompt text
        dispatch_func: Function that takes a prompt and returns a result dict

    Returns:
        Stability test results dict
    """
    return run_mutation_test(prompt, dispatch_func, num_mutations=5)