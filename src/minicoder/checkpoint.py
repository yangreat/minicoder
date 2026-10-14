"""Git-based checkpoints for workspace state."""

from pathlib import Path
from typing import Any

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError


class CheckpointManager:
    """Manage git-based checkpoints."""

    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)
        try:
            self.repo = Repo(self.repo_path)
        except (InvalidGitRepositoryError, Exception):
            self.repo = Repo.init(self.repo_path)
        self._ensure_identity()
        self._ensure_gitignore()

    def _ensure_gitignore(self) -> None:
        """Keep MiniCoder internals out of checkpoint diffs."""
        gi = self.repo_path / ".gitignore"
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        extra = ""
        if ".minicoder/" not in existing:
            extra += ".minicoder/\n"
        if "*.db" not in existing:
            extra += "*.db\n"
        if extra:
            prefix = "" if not existing or existing.endswith("\n") else "\n"
            gi.write_text(existing + prefix + extra, encoding="utf-8")

    def _ensure_identity(self) -> None:
        """Set a local git identity so commits work in CI/demo."""
        with self.repo.config_writer() as writer:
            writer.set_value("user", "name", "MiniCoder")
            writer.set_value("user", "email", "minicoder@localhost")

    def create_checkpoint(
        self, run_id: str, step: int, message: str = "", allow_empty: bool = False
    ) -> str:
        """Create a checkpoint of current state."""
        try:
            self.repo.git.add(A=True)
            try:
                self.repo.git.rm("-r", "--cached", "--ignore-unmatch", ".minicoder")
            except GitCommandError:
                pass

            checkpoint_msg = f"[MiniCoder] Run {run_id} - Step {step}"
            if message:
                checkpoint_msg += f": {message}"

            if allow_empty:
                self.repo.git.commit("--allow-empty", "-m", checkpoint_msg)
                return str(self.repo.head.commit.hexsha)

            try:
                if self.repo.head.is_valid() and not self.repo.index.diff("HEAD"):
                    untracked = list(self.repo.untracked_files)
                    if not untracked:
                        return str(self.repo.head.commit.hexsha)
            except Exception:
                pass

            commit = self.repo.index.commit(checkpoint_msg)
            return str(commit.hexsha)

        except GitCommandError as e:
            raise RuntimeError(f"Failed to create checkpoint: {e}") from e

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """List all checkpoints for a run (newest first)."""
        checkpoints: list[dict[str, Any]] = []

        try:
            for commit in self.repo.iter_commits():
                if f"Run {run_id}" in commit.message:
                    checkpoints.append(
                        {
                            "sha": commit.hexsha[:8],
                            "full_sha": commit.hexsha,
                            "message": commit.message.strip(),
                            "timestamp": commit.committed_datetime.isoformat(),
                        }
                    )
        except Exception:
            pass

        return checkpoints

    def rollback(self, checkpoint_sha: str) -> None:
        """Rollback to a checkpoint."""
        try:
            self.repo.git.reset("--hard", checkpoint_sha)
        except GitCommandError as e:
            raise RuntimeError(f"Failed to rollback: {e}") from e

    def get_current_sha(self) -> str | None:
        """Get current commit SHA."""
        try:
            if self.repo.head.is_valid():
                return str(self.repo.head.commit.hexsha)
        except Exception:
            pass
        return None

    def has_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        return self.repo.is_dirty() or len(self.repo.untracked_files) > 0

    def get_diff(self, from_sha: str | None = None, to_sha: str | None = None) -> str:
        """Get diff between two commits or against working tree."""
        try:
            if from_sha and to_sha:
                return str(self.repo.git.diff(from_sha, to_sha))
            elif from_sha:
                staged = str(self.repo.git.diff(from_sha, "HEAD"))
                dirty = str(self.repo.git.diff(from_sha))
                return staged or dirty
            else:
                return str(self.repo.git.diff("HEAD")) or str(self.repo.git.diff())
        except GitCommandError as e:
            return f"Error getting diff: {e}"

    def get_run_diff(self, run_id: str) -> str:
        """Diff since the first checkpoint of this run (the baseline)."""
        checkpoints = self.list_checkpoints(run_id)
        if not checkpoints:
            return self.get_diff()
        baseline = checkpoints[-1]["full_sha"]
        return self.get_diff(from_sha=baseline)
