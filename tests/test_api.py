"""API tests on real cached data (EU snapshot 2026-09-13, ONSSA cache). Spray records are seeded."""
from fastapi.testclient import TestClient

from residuecheck.api import app, parse_csv

client = TestClient(app)
ORANGES = "0110020"


def test_health_reports_engine_and_data():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["engine"]["name"] == "rules-only" and body["engine"]["model"] is None
    assert body["eu_snapshot"] == "2026-09-13" and body["onssa_products"] > 1000 and body["crops"] == 32


def test_crops_and_product_suggestions():
    crops = client.get("/api/crops").json()
    assert any(c["code"] == ORANGES for c in crops) and len(crops) == 32
    assert "ACTARA 25 WG" in client.get("/api/products", params={"q": "actara"}).json()["products"]


def test_actara_on_oranges_is_red_with_sources():
    body = client.post("/api/check", json={"crop_code": ORANGES, "harvest_on": "2026-10-01",
                                           "applications": [{"product": "ACTARA 25 WG", "applied_on": "2026-08-15"}]}).json()
    assert body["verdict"] == "RED"
    app0 = body["applications"][0]
    assert (app0["status"], app0["registration"], app0["dar_days"]) == ("found", "registered", 28)
    red = [f for f in body["findings"] if f["code"] == "MRL_AT_LOQ"]
    assert red and red[0]["sources"]
    assert body["engine"]["name"] == "rules-only"


def test_misspelled_product_is_not_guessed_but_suggested():
    body = client.post("/api/check", json={"crop_code": ORANGES, "harvest_on": "2026-10-01",
                                           "applications": [{"product": "AKTARA 25 WG", "applied_on": "2026-08-15"}]}).json()
    assert body["verdict"] == "CANNOT_VERIFY"
    assert body["applications"][0]["status"] == "not_found"
    assert "ACTARA 25 WG" in body["applications"][0]["suggestions"]


def test_validation_errors():
    assert client.post("/api/check", json={"crop_code": "9999999", "harvest_on": "2026-10-01",
                                           "applications": [{"product": "X", "applied_on": "2026-08-15"}]}).status_code == 422
    assert client.post("/api/check", json={"crop_code": ORANGES, "harvest_on": "2026-10-01", "origin": "TR",
                                           "applications": [{"product": "X", "applied_on": "2026-08-15"}]}).status_code == 422
    assert client.post("/api/check", json={"crop_code": ORANGES, "harvest_on": "2026-10-01", "applications": []}).status_code == 422


def test_csv_check_and_parser():
    rows, errors = parse_csv("produit;date\nACTARA 25 WG;15/08/2026\nBAD ROW\nCYMIL;2026-09-01\nX;31/31/2026")
    assert [r.product for r in rows] == ["ACTARA 25 WG", "CYMIL"]
    assert len(errors) == 2
    body = client.post("/api/check/csv", json={"crop_code": ORANGES, "harvest_on": "2026-10-01",
                                               "csv_text": "product,date\nACTARA 25 WG,2026-08-15"}).json()
    assert body["verdict"] == "RED" and body["csv_errors"] == []
