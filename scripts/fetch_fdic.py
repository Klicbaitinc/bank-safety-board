#!/usr/bin/env python3
"""Download active FDIC institutions, eight quarters of financials, and failures.

Amounts in the BankFind financial feed are thousands of dollars. This script
stores dollars. Ratio fields are already in percent and are stored that way.
"""
import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

from formatutil import (
    BKCLASS, assert_scale, clean_web, dollars_from_thousands, nice_name,
    parse_date, parse_num, quarter_label, ratio, slugify, zip_code,
)
from http_util import USER_AGENT, get

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache" / "fdic"
API = "https://api.fdic.gov/banks"

INST_FIELDS = ",".join([
    "CERT", "NAME", "STALP", "STNAME", "CITY", "ADDRESS", "ZIP", "WEBADDR",
    "OFFICES", "BKCLASS", "REPDTE", "ACTIVE", "INSDATE", "CHARTER", "NAMEHCR",
])
FIN_FIELDS = ",".join([
    "CERT", "REPDTE", "ASSET", "DEP", "EQ", "ROA", "RBCRWAJ", "IDT1CER",
    "RBC1AAJ", "NCLNLSR", "CBLRIND",
])
FAIL_FIELDS = ",".join([
    "ID", "CERT", "NAME", "CITYST", "FAILDATE", "QBFASSET", "QBFDEP", "COST", "RESTYPE",
])


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(path)


def load_json(path):
    return json.loads(path.read_text())


