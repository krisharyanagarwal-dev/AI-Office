"""
Load testing for THE CLAUDE COMPANY dispatcher.

Tests dispatch performance under concurrent load and sustained load.
"""

import time
from typing import Callable, Dict, List


def run_load_test(dispatch_func: Callable,
                  num_concurrent: int,
                  num_requests: int) -> dict:
    """Run load test with concurrent dispatch requests.

    Args:
        dispatch_func: Function that takes a prompt and returns a result dict
        num_concurrent: Number of concurrent requests
        num_requests: Total number of requests to send

    Returns:
        Dict with total_requests, completed, failed, avg_response_time,
        max_response_time, requests_per_second
    """
    import concurrent.futures

    prompts = [f"Load test prompt {i}" for i in range(num_requests)]
    results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=num_concurrent
    ) as executor:
        futures = {
            executor.submit(dispatch_func, prompt): i
            for i, prompt in enumerate(prompts)
        }

        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append({"error": str(e)})

    end_time = time.time()
    total_time = end_time - start_time

    completed = sum(1 for r in results if "error" not in r)
    failed = len(results) - completed

    return {
        "total_requests": len(results),
        "completed": completed,
        "failed": failed,
        "avg_response_time": total_time / len(results) if results else 0,
        "requests_per_second": len(results) / total_time if total_time > 0 else 0,
    }


def run_sustained_load_test(dispatch_func: Callable,
                            requests_per_second: int,
                            duration_seconds: int) -> dict:
    """Run sustained load test at a constant rate.

    Args:
        dispatch_func: Function that takes a prompt and returns a result dict
        requests_per_second: Number of requests per second
        duration_seconds: Duration in seconds

    Returns:
        Dict with total_requests, completed, failed, avg_response_time, errors
    """
    import time
    import concurrent.futures

    total_requests = requests_per_second * duration_seconds
    results = []
    start_time = time.time()
    end_time = start_time + duration_seconds

    interval = 1.0 / requests_per_second

    while time.time() < end_time:
        prompt = f"Load test {len(results)}"
        try:
            result = dispatch_func(prompt)
            results.append(result)
        except Exception as e:
            results.append({"error": str(e)})

        # Wait for next interval
        elapsed = time.time() - start_time
        expected_time = (len(results) + 1) / requests_per_second
        if elapsed < expected_time:
            time.sleep(expected_time - elapsed)

    completed = sum(1 for r in results if "error" not in r)
    failed = len(results) - completed

    total_time = time.time() - start_time

    return {
        "total_requests": len(results),
        "completed": completed,
        "failed": failed,
        "avg_response_time": total_time / len(results) if results else 0,
        "errors": [r.get("error") for r in results if "error" in r],
    }


def find_breaking_point(dispatch_func: Callable,
                        max_concurrent: int = 100) -> dict:
    """Find the breaking point of the system.

    Gradually increases concurrent load until failure rate exceeds threshold.

    Args:
        dispatch_func: Function that takes a prompt and returns a result dict
        max_concurrent: Maximum concurrent requests to test

    Returns:
        Dict with breaking_point, max_concurrent_handled, and results
    """
    breaking_point = None
    max_concurrent_handled = 0
    results = []

    for concurrent in [1, 5, 10, 20, 30, 50, 75, max_concurrent]:
        result = run_load_test(dispatch_func, concurrent, concurrent * 2)
        results.append({
            "concurrent": concurrent,
            "completed": result["completed"],
            "failed": result["failed"],
            "error_rate": result["failed"] / result["total_requests"]
            if result["total_requests"] > 0 else 0,
        })

        if result["failed"] / result["total_requests"] > 0.5:
            breaking_point = concurrent
            break

        max_concurrent_handled = concurrent

    return {
        "breaking_point": breaking_point,
        "max_concurrent_handled": max_concurrent_handled,
        "results": results,
    }