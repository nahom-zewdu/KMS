# nlp/codebase/baseline.py
"""
Full baseline syncer for GitHub repositories.
This module performs a complete traversal of the repository tree, indexing files and modules.
It creates REPOSITORY entities, FILE entities, and PART_OF relationships in the knowledge graph,
and populates the codebase_files and codebase_modules tables in Supabase.
The sync is designed to be idempotent and can be re-run safely.
The main entry point is the `sync_repository` method, which takes a repository full name
Creates REPOSITORY entity + codebase_files + PART_OF edges safely.  
"""

import logging
import os
from datetime import datetime, timezone
import uuid
from typing import Dict

from github import Github, GithubException
from supabase import Client

logger = logging.getLogger(__name__)


class CodebaseBaselineSync:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.gh = Github(os.getenv("GITHUB_API_TOKEN"))

    def sync_repository(self, repo_full_name: str, company_id: str = "default") -> bool:
        """Perform a full baseline sync for the given repository."""
        logger.info(f"Starting full baseline sync for {repo_full_name} | company={company_id}")
        try:
            repo = self.gh.get_repo(repo_full_name)
            now = datetime.now(timezone.utc).isoformat()

            # 1. REPOSITORY entity (tenant-scoped id)
            repo_entity_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"repo:{company_id}:{repo_full_name}")
            )
            self.supabase.table("entities").upsert(
                {
                    "id": repo_entity_id,
                    "type": "REPOSITORY",
                    "name": repo_full_name,
                    "company_id": company_id,
                    "metadata": {
                        "description": repo.description or "",
                        "language": repo.language,
                        "default_branch": repo.default_branch,
                        "company_id": company_id,
                    },
                    "created_at": now,
                },
                on_conflict="id",
            ).execute()

            # 2. repositories table
            existing = (
                self.supabase.table("repositories")
                .select("id")
                .eq("full_name", repo_full_name)
                .eq("company_id", company_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                physical_repo_id = existing.data[0]["id"]
                self.supabase.table("repositories").update(
                    {
                        "description": repo.description or "",
                        "language": repo.language,
                        "default_branch": repo.default_branch,
                        "last_synced_at": now,
                        "updated_at": now,
                    }
                ).eq("id", physical_repo_id).execute()
            else:
                physical_repo_id = str(uuid.uuid4())
                self.supabase.table("repositories").insert(
                    {
                        "id": physical_repo_id,
                        "full_name": repo_full_name,
                        "company_id": company_id,
                        "description": repo.description or "",
                        "language": repo.language,
                        "default_branch": repo.default_branch,
                        "last_synced_at": now,
                        "updated_at": now,
                    }
                ).execute()

            # 3. Tree walk
            contents = repo.get_contents("")
            files_processed = 0
            module_map: Dict[str, int] = {}

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
                    self._index_file(
                        item,
                        repo_entity_id,
                        physical_repo_id,
                        repo_full_name,
                        company_id,
                    )
                    files_processed += 1

            for mod_path, file_count in module_map.items():
                self._create_module(mod_path, physical_repo_id, file_count)

            logger.info(
                f"Baseline sync complete: {files_processed} files, "
                f"{len(module_map)} modules | company={company_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Baseline sync failed: {e}", exc_info=True)
            return False
    
    def _index_file(self, gh_file, repo_entity_id: str, physical_repo_id: str, repo_full_name: str, company_id: str = "default",):
        """Index a single file: create FILE entity, codebase_files entry, and PART_OF edge."""
        file_path = gh_file.path
        file_name = file_path.split("/")[-1]
        module_path = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""
        now = datetime.now(timezone.utc).isoformat()

        file_entity_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"file:{company_id}:{repo_full_name}:{file_path}")
        )
        self.supabase.table("entities").upsert(
            {
                "id": file_entity_id,
                "type": "FILE",
                "file_path": file_path,
                "module_path": module_path,
                "language": self._detect_language(file_path),
                "name": file_name,
                "metadata": {
                "company_id": company_id,
                },
                "created_at": now,
                "company_id": company_id,
            },
            on_conflict="id",
        ).execute()

        self.supabase.table("codebase_files").upsert(
            {
                "repository_id": physical_repo_id,
                "file_path": file_path,
                "file_name": file_name,
                "module_path": module_path,
                "language": self._detect_language(file_path),
                "last_modified_at": now,
                "last_commit_sha": gh_file.sha,
                "metadata": {"company_id": company_id},
            },
            on_conflict="repository_id,file_path",
        ).execute()

        edge_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"partof:{file_entity_id}:{repo_entity_id}")
        )
        self.supabase.table("edges").upsert(
            {
                "id": edge_id,
                "source_id": file_entity_id,
                "target_id": repo_entity_id,
                "type": "PART_OF",
                "confidence": 1.0,
                "created_at": now,
                "company_id": company_id,
            },
            on_conflict="id",
        ).execute()

    def _create_module(self, module_path: str, repo_id: str, file_count: int):
        """Create/update module with computed importance."""
        module_name = module_path.split("/")[-1] if module_path else "root"
        importance = min(1.0, (file_count / 20.0) + 0.3)

        self.supabase.table("codebase_modules").upsert({
            "repository_id": repo_id,
            "module_path": module_path,
            "module_name": module_name,
            "inferred_type": self._infer_module_type(module_path),
            "description": f"Module containing {file_count} files",
            "importance_score": round(importance, 2),
            "metadata": {"file_count": file_count}
        }, on_conflict="repository_id,module_path").execute()

    def _create_part_of_edge(self, repo_id: str, file_path: str):
        """Create deterministic PART_OF edge using UUID."""
        # Use deterministic UUID based on repo + file_path
        edge_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"partof:{repo_id}:{file_path}"))
        file_entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"file:{repo_id}:{file_path}"))

        self.supabase.table("edges").upsert({
            "id": edge_id,
            "source_id": file_entity_id,
            "target_id": repo_id,
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="id").execute()

    def _infer_module_type(self, module_path: str) -> str:
        lower = module_path.lower()
        if any(k in lower for k in ["api", "handlers", "routes"]): return "api"
        if any(k in lower for k in ["nlp", "engine", "worker"]): return "core"
        if any(k in lower for k in ["utils", "common", "helper"]): return "utils"
        return "feature"

    def _detect_language(self, file_path: str) -> str:
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
