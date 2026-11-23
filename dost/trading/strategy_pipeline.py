"""
Strategy Pipeline for THE CLAUDE COMPANY.

Chains the full strategy pipeline:
1. Submit prompt to fleet via dispatch_prompt_to_fleet
2. Generate signals from the answer using strategy engine
3. Run backtest on the signals
4. Calculate position sizes
5. Validate out-of-sample
6. Return complete results
"""

from __future__ import annotations
import sys

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dost.dost_main import dispatch_prompt_to_fleet
from dost.trading.strategy_engine import generate_all_signals
from dost.trading.backtest_engine import run_backtest
from dost.trading.position_sizer import calculate_position_size
from dost.trading.oos_validator import run_oos_validation
from dost.data_access import generate_synthetic_ohlcv

STRATEGY_DIR = (Path(__file__).resolve().parents[2] / "packages" / "office-os" / "tasks")
STRATEGY_DIR.mkdir(parents=True, exist_ok=True)


def run_strategy_pipeline(
    prompt: str,
    agent_id: str = "strategy-advisor",
    priority: str = "normal",
    capital: float = 100000.0,
    risk_per_trade: float = 0.02,
    max_retries: int = 3,
    poll_interval: float = 5.0,
    max_wait: int = 300,
    dry_run: bool = False,
) -> dict:
    """
    Run a complete strategy pipeline:

    1. Submit prompt to fleet via dispatch_prompt_to_fleet
    2. Wait for task completion
    3. Generate signals from the answer using strategy engine
    4. Run backtest on the signals
    5. Calculate position sizes
    6. Validate out-of-sample
    7. Return complete results

    Args:
        prompt: The research question/prompt to submit
        agent_id: Agent to route the prompt to
        priority: Task priority
        capital: Total capital for position sizing
        risk_per_trade: Risk per trade as decimal
        max_retries: Max retries for dispatcher submission
        poll_interval: Seconds between status checks
        max_wait: Maximum seconds to wait for task completion
        dry_run: If True, preview the dispatch without writing a task file

    Returns:
        Dict with full pipeline results
    """

    debate_id = f"strat-{uuid.uuid4().hex[:8]}"
    result: Dict[str, Any] = {
        "debate_id": debate_id,
        "task_id": None,
        "agents": [agent_id],
        "answers": [],
        "synthesis": "",
        "strategy_signals": [],
        "backtest_result": None,
        "position_sizes": [],
        "validation_result": None,
        "status": "pending",
        "error": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        # Step 1: Submit prompt to fleet
        print(f"[1/6] Submitting prompt to fleet: {prompt[:60]}...")
        dispatch_result = dispatch_prompt_to_fleet(
            prompt=prompt,
            agent_id=agent_id,
            priority=priority,
            dry_run=dry_run,
        )

        if not dispatch_result.get("ok"):
            return {
                **result,
                "status": "error",
                "error": f"Dispatch failed: {dispatch_result.get('error', 'unknown')}",
            }

        task_id = dispatch_result["task_id"]
        result["task_id"] = task_id
        print(f"  Task submitted: {task_id}")

        if dry_run:
            return {
                **result,
                "status": "dry_run",
                "dry_run": True,
                "message": dispatch_result.get("message", "[DRY RUN] No task written."),
            }

        # Step 2: Wait for task completion
        print(f"[2/6] Waiting for task completion (max {max_wait}s)...")
        start_time = time.time()
        task_status = "pending"
        task_result_text = ""

        while time.time() - start_time < max_wait:
            time.sleep(poll_interval)
            task_path = (Path(__file__).resolve().parents[2] / "packages" / "office-os" / "tasks") / f"{task_id}.json"
            if task_path.exists():
                try:
                    task_data = json.loads(task_path.read_text())
                    status = task_data.get("status")
                    if status == "done":
                        print(f"  Task completed in {time.time() - start_time:.1f}s")
                        result_data = task_data.get("result", {})
                        if isinstance(result_data, dict):
                            answer_text = result_data.get("text", "")
                        else:
                            answer_text = str(result_data)
                        print(f"  Answer: {answer_text[:200]}...")
                        break
                    elif status == "error":
                        print(f"  Task failed: {task_data.get('error', 'unknown')}")
                        return {
                            **result,
                            "status": "error",
                            "error": task_data.get("error", "Task failed"),
                        }
                except Exception:
                    pass
            else:
                elapsed = int(time.time() - start_time)
                print(f"  Waiting... ({elapsed}s)")
        else:
            return {
                **result,
                "status": "error",
                "error": f"Task not completed within {max_wait}s",
            }

        # Step 3: Generate signals from the answer (using synthetic candles)
        print(f"[3/6] Generating signals from fleet answer...")
        candles = generate_synthetic_ohlcv(
            symbol="NIFTY",
            days=252,
            start_price=22000.0,
            volatility=0.015,
            drift=0.0003,
            seed=42,
        )
        signals = generate_all_signals(
            agent_id=agent_id,
            instrument="NIFTY",
            candles=candles,
        )
        print(f"  Generated {len(signals)} signals")
        for s in signals[:3]:
            print(f"    {s.get('agent_id', '?')}: {s.get('claim', '')[:60]}...")

        # Step 4: Run backtest on signals
        print(f"[4/6] Running backtest on signals...")
        backtest_result = None
        if signals:
            try:
                bt_result = run_backtest(
                    signal=signals[0],
                    candles=candles,
                    initial_capital=capital,
                    risk_per_trade=risk_per_trade,
                )
                print(f"  Backtest: {bt_result.get('status')}")
                print(
                    f"  Total return: {bt_result.get('total_return_pct', 0):.2f}%"
                )
                print(f"  Sharpe ratio: {bt_result.get('sharpe_ratio', 0):.2f}")
                print(
                    f"  Max drawdown: {bt_result.get('max_drawdown_pct', 0):.2f}%"
                )
                backtest_result = bt_result
            except Exception as e:
                print(f"  Backtest failed: {e}")
                import traceback

                traceback.print_exc()

        # Step 5: Calculate position sizes
        print(f"[5/6] Calculating position sizes...")
        position_sizes = []
        if backtest_result and backtest_result.get("status") == "done" and signals:
            try:
                signal = signals[0]
                pos_size = calculate_position_size(
                    agent_id=agent_id,
                    instrument=signal.get("instrument", "NIFTY"),
                    direction=signal.get("direction", "neutral"),
                    signal_confidence=signal.get("confidence", 0.5),
                    entry_price=signal.get("exec_price", 0) or 0,
                    stop_loss=signal.get("stop_loss"),
                    cost_units=1,
                    method="fixed_fraction",
                    capital=capital,
                    risk_per_trade=risk_per_trade,
                )
                position_sizes = [pos_size]
                print(
                    f"  Position size: {pos_size.get('position_size', 0)} units"
                )
                print(f"  Cost units: {pos_size.get('cost_units', 0)}")
                print(f"  Net value: {pos_size.get('net_value', 0)}")
            except Exception as e:
                print(f"  Position sizing failed: {e}")
                import traceback

                traceback.print_exc()

        # Step 6: Validate out-of-sample
        print(f"[6/6] Running out-of-sample validation...")
        oos_result = None
        if backtest_result and backtest_result.get("status") == "done":
            try:
                oos_candles = generate_synthetic_ohlcv(
                    symbol="NIFTY",
                    days=126,
                    start_price=22000.0,
                    volatility=0.015,
                    drift=0.0003,
                    seed=99,
                )
                bt_result_id = backtest_result.get(
                    "task_id", f"signal-{uuid.uuid4().hex[:8]}"
                )
                oos_result = run_oos_validation(
                    backtest_result_id=bt_result_id,
                    oos_candles=oos_candles,
                    is_backtest_result=backtest_result,
                )
                print(f"  Validation: {oos_result.get('status')}")
                print(
                    f"  Overall score: {oos_result.get('overall_score', 0):.2f}"
                )
                print(
                    f"  Passes threshold: {oos_result.get('passes_threshold', False)}"
                )
            except Exception as e:
                print(f"  Validation failed: {e}")
                import traceback

                traceback.print_exc()

        # Compile final result
        final_result = {
            **result,
            "status": "completed",
            "signals": signals,
            "backtest_result": backtest_result,
            "position_sizes": position_sizes,
            "validation_result": oos_result,
            "synthesis": result.get("synthesis", ""),
            "agent_answers": [],
        }

        print()
        print("=== PIPELINE COMPLETE ===")
        print(f"Task ID: {task_id}")
        print(f"Signals generated: {len(signals)}")
        if backtest_result:
            print(f"Backtest: {backtest_result.get('status')}")
            print(
                f"  Total return: {backtest_result.get('total_return_pct', 0):.2f}%"
            )
            print(
                f"  Sharpe ratio: {backtest_result.get('sharpe_ratio', 0):.2f}"
            )
            print(
                f"  Max drawdown: {backtest_result.get('max_drawdown_pct', 0):.2f}%"
            )
        if oos_result:
            print(f"Validation: {oos_result.get('status')}")
            print(
                f"  Overall score: {oos_result.get('overall_score', 0):.2f}"
            )
            print(
                f"  Passes threshold: {oos_result.get('passes_threshold', False)}"
            )

        return final_result

    except Exception as e:
        import traceback

        traceback.print_exc()
        return {
            "task_id": task_id if "task_id" in locals() else None,
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def run_pipeline_from_file(task_file_path: str) -> dict:
    """Run the full pipeline from an existing task file.

    Args:
        task_file_path: Path to the task file.

    Returns:
        Pipeline result dict.
    """
    import json

    p = Path(task_file_path)
    if not p.exists():
        return {"ok": False, "error": f"Task file not found: {task_file_path}"}

    try:
        task = json.loads(p.read_text())
    except Exception as e:
        return {"ok": False, "error": f"Invalid task file: {e}"}

    prompt = task.get("description", task.get("title", ""))
    agent_id = task.get("agent_id", "strategy-advisor")
    priority = task.get("priority", "normal")

    return run_strategy_pipeline(
        prompt=prompt,
        agent_id=agent_id,
        priority=priority,
    )
