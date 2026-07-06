# nlp/codebase/analyzer.py
"""
Codebase Analyzer for incremental GitHub push events.
Processes changed files, creates FILE entities in the knowledge graph,
populates codebase_files, and establishes PART_OF relationships.
Ensures consistency with baseline sync.
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

    async def process_push_event(self, payload: Dict[str, Any], record_id: str):
        """Process incremental push event from GitHub."""
        logger.info(f"Incremental push processing | record={record_id}")

        try:
            repo_name = self._extract_repo_name(payload)
            files = payload.get("files", {})
            changed_files = files.get("added", []) + files.get("modified", [])

            for file_path in changed_files[:60]:
                if file_path and not file_path.startswith("."):
                    await self._upsert_file(file_path, repo_name, record_id, payload)

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

    async def _upsert_file(self, file_path: str, repo_name: str, record_id: str, payload: Dict):
        """Create FILE entity + codebase_files record + PART_OF edge."""
        file_name = file_path.split("/")[-1]
        module_path = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""

        # 1. Create FILE entity (required for edges FK)
        file_entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"file:{repo_name}:{file_path}"))
        self.supabase.table("entities").upsert({
            "id": file_entity_id,
            "type": "FILE",
            "name": file_name,
            "file_path": file_path,
            "language": self._detect_language(file_path),
            "metadata": {
                "module_path": module_path,
                "source_record_id": record_id
            },
            "created_at": datetime.now(timezone.utc).isoformat()
        }, on_conflict="id").execute()

        # 2. Ensure repository exists and get physical ID
        repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_name).single().execute()
        if not repo_res.data:
            # Fallback create
            self.supabase.table("repositories").upsert({
                "full_name": repo_name,
                "company_id": "default",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, on_conflict="full_name").execute()
            repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_name).single().execute()

        physical_repo_id = repo_res.data["id"]

        # 3. codebase_files record
        file_data = {
            "repository_id": physical_repo_id,
            "file_path": file_path,
            "file_name": file_name,
            "module_path": module_path,
            "language": self._detect_language(file_path),
            "last_modified_at": datetime.now(timezone.utc).isoformat(),
            "last_commit_sha": payload.get("head_commit", {}).get("id"),
            "last_author": payload.get("sender"),
            "metadata": {"source_record_id": record_id}
        }
        self.supabase.table("codebase_files").upsert(file_data, on_conflict="repository_id,file_path").execute()

        # 4. PART_OF edge: FILE → REPOSITORY
        edge_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"partof:{file_entity_id}:{physical_repo_id}"))
        self.supabase.table("edges").upsert({
            "id": edge_id,
            "source_id": file_entity_id,
            "target_id": repo_res.data.get("id"),  # Use physical repo if needed, but prefer entity
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_record_id": record_id
        }, on_conflict="id").execute()

        logger.debug(f"Updated incremental file: {file_path}")

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
