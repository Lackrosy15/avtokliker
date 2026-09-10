# Тесты парсинга avtokliker без сети.
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from avtokliker import Lead, parse_curl, parse_leads, build_accept_request, CurlRequest

CURL_SAMPLE = r"""curl 'https://util.1c-bitrix.by/bitrix/services/main/ajax.php?mode=class&c=bx%3Apartner.application.b24.list.work&action=synchronizeQualificationDataStartGrid' \
  -H 'accept: application/json' \
  -H 'cookie: PHPSESSID=abc123; BX_USER_ID=42' \
  --data-raw 'signedParameters=AAA.BBB&sessid=xyz&page=1' \
  --compressed"""

def test_parse_curl():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(CURL_SAMPLE)
        path = Path(f.name)
    req = parse_curl(path)
    assert req.method == "POST", req.method
    assert "action=synchronizeQualificationDataStartGrid" in req.url
    assert req.headers["cookie"] == "PHPSESSID=abc123; BX_USER_ID=42"
    assert "signedParameters=AAA.BBB" in req.data
    print("parse_curl OK")

def test_parse_leads_typical_bx():
    payload = json.dumps({
        "status": "success",
        "data": {
            "items": [
                {"ID": 12345, "TITLE": "Внедрение Битрикс для строительной организации",
                 "CITY": "Минск", "DIRECTION": "Битрикс24", "DETAILS": ""},
                {"ID": 12346, "TITLE": "Интеграция 1С с бухгалтерией",
                 "CITY": "Гомель", "DIRECTION": "1С", "DETAILS": ""},
                {"ID": 12347, "TITLE": "Настройка CRM",
                 "CITY": "Брест", "DIRECTION": "Битрикс24",
                 "DETAILS": "Нельзя взять эту заявку: Нет свободных мест"},
            ]
        }
    }).encode()
    leads = parse_leads(payload)
    assert len(leads) == 3, leads
    assert leads[0].id == "12345"
    assert leads[0].city == "Минск"
    assert leads[2].slots_free is False
    assert leads[0].matches(["внедрение", "crm"], ["1с"])
    assert not leads[1].matches(["внедрение", "crm"], ["1с"])
    print("parse_leads OK")

def test_build_accept_request():
    template = CurlRequest(
        method="POST",
        url="https://util.1c-bitrix.by/bitrix/services/main/ajax.php?action=takeWork",
        headers={"cookie": "PHPSESSID=abc"},
        data="signedParameters=AAA&sessid=xyz&id=99999",
    )
    lead = Lead(id="12345", title="Тест")
    req = build_accept_request(template, lead)
    assert "id=12345" in req.data, req.data
    assert "99999" not in req.data
    print("build_accept_request OK")

if __name__ == "__main__":
    test_parse_curl()
    test_parse_leads_typical_bx()
    test_build_accept_request()
    print("Все тесты прошли")
