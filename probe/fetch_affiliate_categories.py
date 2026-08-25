#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_URL = "https://eco.taobao.com/router/rest"
METHOD = "aliexpress.affiliate.category.get"


def sign(params: dict[str, str], secret: str) -> str:
    payload = "".join(k + str(v) for k, v in sorted(params.items()) if k != "sign")
    return hmac.new(secret.encode(), payload.encode(), hashlib.md5).hexdigest().upper()


def main() -> int:
    app_key = os.getenv("ALIEXPRESS_APP_KEY", "").strip()
    app_secret = os.getenv("ALIEXPRESS_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        print("Missing ALIEXPRESS_APP_KEY / ALIEXPRESS_APP_SECRET", file=sys.stderr)
        return 2

    cst = timezone(timedelta(hours=8))
    params = {
        "method": METHOD,
        "app_key": app_key,
        "timestamp": datetime.now(cst).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
        "sign_method": "hmac",
    }
    params["sign"] = sign(params, app_secret)

    req = urllib.request.Request(
        API_URL,
        data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode("utf-8"))

    if "error_response" in payload:
        raise RuntimeError(json.dumps(payload["error_response"], ensure_ascii=False))

    root = payload.get("aliexpress_affiliate_category_get_response", {})
    rr = root.get("resp_result", {})
    if str(rr.get("resp_code")) != "200":
        raise RuntimeError(json.dumps(rr, ensure_ascii=False))

    result = rr.get("result", {})
    cat_obj = result.get("categories", {})
    cats = cat_obj.get("category", []) if isinstance(cat_obj, dict) else []
    if isinstance(cats, dict):
        cats = [cats]

    rows = []
    by_id = {}
    for c in cats:
        row = {
            "category_id": str(c.get("category_id", "")),
            "category_name": str(c.get("category_name", "")),
            "parent_category_id": str(c.get("parent_category_id", "")),
        }
        rows.append(row)
        by_id[row["category_id"]] = row

    def make_path(row):
        chain, seen, cur = [], set(), row
        while cur:
            cid = cur["category_id"]
            if cid in seen:
                chain.append("[CYCLE]")
                break
            seen.add(cid)
            chain.append(cur["category_name"] or cid)
            pid = cur["parent_category_id"]
            if not pid or pid in {"0", "None", "null"}:
                break
            cur = by_id.get(pid)
            if cur is None:
                chain.append(f"[parent:{pid}]")
                break
        chain.reverse()
        return len(chain) - 1, " > ".join(chain)

    for row in rows:
        row["depth"], row["category_path"] = make_path(row)
    rows.sort(key=lambda x: (x["category_path"].lower(), x["category_id"]))

    out = Path("output")
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    (out / f"categories_raw_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / f"categories_normalized_{stamp}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / f"categories_{stamp}.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["category_id", "category_name", "parent_category_id", "depth", "category_path"])
        w.writeheader()
        w.writerows(rows)

    tops = [r for r in rows if not r["parent_category_id"] or r["parent_category_id"] in {"0", "None", "null"}]
    (out / f"summary_{stamp}.json").write_text(
        json.dumps({"category_count": len(rows), "top_level_count": len(tops), "top_level_categories": tops}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Fetched {len(rows)} categories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
