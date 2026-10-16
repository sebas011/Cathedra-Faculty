"""Query public package names/versions only; fail closed on incomplete checks."""
import json
import urllib.request
from pathlib import Path


def check():
    root=Path(__file__).resolve().parents[1]
    pins=[line.split("==",1) for line in (root/"backend/constraints-win-py314.txt").read_text().splitlines() if "==" in line]
    queries=[{"package":{"ecosystem":"PyPI","name":name},"version":version} for name,version in pins]
    request=urllib.request.Request("https://api.osv.dev/v1/querybatch",data=json.dumps({"queries":queries}).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=45) as response:
        results=json.load(response)["results"]
    findings=[{"package":name,"version":version,"advisories":result["vulns"]} for (name,version),result in zip(pins,results,strict=True) if result.get("vulns")]
    print(json.dumps({"packages_checked":len(pins),"findings":findings},indent=2))
    if findings:raise SystemExit(1)


if __name__=="__main__":check()
