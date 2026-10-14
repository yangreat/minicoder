"""Git-based checkpoints for workspace state."""

from pathlib import Path

from git import Repo
from git.exc import GitCommandError


class CheckpointManager:
    """Manage git-based checkpoints."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        try:
            self.repo = Repo(repo_path)
        except Exception:
            self.repo = Repo.init(repo_path)

    def create_checkpoint(self, run_id: str, step: int, message: str = "") -> str:
        """Create a checkpoint of current state."""
        try:
            self.repo.git.add(A=True)

            try:
                if not self.repo.index.diff("HEAD"):
                    return self.repo.head.commit.hexsha
            except Exception:
                pass

            checkpoint_msg = f"[MiniCoder] Run {run_id} - Step {step}"
            if message:
                checkpoint_msg += f": {message}"

            commit = self.repo.index.commit(checkpoint_msg)
            return commit.hexsha

        except GitCommandError as e:
            raise RuntimeError(f"Failed to create checkpoint: {e}")

    def list_checkpoints(self, run_id: str) -> list[dict]:
        """List all checkpoints for a run."""
        checkpoints = []

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
            raise RuntimeError(f"Failed to rollback: {e}")

    def get_current_sha(self) -> str | None:
        """Get current commit SHA."""
        try:
            if self.repo.head.is_valid():
                return self.repo.head.commit.hexsha
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
                return self.repo.git.diff(from_sha, to_sha)
            elif from_sha:
                return self.repo.git.diff(from_sha)
            else:
                return self.repo.git.diff()
        except GitCommandError as e:
            return f"Error getting diff: {e}"
