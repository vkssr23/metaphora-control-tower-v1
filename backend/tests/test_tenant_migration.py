"""In-memory tests for the explicit Patch 0C legacy migration utility."""
import pytest

from scripts import backfill_single_tenant as migration

TEN_A = "ten_" + "a" * 32
TEN_B = "ten_" + "b" * 32
TEN_OTHER = "ten_" + "c" * 32
TEN_GENERATED = "ten_" + "d" * 32


def matches(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(doc, q) for q in value): return False
        elif isinstance(value, dict) and "$exists" in value:
            if (key in doc) != value["$exists"]: return False
        elif doc.get(key) != value: return False
    return True


class Collection:
    def __init__(self, docs=None, fail=False): self.docs=list(docs or []); self.writes=[]; self.fail=fail
    def find(self, query): return [dict(d) for d in self.docs if matches(d,query)]
    def find_one(self, query): return next((dict(d) for d in self.docs if matches(d,query)),None)
    def count_documents(self, query): return len(self.find(query))
    def insert_one(self, doc):
        if self.fail: raise RuntimeError("mongodb://secret/private")
        self.writes.append(("insert",dict(doc))); self.docs.append(dict(doc))
    def update_many(self, query, update):
        if self.fail: raise RuntimeError("mongodb://secret/private")
        self.writes.append(("update",dict(query)))
        for doc in self.docs:
            if matches(doc,query): doc.update(update["$set"])


class DB:
    def __init__(self, owners=None, tenant=None):
        self.users=Collection(owners or [])
        self.tenants=Collection([tenant] if tenant else [])
        for name in migration.OPERATIONAL_COLLECTIONS: setattr(self,name,Collection([{"id":name+"-legacy"},{"id":name+"-owned","tenant_id":TEN_OTHER}]))
    def __getitem__(self,name): return getattr(self,name)
    @property
    def writes(self): return sum((c.writes for c in [self.users,self.tenants,*[getattr(self,n) for n in migration.OPERATIONAL_COLLECTIONS]]),[])


def owner(tenant_id=None):
    result={"id":"U1","email":"owner@example.test","role":"owner"}
    if tenant_id: result["tenant_id"]=tenant_id
    return result


def invoke(db, **overrides):
    output=[]; args={"owner_email":"OWNER@example.test","tenant_name":"Acme","requested_tenant_id":None,"execute":False,"confirmation":"","acknowledge_consolidation":False,"output":output.append,"id_factory":lambda:TEN_GENERATED}; args.update(overrides)
    return migration.run(db,**args),output


def test_dry_run_reports_counts_warning_and_zero_writes():
    db=DB([owner()]); code,output=invoke(db)
    assert code==0 and db.writes==[]
    assert migration.CONSOLIDATION_WARNING in output and "  loads: 1" in output


def test_confirmation_controls_fail_before_database_reads_or_writes():
    db=DB([owner()]); assert invoke(db,execute=True)[0]==2 and db.writes==[]
    assert invoke(db,execute=True,confirmation=migration.CONFIRMATION)[0]==2 and db.writes==[]


def test_zero_multiple_and_wrong_role_owner_fail_before_writes():
    for owners in ([],[owner(),{**owner(),"id":"U2"}],[{**owner(),"role":"admin"}]):
        db=DB(owners); assert invoke(db)[0]==3 and db.writes==[]


def test_conflicting_owner_tenant_fails_before_writes():
    db=DB([owner(TEN_A)],{"id":TEN_A,"name":"Acme"})
    assert invoke(db,requested_tenant_id=TEN_B,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)[0]==3
    assert db.writes==[]


def test_matching_owner_and_existing_target_proceeds_without_tenant_insert():
    db=DB([owner(TEN_A)],{"id":TEN_A,"name":"Acme"})
    assert invoke(db,requested_tenant_id=TEN_A,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)[0]==0
    assert db.tenants.writes==[]


def test_tenant_creation_occurs_only_after_preconditions_pass():
    db=DB([owner()]); code,_=invoke(db,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)
    assert code==0 and db.tenants.writes[0][0]=="insert" and db.tenants.docs[0]["id"]==TEN_GENERATED


def test_missing_only_backfill_never_overwrites_existing_tenant_ids():
    db=DB([owner()]); invoke(db,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)
    for name in migration.OPERATIONAL_COLLECTIONS:
        docs=getattr(db,name).docs
        assert docs[0]["tenant_id"]==TEN_GENERATED and docs[1]["tenant_id"]==TEN_OTHER
        assert getattr(db,name).writes[-1][1]==migration.missing_tenant_filter()


