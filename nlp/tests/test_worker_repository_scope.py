"""Tests for trusted repository scope propagation through worker normalization."""

from worker.consumer import RedisStreamConsumer


def test_normalize_job_preserves_top_level_verified_repository():
    consumer = RedisStreamConsumer.__new__(RedisStreamConsumer)

    job = consumer._normalize_job({
        "RecordID": "query-1",
        "CompanyID": "company-a",
        "Repository": "acme/repository",
        "Payload": {
            "question": "Explain the billing module",
            "repository": "attacker/other-repository",
        },
    })

    assert job["company_id"] == "company-a"
    assert job["repository"] == "acme/repository"
    assert job["payload"]["repository"] == "attacker/other-repository"


def test_normalize_job_does_not_promote_untrusted_payload_repository():
    consumer = RedisStreamConsumer.__new__(RedisStreamConsumer)

    job = consumer._normalize_job({
        "RecordID": "query-2",
        "CompanyID": "company-a",
        "Payload": {
            "question": "Explain the billing module",
            "repository": "attacker/other-repository",
        },
    })

    assert job["repository"] is None