def api_pages(endpoint, params, cache_name, refresh):
    path = CACHE / f"{cache_name}.json"
    if path.exists() and not refresh:
        print(f"cache {cache_name}", flush=True)
        return load_json(path)
    rows = []
    offset = 0
    limit = 10000
    meta = {}
    while True:
        query = dict(params)
        query.update(limit=limit, offset=offset)
        print(f"GET {endpoint} offset={offset} {cache_name}", flush=True)
        response = get(f"{API}/{endpoint}", params=query, pause=0.4, timeout=180)
        payload = response.json()
        meta = payload.get("meta") or {}
        batch = [item.get("data") or {} for item in payload.get("data") or []]
        rows.extend(batch)
        total = int(meta.get("total") or 0)
        offset += len(batch)
        if not batch or offset >= total:
            break
    result = {"meta": meta, "rows": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result


def quarter_ends(end, count):
    year, month = end.year, end.month
    found = []
    for _ in range(count):
        if month not in (3, 6, 9, 12):
            month = ((month - 1) // 3) * 3 or 12
            if month == 12 and end.month < 3:
                year -= 1
        day = {3: 31, 6: 30, 9: 30, 12: 31}[month]
        found.append(dt.date(year, month, day))
        month -= 3
        if month <= 0:
            month += 12
            year -= 1
    return list(reversed(found))


def flag(value):
    number = parse_num(value)
    if number is None:
        return None
    return int(number)


def institution_row(row):
    cert = int(row["CERT"])
    official = str(row.get("NAME") or "").strip()
    state = str(row.get("STALP") or "").strip().upper()
    return {
        "cert": cert,
        "official_name": official,
        "name": nice_name(official),
        "slug": slugify(official),
        "city": nice_name(str(row.get("CITY") or "").strip()),
        "state": state,
        "state_name": str(row.get("STNAME") or "").strip(),
        "address": str(row.get("ADDRESS") or "").strip(),
        "zip": zip_code(row.get("ZIP")),
        "web": clean_web(row.get("WEBADDR")),
        "offices": None if parse_num(row.get("OFFICES")) is None else int(parse_num(row.get("OFFICES"))),
        "bkclass": str(row.get("BKCLASS") or "").strip(),
        "bkclass_label": BKCLASS.get(str(row.get("BKCLASS") or "").strip(), ""),
        "insured_since": parse_date(row.get("INSDATE")),
        "charter": str(row.get("CHARTER") or "").strip(),
        "holding_company": str(row.get("NAMEHCR") or "").strip(),
        "repdte": parse_date(row.get("REPDTE")),
        "active": int(parse_num(row.get("ACTIVE")) or 0),
    }


def financial_row(row):
    cblr = flag(row.get("CBLRIND"))
    rbc = ratio(row.get("RBCRWAJ"))
    cet1 = ratio(row.get("IDT1CER"))
    leverage = ratio(row.get("RBC1AAJ"))
    equity = dollars_from_thousands(row.get("EQ"))
    # Banks that elected the community bank leverage ratio have 0 in the
    # risk-based ratio fields. That 0 is not a reported ratio.
    if cblr == 1:
        rbc = None
        cet1 = None
    elif rbc == 0 and cet1 == 0 and leverage == 0 and equity is None:
        rbc = cet1 = leverage = None
    return {
        "date": parse_date(row.get("REPDTE")),
        "assets": dollars_from_thousands(row.get("ASSET")),
        "deposits": dollars_from_thousands(row.get("DEP")),
        "equity": equity,
        "roa": ratio(row.get("ROA")),
        "rbc": rbc,
        "cet1": cet1,
        "leverage": leverage,
        "npl": ratio(row.get("NCLNLSR")),
        "cblr": cblr,
    }


def split_city_state(value):
    text = str(value or "").strip()
    if "," not in text:
        return nice_name(text), ""
    city, state = text.rsplit(",", 1)
    return nice_name(city.strip()), state.strip().upper()


def failure_row(row):
    city, state = split_city_state(row.get("CITYST"))
    official = str(row.get("NAME") or "").strip()
    cert = parse_num(row.get("CERT"))
    return {
        "fdic_id": str(row.get("ID") or "").strip(),
        "cert": int(cert) if cert is not None else None,
        "official_name": official,
        "name": nice_name(official),
        "city": city,
        "state": state,
        "date": parse_date(row.get("FAILDATE")),
        "assets": dollars_from_thousands(row.get("QBFASSET")),
        "deposits": dollars_from_thousands(row.get("QBFDEP")),
        "cost": dollars_from_thousands(row.get("COST")),
        "resolution": str(row.get("RESTYPE") or "").strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-download even if a cache file exists")
    args = parser.parse_args()
    print(f"FDIC user agent: {USER_AGENT}", flush=True)

    institutions = api_pages(
        "institutions",
        {"filters": "ACTIVE:1", "fields": INST_FIELDS, "sort_by": "CERT", "sort_order": "ASC"},
        "institutions-active",
        args.refresh,
    )
    banks = [institution_row(row) for row in institutions["rows"] if parse_num(row.get("CERT")) is not None]
    banks = [bank for bank in banks if bank["active"] == 1]
    rep_counts = Counter(bank["repdte"] for bank in banks if bank["repdte"])
    if not rep_counts:
        raise SystemExit("no report dates on active institutions")
    modal = rep_counts.most_common(1)[0][0]
    print(f"active banks {len(banks)}; modal report date {modal} ({rep_counts[modal]})", flush=True)

    ends = quarter_ends(dt.date.fromisoformat(modal), 8)
    # If the newest quarter is only a partial filing, step back until it covers
    # most active banks. Call reports land a few weeks after quarter-end.
    financials = {}
    kept = []
    for end in ends:
        key = end.strftime("%Y%m%d")
        payload = api_pages(
            "financials",
            {"filters": f"REPDTE:{key}", "fields": FIN_FIELDS},
            f"financials-{key}",
            args.refresh,
        )
        by_cert = {}
        for row in payload["rows"]:
            if parse_num(row.get("CERT")) is None:
                continue
            by_cert[int(row["CERT"])] = financial_row(row)
        financials[key] = by_cert
        print(f"  {key}: {len(by_cert)} financial rows", flush=True)
        if len(by_cert) >= 1000:
            kept.append(end)
    if not kept:
        raise SystemExit("no quarter returned at least 1,000 financial rows")
    # Keep the eight most recent quarters that actually have a full filing,
    # walking back further if the first pass included an empty leading quarter.
    if len(kept) < 8:
        extra_start = kept[0]
        more = quarter_ends(extra_start - dt.timedelta(days=1), 8 - len(kept))
        for end in more:
            if end in kept:
                continue
            key = end.strftime("%Y%m%d")
            payload = api_pages(
                "financials",
                {"filters": f"REPDTE:{key}", "fields": FIN_FIELDS},
                f"financials-{key}",
                args.refresh,
            )
            by_cert = {}
            for row in payload["rows"]:
                if parse_num(row.get("CERT")) is None:
                    continue
                by_cert[int(row["CERT"])] = financial_row(row)
            if len(by_cert) >= 1000:
                financials[key] = by_cert
                kept.append(end)
                print(f"  extra {key}: {len(by_cert)}", flush=True)
    kept = sorted(kept)[-8:]
    as_of = kept[-1].isoformat()
    print(f"using quarters {[d.isoformat() for d in kept]} as of {as_of}", flush=True)

    for bank in banks:
        series = []
        for end in kept:
            row = financials.get(end.strftime("%Y%m%d"), {}).get(bank["cert"])
            if row and row["date"]:
                series.append(row)
        bank["quarters"] = series

    latest_rows = [q for bank in banks for q in bank["quarters"][-1:] if q["date"] == as_of]
    assert_scale("total risk-based capital ratio", [q["rbc"] for q in latest_rows], 5, 40)
    assert_scale("noncurrent loan ratio", [q["npl"] for q in latest_rows], 0, 8)
    assert_scale("ROA", [q["roa"] for q in latest_rows], -2, 5)
    assert_scale("tier 1 leverage ratio", [q["leverage"] for q in latest_rows], 3, 30)

    failures_payload = api_pages(
        "failures",
        {"fields": FAIL_FIELDS, "sort_by": "FAILDATE", "sort_order": "DESC"},
        "failures",
        args.refresh,
    )
    resolutions = Counter(str(row.get("RESTYPE") or "") for row in failures_payload["rows"])
    print(f"failure resolution types: {dict(resolutions)}", flush=True)
    failures = []
    for row in failures_payload["rows"]:
        if str(row.get("RESTYPE") or "").strip() != "FAILURE":
            continue
        # Some early failures have a date and a name but no certificate number.
        if not parse_date(row.get("FAILDATE")):
            continue
        failures.append(failure_row(row))
    failures.sort(key=lambda item: item["date"], reverse=True)

    banks.sort(key=lambda item: item["cert"])
    fetched = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    index = (institutions.get("meta") or {}).get("index") or {}
    dump(DATA / "banks.json", {
        "meta": {
            "source": "FDIC BankFind Suite institutions and financials",
            "fetched_at": fetched,
            "user_agent": USER_AGENT,
            "as_of": as_of,
            "quarter": quarter_label(as_of),
            "quarters": [d.isoformat() for d in kept],
            "index": index.get("name"),
            "index_created": index.get("createTimestamp"),
            "active_institutions": len(banks),
            "institutions_filter": "ACTIVE:1",
            "active_means": "FDIC ACTIVE 1: currently open and insured by the FDIC",
        },
        "banks": banks,
    })
    dump(DATA / "failures.json", {
        "meta": {
            "source": "FDIC BankFind Suite failures",
            "fetched_at": fetched,
            "user_agent": USER_AGENT,
            "resolution_counts": dict(resolutions),
            "listed": "RESTYPE FAILURE only",
            "count": len(failures),
        },
        "failures": failures,
    })
    print(f"wrote {len(banks)} banks and {len(failures)} failures", flush=True)


if __name__ == "__main__":
    main()