def test_rerun_is_idempotent():
    db=DB([owner()]); invoke(db,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)
    before=[dict(d) for d in db.loads.docs]
    invoke(db,requested_tenant_id=TEN_GENERATED,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)
    assert db.loads.docs==before


def test_partial_database_failure_is_sanitized_and_nonzero():
    db=DB([owner()]); db.loads.fail=True; code,output=invoke(db,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)
    assert code==3 and output[-1]=="Migration failed safely" and "mongodb" not in " ".join(output).lower()


def test_utility_has_no_delete_operation_and_import_does_nothing():
    assert not hasattr(Collection,"delete_one") and not hasattr(Collection,"delete_many")
    db=DB([owner()]); assert db.writes==[]


def test_valid_supplied_and_generated_tenant_ids_are_canonical():
    db=DB([owner()]); assert invoke(db,requested_tenant_id=TEN_A,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)[0]==0
    assert db.tenants.docs[0]["id"]==TEN_A
    generated=migration.new_tenant_id(); assert migration.validate_tenant_id(generated)==generated


@pytest.mark.parametrize("invalid", [
    "", "   ", " ten_"+"a"*32, "ten_"+"a"*32+" ", "ten_"+"a"*15+" "+"a"*16,
    "ten_"+"a"*31+"\t", "ten_"+"a"*31+"\n", "ten_"+"a"*31+"\r",
    "ten_"+"a"*31+"\0", "ten_"+"a"*31+"\x1f", "org_"+"a"*32, "a"*32,
    "ten_"+"A"*32, "ten_"+"a"*16+"A"*16, "ten_"+"a"*31, "ten_"+"a"*33,
    "ten_"+"g"*32, "ten_/"+"a"*31, "ten_\\"+"a"*31, "ten_."+"a"*31,
    "ten_.."+"a"*30, "ten_:"+"a"*31, "ten_;"+"a"*31, "ten_,"+"a"*31,
    "ten_|"+"a"*31, "ten_?"+"a"*31, "ten_#"+"a"*31, "ten_&"+"a"*31,
    "ten_="+"a"*31, "ten_%2f"+"a"*29, "ｔｅｎ_"+"a"*32, "ten_"+"a"*31+"\u00a0",
    "../ten_"+"a"*32, "https://example/ten_"+"a"*32, "x:ten_"+"a"*32,
    TEN_A+"suffix", "prefix"+TEN_A, "ten_",
])
def test_invalid_supplied_tenant_ids_fail_before_all_writes(invalid):
    db=DB([owner()]); code,_=invoke(db,requested_tenant_id=invalid,execute=True,confirmation=migration.CONFIRMATION,acknowledge_consolidation=True)
    assert code==3 and db.writes==[] and db.tenants.docs==[]
    called=False
    def forbidden_client(_):
        nonlocal called; called=True; raise AssertionError("client must not be constructed")
    cli_code=migration.main(["--tenant-name","Acme","--owner-email","owner@example.test","--tenant-id",invalid],client_factory=forbidden_client,environ={"MONGO_URL":"not-used","DB_NAME":"not-used"})
    assert cli_code!=0 and called is False


class FakeClient:
    def __init__(self, database): self.database=database; self.closed=False
    def __getitem__(self, name): return self.database
    def close(self): self.closed=True


def test_valid_cli_tenant_id_requests_only_injected_client():
    db=DB([owner()]); calls=[]; client=FakeClient(db)
    def factory(value): calls.append(value); return client
    code=migration.main(["--tenant-name","Acme","--owner-email","owner@example.test","--tenant-id",TEN_A],client_factory=factory,environ={"MONGO_URL":"fake-config","DB_NAME":"fake-db"})
    assert code==0 and calls==["fake-config"] and client.closed and db.writes==[]


def test_missing_cli_arguments_and_execution_controls_precede_client_construction():
    calls=[]
    def forbidden(value): calls.append(value); raise AssertionError("unexpected client")
    with pytest.raises(SystemExit): migration.main([],client_factory=forbidden,environ={})
    assert calls==[]
    code=migration.main(["--tenant-name","Acme","--owner-email","owner@example.test","--tenant-id",TEN_A,"--execute"],client_factory=forbidden,environ={"MONGO_URL":"fake","DB_NAME":"fake"})
    assert code==2 and calls==[]
