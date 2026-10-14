"""Evaluation framework for MiniCoder."""

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class BenchmarkResult:
    """Result of running a benchmark."""

    name: str
    success: bool
    steps: int
    tokens: int
    error: Optional[str] = None
    tests_passed: bool = False


class Evaluator:
    """Evaluate agent performance on benchmarks."""

    def __init__(self, benchmarks_dir: Path, output_dir: Path):
        self.benchmarks_dir = benchmarks_dir
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_toy_benchmarks(self) -> List[Dict[str, str]]:
        """Get toy benchmark repositories."""
        toy_repos = self.benchmarks_dir / "toy_repos"
        benchmarks = []

        for repo_dir in toy_repos.iterdir():
            if repo_dir.is_dir() and (repo_dir / "README.md").exists():
                benchmarks.append(
                    {
                        "name": repo_dir.name,
                        "path": str(repo_dir),
                        "task": f"Fix the bug in this repository. Read README.md for context and make all tests pass.",
                    }
                )

        return benchmarks

    async def run_benchmark(
        self, name: str, path: str, task: str, use_mock: bool = True
    ) -> BenchmarkResult:
        """Run a single benchmark."""
        console.print(f"\n[bold cyan]Running benchmark: {name}[/bold cyan]")

        try:
            cmd = [
                sys.executable,
                "-m",
                "minicoder.cli",
                "run",
                task,
                "--repo",
                path,
                "--max-steps",
                "10",
            ]

            if not use_mock:
                cmd.extend(["--model", "gpt-4"])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            success = result.returncode == 0

            tests_passed = self._check_tests(path)

            steps = 0
            tokens = 0
            if "Steps:" in result.stdout:
                try:
                    steps = int(result.stdout.split("Steps:")[1].split()[0])
                except:
                    pass
            if "Tokens:" in result.stdout:
                try:
                    tokens = int(result.stdout.split("Tokens:")[1].split()[0])
                except:
                    pass

            return BenchmarkResult(
                name=name,
                success=success,
                steps=steps,
                tokens=tokens,
                tests_passed=tests_passed,
                error=None if success else result.stderr,
            )

        except subprocess.TimeoutExpired:
            return BenchmarkResult(
                name=name, success=False, steps=0, tokens=0, error="Timeout"
            )
        except Exception as e:
            return BenchmarkResult(
                name=name, success=False, steps=0, tokens=0, error=str(e)
            )

    def _check_tests(self, repo_path: str) -> bool:
        """Check if tests pass in the repository."""
        try:
            result = subprocess.run(
                ["pytest", "-v"],
                cwd=repo_path,
                capture_output=True,
                timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def run_all_benchmarks(
        self, use_mock: bool = True
    ) -> Dict[str, BenchmarkResult]:
        """Run all benchmarks."""
        benchmarks = self.get_toy_benchmarks()
        results = {}

        console.print(f"[bold]Running {len(benchmarks)} benchmarks[/bold]")

        for bench in benchmarks:
            result = await self.run_benchmark(
                bench["name"], bench["path"], bench["task"], use_mock
            )
            results[bench["name"]] = result

        return results

    def generate_report(self, results: Dict[str, BenchmarkResult]) -> None:
        """Generate evaluation report."""
        table = Table(title="Evaluation Results")
        table.add_column("Benchmark", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Tests", style="yellow")
        table.add_column("Steps", justify="right", style="green")
        table.add_column("Tokens", justify="right", style="blue")

        total = len(results)
        passed = sum(1 for r in results.values() if r.tests_passed)
        total_steps = sum(r.steps for r in results.values())
        total_tokens = sum(r.tokens for r in results.values())

        for name, result in results.items():
            status = "✓" if result.success else "✗"
            tests = "✓" if result.tests_passed else "✗"

            table.add_row(
                name, status, tests, str(result.steps), str(result.tokens)
            )

        console.print(table)
        console.print(f"\n[bold]Pass Rate:[/bold] {passed}/{total} ({passed/total*100:.1f}%)")
        console.print(f"[bold]Total Steps:[/bold] {total_steps}")
        console.print(f"[bold]Total Tokens:[/bold] {total_tokens}")

        report_path = self.output_dir / "results.json"
        report_data = {
            "summary": {
                "total": total,
                "passed": passed,
                "pass_rate": passed / total if total > 0 else 0,
                "total_steps": total_steps,
                "total_tokens": total_tokens,
            },
            "benchmarks": {
                name: {
                    "success": r.success,
                    "tests_passed": r.tests_passed,
                    "steps": r.steps,
                    "tokens": r.tokens,
                    "error": r.error,
                }
                for name, r in results.items()
            },
        }

        report_path.write_text(json.dumps(report_data, indent=2))
        console.print(f"\n[bold green]Report saved to {report_path}[/bold green]")


async def main() -> None:
    """Run evaluation."""
    benchmarks_dir = Path(__file__).parent
    output_dir = benchmarks_dir / "results"

    evaluator = Evaluator(benchmarks_dir, output_dir)

    console.print("[bold blue]MiniCoder Evaluation[/bold blue]")
    console.print("Using mock LLM for testing")

    results = await evaluator.run_all_benchmarks(use_mock=True)
    evaluator.generate_report(results)


if __name__ == "__main__":
    asyncio.run(main())
