import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from engine import ner, re
from utils import db_helpers


class FailingTable:
    def upsert(self, *args, **kwargs):
        return self

    def insert(self, *args, **kwargs):
        return self

    def execute(self):
        raise RuntimeError("database unavailable")


class FailingSupabase:
    def table(self, _name):
        return FailingTable()


class FallbackTable:
    def upsert(self, *args, **kwargs):
        raise RuntimeError("upsert unavailable")

    def insert(self, *args, **kwargs):
        return self

    def execute(self):
        return object()


class FallbackSupabase:
    def table(self, _name):
        return FallbackTable()


class FailureSemanticsTests(unittest.TestCase):
    def test_supabase_write_failure_propagates(self):
        with self.assertRaisesRegex(RuntimeError, "entity persistence failed"):
            db_helpers.insert_entities(FailingSupabase(), [{"id": "1"}])

    def test_successful_entity_fallback_is_success(self):
        db_helpers.insert_entities(FallbackSupabase(), [{"id": "1"}])


    def test_embedding_failure_propagates(self):
        original = db_helpers.embed_content
        db_helpers.embed_content = lambda _content: (_ for _ in ()).throw(RuntimeError("embed"))
        self.addCleanup(setattr, db_helpers, "embed_content", original)
        with self.assertRaisesRegex(RuntimeError, "embedding generation failed"):
            db_helpers.insert_raw_data(FailingSupabase(), {"record_id": "r1", "content": "text"})


    def test_ner_llm_failure_propagates(self):
        original = ner.llm_infer
        ner.llm_infer = lambda _prompt: (_ for _ in ()).throw(RuntimeError("llm"))
        self.addCleanup(setattr, ner, "llm_infer", original)
        with self.assertRaisesRegex(RuntimeError, "NER processing failed"):
            ner.extract_entities("text", "r1", "slack", "now")


    def test_ner_malformed_response_propagates(self):
        original = ner.llm_infer
        ner.llm_infer = lambda _prompt: '{"entities": {}}'
        self.addCleanup(setattr, ner, "llm_infer", original)
        with self.assertRaisesRegex(ValueError, "entities must be a list"):
            ner.extract_entities("text", "r1", "slack", "now")


    def test_valid_empty_ner_extraction_succeeds(self):
        original = ner.llm_infer
        ner.llm_infer = lambda _prompt: '{"entities": []}'
        self.addCleanup(setattr, ner, "llm_infer", original)
        self.assertEqual(ner.extract_entities("text", "r1", "slack", "now"), [])


    def test_relation_llm_failure_propagates(self):
        original = re.llm_infer
        re.llm_infer = lambda _prompt: (_ for _ in ()).throw(RuntimeError("llm"))
        self.addCleanup(setattr, re, "llm_infer", original)
        with self.assertRaisesRegex(RuntimeError, "relation extraction failed"):
            re.extract_relations("text", [{"text": "alice", "type": "PERSON"}], "r1", "now")


    def test_relation_malformed_response_propagates(self):
        original = re.llm_infer
        re.llm_infer = lambda _prompt: '{"relations": {}}'
        self.addCleanup(setattr, re, "llm_infer", original)
        with self.assertRaisesRegex(ValueError, "invalid relation extraction response"):
            re.extract_relations("text", [{"text": "alice", "type": "PERSON"}], "r1", "now")


if __name__ == "__main__":
    unittest.main()