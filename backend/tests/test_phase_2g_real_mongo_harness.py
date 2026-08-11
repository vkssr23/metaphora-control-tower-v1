import pytest

from scripts.verify_real_mongo import guarded_target


def test_real_mongo_guard_never_falls_back_and_requires_disposable_name():
    with pytest.raises(ValueError, match="no fallback"):
        guarded_target({"MONGO_URI": "mongodb://production/customer", "APP_ENV": "test"})
    with pytest.raises(ValueError, match="test/disposable"):
        guarded_target({"METAPHORA_TEST_MONGO_URI": "mongodb://localhost", "METAPHORA_TEST_MONGO_DB": "metaphora", "APP_ENV": "test"})
    with pytest.raises(ValueError, match="production"):
        guarded_target({"METAPHORA_TEST_MONGO_URI": "mongodb://localhost", "METAPHORA_TEST_MONGO_DB": "metaphora_test", "APP_ENV": "production"})


def test_real_mongo_guard_accepts_explicit_disposable_target_without_disclosing_it():
    uri, name = guarded_target({"METAPHORA_TEST_MONGO_URI": "mongodb://localhost:27017", "METAPHORA_TEST_MONGO_DB": "metaphora_disposable", "APP_ENV": "staging"})
    assert name == "metaphora_disposable" and uri.startswith("mongodb://")
