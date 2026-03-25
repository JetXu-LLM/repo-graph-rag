from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Optional

from repo_knowledge_graph import RepoKnowledgeGraph

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional for public mainline
    load_dotenv = None


def _load_default_env() -> None:
    if load_dotenv is None:
        return
    default_env_path = Path(__file__).resolve().parents[1] / ".env"
    if default_env_path.exists():
        load_dotenv(default_env_path)
    else:
        load_dotenv()


def _configure_logging(log_level: str) -> None:
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if logger.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy full-build Arango path for repo-graph-rag. "
            "Incremental update support was intentionally removed from the public surface."
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository in owner/name format.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="ArangoDB database name. Defaults to a sanitized repository name.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="ArangoDB host. Defaults to ARANGODB_HOST or http://localhost:8529.",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="ArangoDB username. Defaults to ARANGODB_USERNAME or root.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="ArangoDB password. Defaults to ARANGODB_PASSWORD.",
    )
    parser.add_argument(
        "--reset-collections",
        action="store_true",
        help="Explicitly drop and recreate graph collections before a full build.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level. Defaults to INFO.",
    )
    return parser


def _require_github_rag():
    try:
        from llama_github import GithubRAG
    except ImportError as exc:  # pragma: no cover - depends on legacy environment
        raise RuntimeError(
            "The legacy Arango build path requires llama-github. "
            "Install repo_kg_maintainer/requirements-legacy.txt to use main.py."
        ) from exc
    return GithubRAG


def _load_repo_structure(repo, attempts: int = 3, delay_seconds: int = 2):
    for attempt in range(1, attempts + 1):
        try:
            return repo.get_structure()
        except Exception as exc:
            if attempt == attempts:
                raise RuntimeError(
                    "Failed to fetch repository structure from GitHub after retries. "
                    "This is usually a transient GitHub API or network issue."
                ) from exc
            logging.getLogger(__name__).warning(
                "Fetching repository structure failed on attempt %s/%s: %s. Retrying...",
                attempt,
                attempts,
                exc,
            )
            time.sleep(delay_seconds)


def main(argv: Optional[list[str]] = None) -> None:
    _load_default_env()
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.log_level)

    GithubRAG = _require_github_rag()

    github_token = os.environ.get("GITHUB_ACCESS_TOKEN")
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    huggingface_token = os.environ.get("HUGGINGFACE_TOKEN")

    arangodb_host = args.host or os.environ.get("ARANGODB_HOST", "http://localhost:8529")
    arangodb_username = args.username or os.environ.get("ARANGODB_USERNAME", "root")
    arangodb_password = args.password or os.environ.get("ARANGODB_PASSWORD")

    github_rag = GithubRAG(
        github_access_token=github_token,
        mistral_api_key=mistral_key,
        huggingface_token=huggingface_token,
        simple_mode=True,
    )

    repo = github_rag.RepositoryPool.get_repository(args.repo)
    repo_structure = _load_repo_structure(repo)
    database_name = args.database or re.sub(r"[^a-zA-Z0-9_-]", "_", repo.full_name)

    if args.reset_collections:
        logging.getLogger(__name__).warning(
            "reset-collections is enabled; existing legacy graph collections will be recreated."
        )

    kg = RepoKnowledgeGraph(
        repo=repo,
        host=arangodb_host,
        database=database_name,
        username=arangodb_username,
        password=arangodb_password,
        reset_collections=args.reset_collections,
    )
    kg.build_knowledge_graph(repo.full_name, repo_structure)


if __name__ == "__main__":
    main()
