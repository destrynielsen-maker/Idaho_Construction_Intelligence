"""Read-only discovery of City of Nampa's official public ArcGIS catalog.

The city links its ArcGIS hub at https://www.cityofnampa.us/185/Mapping.
No credentials, restricted datasets, guessed service routes, or ledger writes.
Catalog hits alone are not proof of issuance coverage.
"""
import json
import re
import urllib.parse
import urllib.request

PORTAL = "https://nampa.maps.arcgis.com/sharing/rest/"
SEARCH = "https://www.arcgis.com/sharing/rest/search"


def get_json(url, params):
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                     headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        if urllib.parse.urlsplit(response.url).hostname != urllib.parse.urlsplit(url).hostname:
            raise ValueError("Unexpected redirect host")
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError("Oversize catalog response")
    obj = json.loads(data)
    if "error" in obj:
        raise RuntimeError("Public catalog API error: " + str(obj["error"].get("code")))
    return obj


def search():
    org = get_json(PORTAL + "portals/self", {"f": "json"})
    org_id = org.get("id")
    if not isinstance(org_id, str) or not re.fullmatch(r"[A-Za-z0-9]{16}", org_id):
        raise ValueError("Public city organization identity not established")
    print("Public organization:", org.get("name"), org_id)
    query = f'orgid:{org_id} AND (permit OR permits OR permitting OR energov) AND access:public'
    start = 1
    seen = set()
    while start != -1:
        if start < 1 or start in seen or len(seen) >= 10:
            raise ValueError("Incomplete or repeated catalog pagination")
        seen.add(start)
        result = get_json(SEARCH, {"q": query, "f": "json", "num": 100, "start": start})
        print("Catalog total:", result["total"], "page:", start)
        for item in result["results"]:
            if item.get("orgId") != org_id or item.get("access") != "public":
                raise ValueError("Unexpected organization or access in search results")
            print(json.dumps({k: item.get(k) for k in
                ("id", "title", "type", "url", "modified", "owner", "access")}))
        start = result["nextStart"]
    print("Catalog discovery complete. No issuance records imported.")


if __name__ == "__main__":
    search()
