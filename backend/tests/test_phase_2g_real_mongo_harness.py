import pytest

from scripts.verify_real_mongo import guarded_target, index_plan, validate_plan


def test_real_mongo_guard_never_falls_back_and_requires_disposable_name():
    with pytest.raises(ValueError, match="no fallback"):
        guarded_target({"MONGO_URI": "mongodb://production/customer", "APP_ENV": "test"})
    with pytest.raises(ValueError, match="test/disposable"):
        guarded_target({"METAPHORA_TEST_MONGO_URI": "mongodb://localhost", "METAPHORA_TEST_MONGO_DB": "metaphora", "APP_ENV": "test", "METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED":"true"})
    with pytest.raises(ValueError, match="production"):
        guarded_target({"METAPHORA_TEST_MONGO_URI": "mongodb://localhost", "METAPHORA_TEST_MONGO_DB": "metaphora_test", "APP_ENV": "production", "METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED":"true"})
    with pytest.raises(ValueError, match="explicitly confirm"):
        guarded_target({"METAPHORA_TEST_MONGO_URI":"mongodb://localhost", "METAPHORA_TEST_MONGO_DB":"metaphora_test", "APP_ENV":"test"})


def test_real_mongo_guard_accepts_explicit_disposable_target_without_disclosing_it():
    uri, name = guarded_target({"METAPHORA_TEST_MONGO_URI": "mongodb://localhost:27017", "METAPHORA_TEST_MONGO_DB": "metaphora_disposable", "APP_ENV": "staging", "METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED":"true"})
    assert name == "metaphora_disposable" and uri.startswith("mongodb://")


def test_manifest_plan_is_bounded_authoritative_and_valid():
    plan=index_plan(); result=validate_plan(plan)
    assert result["status"] == "PASS" and result["index_count"] == len(plan)
    assert not result["duplicates"] and not result["invalid"]
    assert all(set(x) == {"collection","name","fields","unique","partial_filter","priority","purpose"} for x in plan)
