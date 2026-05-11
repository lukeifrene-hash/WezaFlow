from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    repo_root: Path
    config_dir: Path
    db_dir: Path
    scripts_dir: Path
    services_dir: Path
    artifacts_dir: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "ProjectPaths":
        root = repo_root.resolve()
        return cls(
            repo_root=root,
            config_dir=root / "config",
            db_dir=root / "db",
            scripts_dir=root / "scripts",
            services_dir=root / "services",
            artifacts_dir=root / "artifacts",
        )

    @classmethod
    def discover(cls, start: Path | None = None) -> "ProjectPaths":
        current = (start or Path.cwd()).resolve()
        for candidate in (current, *current.parents):
            if (candidate / "pyproject.toml").exists() and (candidate / "services").exists():
                return cls.from_repo_root(candidate)
        raise FileNotFoundError("Could not find the LocalFlow repository root")
