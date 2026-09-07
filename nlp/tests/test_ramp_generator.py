import uuid
from unittest.mock import Mock

from ramp.generator import RampPlanGenerator


class TestRampGeneratorQuality:
    def setup_method(self):
        self.generator = RampPlanGenerator(supabase=Mock())

    def _build_steps(self, modules, key_files=None, owner_index=None, architecture=None):
        return self.generator._build_steps(
            role="backend",
            company_id="company-123",
            modules=modules,
            key_files=key_files or [],
            owner_index=owner_index or {},
            safe_paths=set(),
            risk_paths=set(),
            architecture=architecture or [{"name": "API Layer", "description": "API services"}],
        )

    def test_evidence_backed_why_generation(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "handlers",
                    "path": "api/handlers",
                    "description": "HTTP request handling for the backend API.",
                    "importance": 0.9,
                    "file_count": 4,
                }
            ],
            key_files=[
                {"path": "api/handlers/tenant.py", "module": "api/handlers", "last_author": "alice"},
                {"path": "api/handlers/routes.py", "module": "api/handlers", "last_author": "bob"},
            ],
            owner_index={"api/handlers": ["alice"]},
        )

        step = steps[0]
        why = step["why"]
        assert "api/handlers" in why
        assert "this repo" in why.lower() or "specific" in why.lower()
        assert "owner" in why.lower() or "evidence" in why.lower()
        assert any(ev.get("kind") == "observed" for ev in step["evidence"])

    def test_context_generation_is_specific_and_understandable(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "handlers",
                    "path": "api/handlers",
                    "description": "HTTP request handling for the backend API.",
                    "importance": 0.9,
                    "file_count": 3,
                }
            ],
            key_files=[{"path": "api/handlers/tenant.py", "module": "api/handlers"}],
            owner_index={"api/handlers": ["alice"]},
            architecture=[{"name": "API Layer", "description": "API services"}],
        )

        step = steps[0]
        assert "understand" in step
        assert "api/handlers" in step["understand"]
        assert "HTTP" in step["understand"] or "request" in step["understand"].lower()
        assert step["summary"]["what"]
        assert step["summary"]["where"]
