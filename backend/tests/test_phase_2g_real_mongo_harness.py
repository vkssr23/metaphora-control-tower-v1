import asyncio
import json

import pytest
from pymongo.errors import OperationFailure

from scripts.verify_real_mongo import guarded_target, index_plan, validate_plan, verify


SAFE_ENV = {
    "METAPHORA_TEST_MONGO_URI": "mongodb://certifier:never-print-this-password@example.invalid",
    "METAPHORA_TEST_MONGO_DB": "metaphora_disposable", "APP_ENV": "staging",
    "METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED": "true",
}


class FakeAdmin:
    def __init__(self, failure=None): self.failure = failure
    async def command(self, name):
        if self.failure: raise self.failure
        return {"logicalSessionTimeoutMinutes": None}


class FailingIndexCollection:
    async def create_index(self, *args, **kwargs):
        raise OperationFailure("mongodb://user:password@host must never appear", code=85,
                               details={"codeName": "IndexOptionsConflict", "credential": "secret"})


class EmptyFailingIndexDatabase:
    async def list_collection_names(self): return []
    def __getitem__(self, name): return FailingIndexCollection()


class NonemptyDatabase:
    async def list_collection_names(self): return ["existing"]


class FakeClient:
    def __init__(self, admin, db=None):
        self.admin, self.db, self.drop_calls, self.closed = admin, db, 0, False
    def __getitem__(self, name): return self.db
    async def drop_database(self, name): self.drop_calls += 1
    def close(self): self.closed = True


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


def test_index_operation_failure_reports_safe_identity_and_cleans_owned_database():
    client=FakeClient(FakeAdmin(), EmptyFailingIndexDatabase())
    report=asyncio.run(verify(SAFE_ENV, client_factory=lambda *args, **kwargs: client))
    assert report == {
        "status":"FAIL", "reason_code":"OperationFailure", "stage":"index_creation",
        "collection":"tenants", "index_name":"uq_tenants_id", "mongo_error_code":85,
        "mongo_error_code_name":"IndexOptionsConflict", "production_accessed":False,
        "customer_data_accessed":False, "uri_included":False,
        "cleanup_result":"OWNED_DISPOSABLE_DATABASE_DROPPED",
    }
    serialized=json.dumps(report)
    assert "mongodb" not in serialized.lower() and "password" not in serialized.lower()
    assert "credential" not in serialized.lower() and client.drop_calls == 1 and client.closed


def test_preownership_operation_failure_identifies_hello_and_never_drops_database():
    failure=OperationFailure("secret host and password", code=13, details={"codeName":"Unauthorized"})
    client=FakeClient(FakeAdmin(failure))
    report=asyncio.run(verify(SAFE_ENV, client_factory=lambda *args, **kwargs: client))
    assert report["status"] == "FAIL" and report["stage"] == "hello"
    assert report["mongo_error_code"] == 13 and report["mongo_error_code_name"] == "Unauthorized"
    assert report["cleanup_result"] == "NOT_OWNED_NO_DROP"
    assert client.drop_calls == 0 and "password" not in json.dumps(report).lower()


def test_nonempty_target_is_never_owned_or_dropped():
    client=FakeClient(FakeAdmin(), NonemptyDatabase())
    with pytest.raises(RuntimeError, match="not empty"):
        asyncio.run(verify(SAFE_ENV, client_factory=lambda *args, **kwargs: client))
    assert client.drop_calls == 0 and client.closed
