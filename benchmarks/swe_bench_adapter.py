"""SWE-bench Lite adapter for MiniCoder."""

import json
from pathlib import Path
from typing import List, Dict


def load_swe_bench_lite(
    dataset_path: Path, max_instances: int = 10
) -> List[Dict[str, str]]:
    """Load a subset of SWE-bench Lite instances."""
    if not dataset_path.exists():
        print(f"SWE-bench Lite dataset not found at {dataset_path}")
        print("To use SWE-bench Lite:")
        print("1. Download from https://github.com/princeton-nlp/SWE-bench")
        print("2. Place lite_dataset.json in benchmarks/swe_bench/")
        return []

    with open(dataset_path) as f:
        instances = json.load(f)

    return instances[:max_instances]


def convert_to_minicoder_task(instance: Dict) -> Dict[str, str]:
    """Convert SWE-bench instance to MiniCoder task format."""
    task = f"""
Repository: {instance.get('repo', 'unknown')}
Issue: {instance.get('problem_statement', '')}

Your task is to fix the issue described above.
Make changes to the codebase to resolve the problem and ensure all tests pass.
"""

    return {
        "name": instance.get("instance_id", "unknown"),
        "task": task.strip(),
        "repo": instance.get("repo", ""),
        "base_commit": instance.get("base_commit", ""),
    }


if __name__ == "__main__":
    print("SWE-bench Lite adapter for MiniCoder")
    print("\nTo run on SWE-bench Lite:")
    print("1. Download the dataset")
    print("2. Set up repositories at the correct commits")
    print("3. Run: python -m benchmarks.swe_bench_adapter")
