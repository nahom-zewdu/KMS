import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from utils import db_helpers


class TenantAwareQuery:
    def __init__(self, database, table, operation, values=None):
        self.database = database
        self.table_name = table
        self.operation = operation
        self.values = values
        self.filters = []
        self.limit_value = None

    def select(self, *_fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def update(self, values):
        self.operation = "update"
        self.values = values
        return self

    def insert(self, values):
        self.operation = "insert"
        self.values = values
        return self

    def execute(self):
        rows = self.database.rows.setdefault(self.table_name, [])
        if self.operation == "select":
            matches = [row for row in rows if all(row.get(k) == v for k, v in self.filters)]
            return SimpleNamespace(data=[dict(row) for row in matches[:self.limit_value]])
        if self.operation == "update":
            matches = [row for row in rows if all(row.get(k) == v for k, v in self.filters)]
            for row in matches:
                row.update(self.values)
            return SimpleNamespace(data=[dict(row) for row in matches])
        if self.operation == "insert":
            values = self.values if isinstance(self.values, list) else [self.values]
            for value in values:
                if self.table_name == "raw_data" and any(
                    row.get("record_id") == value.get("record_id") for row in rows
                ):
                    raise ValueError("duplicate raw_data record_id")
                rows.append(dict(value))
            return SimpleNamespace(data=[dict(row) for row in values])
        raise AssertionError(f"unsupported operation {self.operation}")


class TenantAwareDatabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return TenantAwareQuery(self, name, "select")


class WorkerTenantSafetyTests(unittest.TestCase):
    def test_event_ownership_requires_matching_delivery_and_company(self):
        database = TenantAwareDatabase({
            "events": [{"delivery_id": "delivery-1", "company_id": "company-a"}],
        })

        with self.assertRaisesRegex(ValueError, "does not belong"):
            db_helpers.ensure_event_tenant(database, "delivery-1", "company-b")

        db_helpers.ensure_event_tenant(database, "delivery-1", "company-a")

    def test_processed_marker_cannot_update_another_company_event(self):
        database = TenantAwareDatabase({
            "events": [{
                "delivery_id": "delivery-1",
                "company_id": "company-a",
                "processed": False,
            }],
        })

        with self.assertRaisesRegex(RuntimeError, "marker update failed"):
            db_helpers.mark_event_processed(database, "delivery-1", "company-b")
        db_helpers.mark_event_processed(database, "delivery-1", "company-a")
        self.assertTrue(database.rows["events"][0]["processed"])

    def test_raw_data_retry_updates_only_the_matching_tenant_row(self):
        database = TenantAwareDatabase({
            "raw_data": [{
                "id": "raw-1",
                "record_id": "delivery-1",
                "company_id": "company-a",
                "content": "old",
            }],
        })
        with patch.object(db_helpers, "embed_content", return_value=[0.1]):
            db_helpers.insert_raw_data(database, {
                "record_id": "delivery-1",
                "company_id": "company-a",
                "source": "slack",
                "content": "new",
            })

        self.assertEqual(len(database.rows["raw_data"]), 1)
        self.assertEqual(database.rows["raw_data"][0]["company_id"], "company-a")
        self.assertEqual(database.rows["raw_data"][0]["content"], "new")
        self.assertEqual(database.rows["raw_data"][0]["id"], "raw-1")

    def test_raw_data_collision_owned_by_other_tenant_fails_closed(self):
        database = TenantAwareDatabase({
            "raw_data": [{
                "id": "raw-1",
                "record_id": "delivery-1",
                "company_id": "company-a",
                "content": "private",
            }],
        })
        with patch.object(db_helpers, "embed_content", return_value=[0.1]):
            with self.assertRaisesRegex(RuntimeError, "raw_data persistence failed"):
                db_helpers.insert_raw_data(database, {
                    "record_id": "delivery-1",
                    "company_id": "company-b",
                    "source": "slack",
                    "content": "attempted overwrite",
                })

        self.assertEqual(database.rows["raw_data"][0]["company_id"], "company-a")
        self.assertEqual(database.rows["raw_data"][0]["content"], "private")

    def test_missing_and_default_tenants_are_rejected_for_worker_writes(self):
        database = TenantAwareDatabase({"events": []})
        for company_id in ("", "default"):
            with self.subTest(company_id=company_id):
                with self.assertRaises(ValueError):
                    db_helpers.ensure_event_tenant(database, "delivery-1", company_id)
                with self.assertRaises(ValueError):
                    db_helpers.insert_raw_data(database, {
                        "record_id": "delivery-1",
                        "company_id": company_id,
                        "content": "text",
                    })


if __name__ == "__main__":
    unittest.main()
