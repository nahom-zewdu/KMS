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
