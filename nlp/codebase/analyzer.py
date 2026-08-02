# nlp/codebase/analyzer.py
"""
Codebase Analyzer for incremental GitHub push events.
Creates FILE entities, codebase_files records, PART_OF edges, and OWNS relationships
from commit authors.
Fully consistent with baseline sync.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timezone
import uuid

from supabase import Client

logger = logging.getLogger(__name__)


class CodebaseAnalyzer:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def process_push_event(self, payload: Dict[str, Any], record_id: str, company_id: str = "default") -> bool:
        """Process incremental push event."""
        logger.info(f"Incremental push processing | record={record_id}")

        try:
            repo_name = self._extract_repo_name(payload)
            files = payload.get("files", {})
            changed_files = files.get("added", []) + files.get("modified", [])

            for file_path in changed_files[:60]:
                if file_path and not file_path.startswith("."):
                    await self._upsert_file(file_path, repo_name, record_id, payload, company_id)

            logger.info(f"Incremental update completed: {len(changed_files)} files for {repo_name}")
            return True
        except Exception as e:
            logger.error(f"Incremental push failed for {record_id}: {e}", exc_info=True)
            return False

    def _extract_repo_name(self, payload: Dict) -> str:
        """Safely extract repository full name."""
        repo = payload.get("repository")
        if isinstance(repo, dict):
            return repo.get("full_name") or repo.get("name", "unknown-repo")
        return str(payload.get("repo") or repo or "unknown-repo")

    async def _upsert_file(self, file_path: str, repo_name: str, record_id: str, payload: Dict, company_id: str = "default"):
        """Create FILE entity + codebase_files + PART_OF + OWNS edges."""
        file_name = file_path.split("/")[-1]
        module_path = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""

        # REPOSITORY entity (ensure exists)
        repo_entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"repo:{repo_name}"))
        self.supabase.table("entities").upsert({
            "id": repo_entity_id,
            "type": "REPOSITORY",
            "name": repo_name,
            "metadata": {"source": "github_push", "company_id": company_id},
            "created_at": datetime.now(timezone.utc).isoformat()
        }, on_conflict="id").execute()

        # FILE entity
        file_entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"file:{repo_name}:{file_path}"))
        self.supabase.table("entities").upsert({
            "id": file_entity_id,
            "type": "FILE",
            "name": file_name,
            "file_path": file_path,
            "language": self._detect_language(file_path),
            "metadata": {"module_path": module_path, "source_record_id": record_id, "company_id": company_id},
            "created_at": datetime.now(timezone.utc).isoformat()
        }, on_conflict="id").execute()

        # Physical repo record
        repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_name).single().execute()
        if not repo_res.data:
            self.supabase.table("repositories").upsert({
                "full_name": repo_name,
                "company_id": company_id,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, on_conflict="full_name").execute()
            repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_name).single().execute()

        physical_repo_id = repo_res.data["id"]

        # codebase_files
        file_data = {
            "repository_id": physical_repo_id,
            "file_path": file_path,
            "file_name": file_name,
            "module_path": module_path,
            "language": self._detect_language(file_path),
            "last_modified_at": datetime.now(timezone.utc).isoformat(),
            "last_commit_sha": payload.get("head_commit", {}).get("id"),
            "last_author": payload.get("sender"),
            "metadata": {"source_record_id": record_id, "company_id": company_id}
        }
        self.supabase.table("codebase_files").upsert(file_data, on_conflict="repository_id,file_path").execute()

        # PART_OF edge
        edge_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"partof:{file_entity_id}:{repo_entity_id}"))
        self.supabase.table("edges").upsert({
            "id": edge_id,
            "source_id": file_entity_id,
            "target_id": repo_entity_id,
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_record_id": record_id,
            "company_id": company_id
        }, on_conflict="id").execute()

        # OWNS edge from last author (if available)
        author = payload.get("sender") or payload.get("last_author")
        if author:
            person_entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"person:{author}"))
            self.supabase.table("entities").upsert({
                "id": person_entity_id,
                "type": "PERSON",
                "name": author,
                "metadata": {"source": "github_commit", "company_id": company_id},
                "created_at": datetime.now(timezone.utc).isoformat()
            }, on_conflict="id").execute()

            owns_edge_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"owns:{person_entity_id}:{file_entity_id}"))
            self.supabase.table("edges").upsert({
                "id": owns_edge_id,
                "source_id": person_entity_id,
                "target_id": file_entity_id,
                "type": "OWNS",
                "confidence": 0.85,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_record_id": record_id,
                "company_id": company_id
            }, on_conflict="id").execute()

        logger.debug(f"Updated file with ownership: {file_path}")

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
