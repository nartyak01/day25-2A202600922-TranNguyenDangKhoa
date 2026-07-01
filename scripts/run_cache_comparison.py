"""Compare chaos metrics with cache enabled vs disabled (all_healthy scenario)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reliability_lab.chaos import load_queries, run_scenario
from reliability_lab.config import LabConfig, ScenarioConfig, load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out", default="reports/cache_comparison.json")
    args = parser.parse_args()

    config = load_config(args.config)
    queries = load_queries()
    scenario = ScenarioConfig(name="all_healthy", description="cache comparison baseline", provider_overrides={})

    without_cache = config.model_copy(deep=True)
    without_cache.cache.enabled = False
    without_metrics = run_scenario(without_cache, queries, scenario)

    with_cache = config.model_copy(deep=True)
    with_cache.cache.enabled = True
    with_metrics = run_scenario(with_cache, queries, scenario)

    comparison = {
        "scenario": scenario.name,
        "requests_per_run": config.load_test.requests,
        "without_cache": without_metrics.to_report_dict(),
        "with_cache": with_metrics.to_report_dict(),
        "delta": {
            "latency_p50_ms": round(
                with_metrics.percentile(50) - without_metrics.percentile(50), 2
            ),
            "latency_p95_ms": round(
                with_metrics.percentile(95) - without_metrics.percentile(95), 2
            ),
            "estimated_cost": round(
                with_metrics.estimated_cost - without_metrics.estimated_cost, 6
            ),
            "cache_hit_rate": round(with_metrics.cache_hit_rate, 4),
        },
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(comparison, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
