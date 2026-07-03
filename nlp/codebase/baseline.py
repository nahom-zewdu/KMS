# nlp/codebase/baseline.py
"""
Full baseline syncer for GitHub repositories.
Indexes files, infers modules with importance scoring, creates PART_OF relationships,
and enriches metadata for visualizer needs.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict
from github import Github, GithubException
from supabase import Client

logger = logging.getLogger(__name__)


class CodebaseBaselineSync:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.gh = Github(os.getenv("GITHUB_API_TOKEN"))

    def sync_repository(self, repo_full_name: str) -> bool:
        logger.info(f"Starting full baseline sync for {repo_full_name}")
        try:
            repo = self.gh.get_repo(repo_full_name)

            # 1. Repository record
            repo_data = {
                "full_name": repo_full_name,
                "company_id": "default",
                "description": repo.description or "",
                "language": repo.language,
                "default_branch": repo.default_branch,
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"size": repo.size, "stars": repo.stargazers_count}
            }
            self.supabase.table("repositories").upsert(repo_data, on_conflict="full_name").execute()

            repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_full_name).single().execute()
            repo_id = repo_res.data["id"]

            # 2. Tree walk
            contents = repo.get_contents("")
            files_processed = 0
            module_map = {}  # for importance scoring

            while contents:
                item = contents.pop(0)
                if item.type == "dir":
                    try:
                        contents.extend(repo.get_contents(item.path))
                        module_map[item.path] = module_map.get(item.path, 0) + 1
                    except GithubException:
                        continue
                    continue

                if item.type == "file":
                    self._index_file(item, repo_id, repo_full_name)
                    files_processed += 1

            # 3. Create / update modules with importance
            for mod_path, file_count in module_map.items():
                self._create_module(mod_path, repo_id, file_count)

            logger.info(f"Baseline sync complete: {files_processed} files, {len(module_map)} modules for {repo_full_name}")
            return True

        except Exception as e:
            logger.error(f"Baseline sync failed for {repo_full_name}: {e}", exc_info=True)
            return False

    def _index_file(self, gh_file, repo_id: str, repo_full_name: str):
        """Index single file with module_path and basic importance hint."""
        file_path = gh_file.path
        file_name = file_path.split("/")[-1]
        module_path = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""

        file_data = {
            "repository_id": repo_id,
            "file_path": file_path,
            "file_name": file_name,
            "module_path": module_path,
            "language": self._detect_language(file_path),
            "last_modified_at": datetime.now(timezone.utc).isoformat(),
            "last_commit_sha": gh_file.sha,
            "metadata": {
                "github_sha": gh_file.sha,
                "size": gh_file.size,
                "html_url": gh_file.html_url
            }
        }

        self.supabase.table("codebase_files").upsert(file_data, on_conflict="repository_id,file_path").execute()

        # PART_OF relationship (file → repo)
        self._create_part_of_edge(repo_id, file_path, "FILE", "REPOSITORY")

        logger.debug(f"Indexed file: {file_path} (module: {module_path})")

    def _create_module(self, module_path: str, repo_id: str, file_count: int):
        """Create/update module with computed importance."""
        module_name = module_path.split("/")[-1] if module_path else "root"
        importance = min(1.0, (file_count / 20.0) + 0.3)  # base score from size

        self.supabase.table("codebase_modules").upsert({
            "repository_id": repo_id,
            "module_path": module_path,
            "module_name": module_name,
            "inferred_type": self._infer_module_type(module_path),
            "description": f"Module containing {file_count} files",
            "importance_score": round(importance, 2),
            "metadata": {"file_count": file_count}
        }, on_conflict="repository_id,module_path").execute()

    def _infer_module_type(self, module_path: str) -> str:
        lower = module_path.lower()
        if any(k in lower for k in ["api", "handlers", "routes"]):
            return "api"
        if any(k in lower for k in ["nlp", "engine", "worker"]):
            return "core"
        if any(k in lower for k in ["utils", "common", "helper"]):
            return "utils"
        return "feature"

    def _create_part_of_edge(self, repo_id: str, file_path: str, source_type: str, target_type: str):
        """Create PART_OF relationship."""
        # Simple deterministic ID
        edge_id = f"partof-{repo_id}-{hash(file_path)}"
        self.supabase.table("edges").upsert({
            "id": edge_id,
            "source_id": f"file-{repo_id}-{hash(file_path)}",  # will be improved later with real entity IDs
            "target_id": str(repo_id),
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="id").execute()

    def _detect_language(self, file_path: str) -> str:
        # (your existing mapping - kept as-is)
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {"go": "Go", "py": "Python", "js": "JavaScript", "ts": "TypeScript", "java": "Java",
                   "cpp": "C++", "c": "C", "rs": "Rust", "rb": "Ruby", "php": "PHP", "swift": "Swift",
                   "kt": "Kotlin", "scala": "Scala", "hs": "Haskell", "lua": "Lua", "pl": "Perl",
                   "sh": "Shell", "bash": "Bash", "html": "HTML", "css": "CSS", "json": "JSON",
                   "xml": "XML", "yml": "YAML", "yaml": "YAML", "md": "Markdown", "txt": "Text",
                   "r": "R", "dart": "Dart", "erl": "Erlang", "ex": "Elixir", "exs": "Elixir",
                   "clj": "Clojure", "groovy": "Groovy",
                   "sql": "SQL", "tsv": "TSV", "csv": "CSV", "ini": "INI", "toml": "TOML",
                   "bat": "Batch", "ps1": "PowerShell", "vbs": "VBScript", "f": "Fortran", "f90": "Fortran", 
                   "f95": "Fortran", "f03": "Fortran", "f08": "Fortran", "f77": "Fortran", "f2k": "Fortran",
                   "ada": "Ada", "vhdl": "VHDL", "verilog": "Verilog", "asm": "Assembly", "s": "Assembly",
                   "ml": "OCaml", "mli": "OCaml", "nim": "Nim", "d": "D", "zig": "Zig", "rkt": "Racket", "lisp": "Lisp", "scm": "Scheme",
                   "fsharp": "F#", "fs": "F#", "fsx": "F#", "fsproj": "F#", "elm": "Elm", "purescript": "PureScript", "julia": "Julia",
                   }
        return mapping.get(ext, "Unknown")