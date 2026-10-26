#!/usr/bin/env python3
"""Build the static site from data/*.json into site/."""
import bisect
import datetime as dt
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from formatutil import (
    CU_TYPES, STATE_NAMES, comma, money, nice_date, pct, quarter_label, sparkline,
)
from siteconfig import BASE, CONTACT, FOOTER, PUBLIC, SITE_NAME, SITE_URL

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
SITEMAP_LIMIT = 45000

env = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)
env.filters.update(money=money, pct=pct, comma=comma, nice_date=nice_date)


def load_json(name):
    return json.loads((ROOT / "data" / name).read_text())


def load_yaml(name):
    data = yaml.safe_load((ROOT / "config" / name).read_text()) or {}
    return data


def write(rel, text):
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def lower_share(pairs):
    usable = [(key, value) for key, value in pairs if value is not None]
    ordered = sorted(value for _, value in usable)
    count = len(ordered)
    out = {}
    for key, value in usable:
        below = bisect.bisect_left(ordered, value)
        out[key] = round(100.0 * below / count, 1) if count else None
    return out, count


def equity_ratio(quarter):
    if not quarter or not quarter.get("assets") or quarter.get("equity") is None:
        return None
    return quarter["equity"] / quarter["assets"] * 100.0


def nwr(quarter):
    if not quarter or not quarter.get("assets") or quarter.get("net_worth") is None:
        return None
    return quarter["net_worth"] / quarter["assets"] * 100.0


def delinquency(quarter):
    if not quarter or not quarter.get("loans") or quarter.get("delinquent") is None:
        return None
    return quarter["delinquent"] / quarter["loans"] * 100.0


def latest_on(quarters, as_of):
    match = [quarter for quarter in quarters if quarter.get("date") == as_of]
    return match[-1] if match else None


def json_ld(obj):
    return Markup(json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c"))


def faq_block(faqs):
    if not faqs:
        return ""
    return json_ld({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faqs
        ],
    })


def contains_phrase(text, phrase):
    if not text:
        return False
    if phrase.upper() == "VETERAN":
        return re.search(r"\bVETERANS?\b", text, re.I) is not None
    return re.search(r"\b" + re.escape(phrase) + r"\b", text, re.I) is not None


def https_offers(raw):
    offers = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        name = str(item.get("name") or "").strip()
        if not name or not url.startswith("https://"):
            continue
        offers.append({
            "name": name,
            "url": url,
            "apy_label": str(item.get("apy_label") or "").strip(),
            "details": str(item.get("details") or "").strip(),
        })
    return offers


def newsletter_config(raw):
    url = str((raw or {}).get("url") or "").strip()
    if not url.startswith("https://"):
        url = ""
    return {
        "url": url,
        "heading": str((raw or {}).get("heading") or "The free banking note").strip(),
        "text": str((raw or {}).get("text") or "").strip(),
        "button": str((raw or {}).get("button") or "Subscribe").strip(),
    }


def state_name(code, reported=""):
    if reported:
        return reported
    return STATE_NAMES.get(code, code)


def hq_line(parts):
    bits = [part for part in parts if part]
    return ", ".join(bits)


def bank_faqs(bank, quarter, quarter_name, rbc_share, rbc_n):
    name = bank["name"]
    faqs = []
    insured = (
        f"Yes. {name} is on the FDIC list of institutions that are currently open and insured. "
        f"The FDIC certificate number is {bank['cert']}."
    )
    if bank.get("insured_since"):
        insured += f" Deposit insurance on that record began on {nice_date(bank['insured_since'])}."
    insured += (
        " The standard FDIC insurance limit is $250,000 per depositor, per insured bank, "
        "for each account ownership category. This page does not calculate coverage for a specific person."
    )
    faqs.append({"q": f"Is {name} FDIC insured?", "a": insured})
    faqs.append({
        "q": f"What is the FDIC certificate number for {name}?",
        "a": f"The FDIC certificate number for {name} is {bank['cert']}.",
    })
    if quarter and quarter.get("deposits") is not None:
        faqs.append({
            "q": f"How much does {name} report in deposits for {quarter_name}?",
            "a": (
                f"For the quarter ending {nice_date(quarter['date'])}, the FDIC reports "
                f"{money(quarter['deposits'])} of total deposits at {name}."
            ),
        })
    if quarter and quarter.get("assets") is not None:
        faqs.append({
            "q": f"How large is {name} by assets?",
            "a": (
                f"For the quarter ending {nice_date(quarter['date'])}, the FDIC reports "
                f"{money(quarter['assets'])} of total assets at {name}."
            ),
        })
    if quarter and quarter.get("rbc") is not None:
        answer = (
            f"For {quarter_name}, the FDIC reports a total risk-based capital ratio of {pct(quarter['rbc'])} "
            f"for {name}. The ratio is total risk-based capital divided by risk-weighted assets. "
            f"It is not a grade and it is not a prediction."
        )
        if rbc_share is not None and rbc_n:
            answer += (
                f" Among {rbc_n:,} active banks that reported the ratio for {quarter_name}, "
                f"{rbc_share:.1f}% had a lower figure."
            )
        faqs.append({
            "q": f"What is {name}'s total risk-based capital ratio for {quarter_name}?",
            "a": answer,
        })
    if quarter and quarter.get("npl") is not None:
        faqs.append({
            "q": f"What is {name}'s noncurrent-loan ratio for {quarter_name}?",
            "a": (
                f"For {quarter_name}, the FDIC reports noncurrent loans and leases at {pct(quarter['npl'])} "
                f"of gross loans and leases for {name}. Noncurrent means 90 days or more past due, or in nonaccrual."
            ),
        })
    if quarter and quarter.get("roa") is not None:
        faqs.append({
            "q": f"What was {name}'s return on assets for {quarter_name}?",
            "a": (
                f"For {quarter_name}, the FDIC reports return on assets of {pct(quarter['roa'])} for {name}. "
                f"Return on assets is annualized net income as a percent of average total assets."
            ),
        })
    place = hq_line([bank.get("address"), bank.get("city"), " ".join(bit for bit in [bank.get("state_name") or bank.get("state"), bank.get("zip")] if bit)])
    if place:
        faqs.append({
            "q": f"Where is {name} headquartered?",
            "a": f"The FDIC institution record lists {name} at {place}.",
        })
    if bank.get("offices") is not None:
        faqs.append({
            "q": f"How many offices does {name} report?",
            "a": (
                f"The FDIC institution record lists {bank['offices']:,} domestic offices for {name}, "
                f"including the main office. A domestic office is a location where deposit accounts are opened, "
                f"deposits are accepted, checks are paid, or loans are granted."
            ),
        })
    return faqs


def cu_faqs(cu, quarter, quarter_name, published_nwr):
    name = cu["name"]
    faqs = [{
        "q": f"Is {name} federally insured?",
        "a": (
            f"Yes. {name} is on the NCUA list of federally insured credit unions. "
            f"The charter number is {cu['charter']}. "
            f"The standard NCUA share insurance limit is $250,000 per member, per insured credit union, "
            f"for each account ownership category. This page does not calculate coverage for a specific person."
        ),
    }]
    if quarter and quarter.get("shares") is not None:
        faqs.append({
            "q": f"How much does {name} report in shares and deposits for {quarter_name}?",
            "a": (
                f"For the quarter ending {nice_date(quarter['date'])}, the NCUA call report shows "
                f"{money(quarter['shares'])} of shares and deposits at {name}."
            ),
        })
    if quarter and quarter.get("assets") is not None:
        faqs.append({
            "q": f"How large is {name} by assets?",
            "a": (
                f"For the quarter ending {nice_date(quarter['date'])}, the NCUA call report shows "
                f"{money(quarter['assets'])} of total assets at {name}."
            ),
        })
    if published_nwr is not None:
        faqs.append({
            "q": f"What is {name}'s net worth ratio for {quarter_name}?",
            "a": (
                f"NCUA's federally insured credit union list reports a net worth ratio of {pct(published_nwr)} "
                f"for {name} in {quarter_name}. NCUA defines that list figure as net worth divided by total assets, "
                f"excluding the CECL transition provision. It is not a grade and it is not a prediction."
            ),
        })
    elif quarter and nwr(quarter) is not None:
        faqs.append({
            "q": f"What is {name}'s net worth ratio for {quarter_name}?",
            "a": (
                f"For {quarter_name}, net worth divided by total assets is {pct(nwr(quarter))} for {name}, "
                f"using the dollar amounts in the NCUA call report. It is not a grade and it is not a prediction."
            ),
        })
    if quarter and delinquency(quarter) is not None:
        faqs.append({
            "q": f"What share of {name}'s loans are delinquent?",
            "a": (
                f"For {quarter_name}, loans and leases delinquent two months or more are {pct(delinquency(quarter))} "
                f"of total loans and leases at {name}. The percent is computed from the dollar amounts in the call report. "
                f"It is not the same measure as a bank's noncurrent-loan ratio, which uses 90 days and nonaccrual."
            ),
        })
    if cu.get("roa") is not None and cu.get("list_quarter") == (quarter or {}).get("date"):
        faqs.append({
            "q": f"What was {name}'s return on average assets for {quarter_name}?",
            "a": (
                f"NCUA's federally insured credit union list reports return on average assets of {pct(cu['roa'])} "
                f"for {name} in {quarter_name}."
            ),
        })
    place = hq_line([cu.get("hq_address"), cu.get("hq_city"), " ".join(bit for bit in [cu.get("hq_state"), cu.get("hq_zip")] if bit)])
    if place:
        faqs.append({
            "q": f"Where is {name} headquartered?",
            "a": f"The NCUA record lists {name} at {place}.",
        })
    if cu.get("branches") is not None:
        faqs.append({
            "q": f"How many branches does {name} report?",
            "a": (
                f"The NCUA branch file for this quarter lists {cu['branches']:,} branch offices for {name}"
                + (
                    f" and {cu['corporate_offices']:,} corporate "
                    + ("office." if cu["corporate_offices"] == 1 else "offices.")
                    if cu.get("corporate_offices") else "."
                )
            ),
        })
    return faqs


def describe_bank(bank, quarter, quarter_name):
    bits = [f"FDIC certificate {bank['cert']}."]
    place = ", ".join(part for part in [bank.get("city"), bank.get("state_name") or bank.get("state")] if part)
    if place:
        bits.append(f"{bank['name']} is in {place}.")
    if quarter:
        bits.append(f"{quarter_name}:")
        if quarter.get("deposits") is not None:
            bits.append(f"deposits {money(quarter['deposits'])},")
        if quarter.get("rbc") is not None:
            bits.append(f"total risk-based capital ratio {pct(quarter['rbc'])},")
        if quarter.get("npl") is not None:
            bits.append(f"noncurrent loans {pct(quarter['npl'])},")
        if quarter.get("roa") is not None:
            bits.append(f"ROA {pct(quarter['roa'])}.")
    bits.append("Official FDIC numbers, not a safety rating.")
    return " ".join(bits).replace(" ,", ",").replace(", .", ".")


def describe_cu(cu, quarter, quarter_name, published_nwr):
    bits = [f"NCUA charter {cu['charter']}."]
    place = ", ".join(part for part in [cu.get("city"), STATE_NAMES.get(cu.get("state"), cu.get("state"))] if part)
    if place:
        bits.append(f"{cu['name']} is in {place}.")
    if quarter and quarter.get("shares") is not None:
        bits.append(f"{quarter_name} shares and deposits {money(quarter['shares'])}.")
    if published_nwr is not None:
        bits.append(f"Net worth ratio {pct(published_nwr)}.")
    elif quarter and nwr(quarter) is not None:
        bits.append(f"Net worth divided by assets {pct(nwr(quarter))}.")
    bits.append("Official NCUA numbers, not a safety rating.")
    return " ".join(bits)


def sitemap(pages):
    groups = [pages[i:i + SITEMAP_LIMIT] for i in range(0, len(pages), SITEMAP_LIMIT)] or [[]]
    names = []
    if len(groups) == 1:
        names.append("sitemap.xml")
        write("sitemap.xml", urlset(groups[0]))
        return
    for index, group in enumerate(groups, start=1):
        name = f"sitemap-{index}.xml"
        names.append(name)
        write(name, urlset(group))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for name in names:
        lines.append(f"  <sitemap><loc>{escape(PUBLIC + '/' + name)}</loc></sitemap>")
    lines.append("</sitemapindex>")
    write("sitemap.xml", "\n".join(lines) + "\n")


def urlset(pages):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, day in pages:
        loc = escape(PUBLIC + path)
        lines.append(f"  <url><loc>{loc}</loc><lastmod>{day}</lastmod></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def main():
    bank_doc = load_json("banks.json")
    cu_doc = load_json("credit_unions.json")
    fail_doc = load_json("failures.json")
    offers = https_offers(load_yaml("offers.yml").get("offers"))
    newsletter = newsletter_config(load_yaml("newsletter.yml"))
    military_cfg = load_yaml("military.yml")

    banks = bank_doc["banks"]
    credit_unions = cu_doc["credit_unions"]
    failures = fail_doc["failures"]
    bank_as_of = bank_doc["meta"]["as_of"]
    cu_as_of = cu_doc["meta"]["as_of"]
    bank_quarter = bank_doc["meta"]["quarter"]
    cu_quarter = cu_doc["meta"]["quarter"]
    if bank_quarter == cu_quarter:
        as_of_bar = f"Figures as of {bank_quarter}"
    else:
        as_of_bar = f"Banks as of {bank_quarter}. Credit unions as of {cu_quarter}."
    checked = max(bank_doc["meta"]["fetched_at"], cu_doc["meta"]["fetched_at"])[:10]

    rbc_share, rbc_n = lower_share(
        (bank["cert"], (latest_on(bank["quarters"], bank_as_of) or {}).get("rbc")) for bank in banks
    )
    npl_share, npl_n = lower_share(
        (bank["cert"], (latest_on(bank["quarters"], bank_as_of) or {}).get("npl")) for bank in banks
    )
    roa_share, roa_n = lower_share(
        (bank["cert"], (latest_on(bank["quarters"], bank_as_of) or {}).get("roa")) for bank in banks
    )
    cu_nwr_share, cu_nwr_n = lower_share(
        (cu["charter"], cu.get("net_worth_ratio") if cu.get("list_quarter") == cu_as_of else nwr(latest_on(cu["quarters"], cu_as_of)))
        for cu in credit_unions
    )
    cu_dlq_share, cu_dlq_n = lower_share(
        (cu["charter"], delinquency(latest_on(cu["quarters"], cu_as_of))) for cu in credit_unions
    )
    cu_roa_share, cu_roa_n = lower_share(
        (cu["charter"], cu.get("roa") if cu.get("list_quarter") == cu_as_of else None) for cu in credit_unions
    )

    for bank in banks:
        bank["state_name"] = state_name(bank.get("state"), bank.get("state_name"))
        bank["path"] = f"/bank/{bank['cert']}-{bank['slug']}/"
        bank["latest"] = latest_on(bank["quarters"], bank_as_of) or (bank["quarters"][-1] if bank["quarters"] else None)
        bank["quarters"] = sorted(bank["quarters"], key=lambda item: item["date"])
        for quarter in bank["quarters"]:
            quarter["equity_ratio"] = None if equity_ratio(quarter) is None else round(equity_ratio(quarter), 4)
            quarter["quarter"] = quarter_label(quarter["date"])
        if bank["latest"] and bank["latest"]["date"] == bank_as_of:
            bank["rbc_share"] = rbc_share.get(bank["cert"])
            bank["npl_share"] = npl_share.get(bank["cert"])
            bank["roa_share"] = roa_share.get(bank["cert"])
        else:
            bank["rbc_share"] = bank["npl_share"] = bank["roa_share"] = None
        bank["spark_rbc"] = Markup(sparkline([q.get("rbc") for q in bank["quarters"]]))
        bank["spark_npl"] = Markup(sparkline([q.get("npl") for q in bank["quarters"]]))
        bank["spark_roa"] = Markup(sparkline([q.get("roa") for q in bank["quarters"]]))

    for cu in credit_unions:
        cu["state_name"] = state_name(cu.get("state"))
        cu["path"] = f"/credit-union/{cu['charter']}-{cu['slug']}/"
        cu["quarters"] = sorted(cu["quarters"], key=lambda item: item["date"])
        cu["latest"] = latest_on(cu["quarters"], cu_as_of) or (cu["quarters"][-1] if cu["quarters"] else None)
        for quarter in cu["quarters"]:
            quarter["nwr"] = None if nwr(quarter) is None else round(nwr(quarter), 4)
            quarter["dlq"] = None if delinquency(quarter) is None else round(delinquency(quarter), 4)
            quarter["quarter"] = quarter_label(quarter["date"])
        same_list = cu.get("list_quarter") == cu_as_of
        cu["published_nwr"] = cu.get("net_worth_ratio") if same_list else None
        cu["published_roa"] = cu.get("roa") if same_list else None
        if cu["latest"] and cu["latest"]["date"] == cu_as_of:
            cu["nwr_share"] = cu_nwr_share.get(cu["charter"])
            cu["dlq_share"] = cu_dlq_share.get(cu["charter"])
            cu["roa_share"] = cu_roa_share.get(cu["charter"]) if same_list else None
        else:
            cu["nwr_share"] = cu["dlq_share"] = cu["roa_share"] = None
        cu["type_label"] = CU_TYPES.get(cu.get("cu_type") or "", cu.get("cu_type") or "")
        cu["spark_nwr"] = Markup(sparkline([q.get("nwr") for q in cu["quarters"]]))
        cu["spark_dlq"] = Markup(sparkline([q.get("dlq") for q in cu["quarters"]]))
        shown = []
        for trade in cu.get("trade_names") or []:
            if trade.lower() != cu["name"].lower() and trade.lower() != cu["official_name"].lower():
                shown.append(trade)
        cu["trade_names"] = shown

    phrases = military_cfg.get("phrases") or []
    extra = {int(item) for item in military_cfg.get("extra_charters") or []}
    excluded = {int(item) for item in military_cfg.get("exclude_charters") or []}
    military = []
    for cu in credit_unions:
        if cu["charter"] in excluded:
            continue
        reason = None
        for phrase in sorted(phrases, key=len, reverse=True):
            if contains_phrase(cu["official_name"], phrase) or contains_phrase(cu["name"], phrase):
                reason = f'NCUA name contains "{phrase.title() if phrase != "NCUA" else phrase}".'
                break
            for trade in cu.get("trade_names") or []:
                if contains_phrase(trade, phrase):
                    reason = f'NCUA trade name contains "{phrase.title()}": {trade}.'
                    break
            if reason:
                break
        if reason is None and cu["charter"] in extra:
            trades = ", ".join(cu["trade_names"]) if cu["trade_names"] else "none on file"
            reason = (
                f"Charter {cu['charter']} is on this page's short-name list. "
                f"NCUA name: {cu['official_name']}, {cu['city']}, {cu['state']}. Trade names: {trades}."
            )
        if reason:
            cu["military_reason"] = reason
            military.append(cu)
    military.sort(key=lambda item: ((item["latest"] or {}).get("assets") or 0), reverse=True)

    by_state = defaultdict(list)
    cu_by_state = defaultdict(list)
    for bank in banks:
        if bank.get("state"):
            by_state[bank["state"]].append(bank)
    for cu in credit_unions:
        if cu.get("state"):
            cu_by_state[cu["state"]].append(cu)
    for rows in by_state.values():
        rows.sort(key=lambda item: ((item["latest"] or {}).get("assets") or 0), reverse=True)
    for rows in cu_by_state.values():
        rows.sort(key=lambda item: ((item["latest"] or {}).get("assets") or 0), reverse=True)

    today = dt.date.today().isoformat()
    recent_cut = (dt.date.today() - dt.timedelta(days=730)).isoformat()
    recent_failures = [item for item in failures if item.get("date") and item["date"] >= recent_cut]

    search = []
    for bank in banks:
        where = ", ".join(part for part in [bank.get("city"), bank.get("state")] if part)
        hay = " ".join(str(part) for part in [
            bank["name"], bank["official_name"], bank.get("city"), bank.get("state_name"),
            bank.get("state"), bank["cert"],
        ] if part).lower()
        search.append({
            "k": "b", "name": bank["name"], "where": where, "id": bank["cert"],
            "u": bank["path"], "h": hay,
        })
    for cu in credit_unions:
        where = ", ".join(part for part in [cu.get("city"), cu.get("state")] if part)
        hay = " ".join(str(part) for part in [
            cu["name"], cu["official_name"], " ".join(cu.get("trade_names") or []),
            cu.get("city"), cu.get("state_name"), cu.get("state"), cu["charter"],
        ] if part).lower()
        search.append({
            "k": "c", "name": cu["name"], "where": where, "id": cu["charter"],
            "u": cu["path"], "h": hay,
        })
    for failure in failures:
        where = ", ".join(part for part in [failure.get("city"), failure.get("state")] if part)
        hay = " ".join(str(part) for part in [
            failure["name"], failure["official_name"], failure.get("city"), failure.get("state"),
            failure.get("cert"), "failed",
        ] if part).lower()
        search.append({
            "k": "f", "name": failure["name"], "where": where,
            "id": failure.get("cert") or failure.get("fdic_id"),
            "u": f"/failures/#f-{failure['fdic_id']}", "h": hay,
            "date": failure.get("date") or "",
        })

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(ROOT / "static", OUT / "static")
    (OUT / "search-index.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")))

    common = dict(
        base=BASE, site_url=SITE_URL, public_url=PUBLIC, site_name=SITE_NAME,
        contact=CONTACT, footer=FOOTER, as_of_bar=as_of_bar, checked=checked,
        bank_quarter=bank_quarter, cu_quarter=cu_quarter, year=dt.date.today().year,
        offers=offers, newsletter=newsletter,
    )
    pages = []

    def render(template, rel, **kwargs):
        html = env.get_template(template).render(**common, **kwargs)
        write(rel, html)

    state_links = []
    for code in sorted(by_state, key=lambda item: state_name(item, by_state[item][0].get("state_name"))):
        rows = by_state[code]
        state_links.append({
            "code": code,
            "name": rows[0]["state_name"],
            "banks": len(rows),
            "credit_unions": len(cu_by_state.get(code, [])),
            "path": f"/state/{code.lower()}/",
            "cu_path": f"/credit-unions/state/{code.lower()}/" if code in cu_by_state else "",
        })

    render(
        "index.html", "index.html",
        page_title="Is my bank safe? FDIC insurance, capital and deposits",
        description=(
            f"Look up any FDIC-insured U.S. bank or federally insured credit union. "
            f"Deposits, capital, noncurrent loans, and return on assets as of {bank_quarter}. "
            f"No login and no safety score."
        ),
        canonical="/",
        bank_count=len(banks), cu_count=len(credit_unions),
        recent_failures=recent_failures[:12], recent_count=len(recent_failures),
        failure_count=len(failures), states=state_links,
    )
    pages.append(("/", today))

    render(
        "states.html", "states/index.html",
        page_title=f"Banks by state: capital and health data ({bank_quarter})",
        description=f"FDIC deposits, capital ratios, noncurrent loans, and ROA for active banks in every state, as of {bank_quarter}.",
        canonical="/states/", states=state_links,
    )
    pages.append(("/states/", today))

    for code, rows in by_state.items():
        name = rows[0]["state_name"]
        path = f"/state/{code.lower()}/"
        render(
            "state.html", f"state/{code.lower()}/index.html",
            page_title=f"Banks in {name}: capital and health data ({bank_quarter})",
            description=(
                f"{len(rows)} active FDIC-insured banks in {name}. Deposits, total risk-based capital ratio, "
                f"noncurrent loans, and ROA as of {bank_quarter}."
            ),
            canonical=path, state_name=name, state_code=code, rows=rows,
            cu_count=len(cu_by_state.get(code, [])),
            cu_path=f"/credit-unions/state/{code.lower()}/" if code in cu_by_state else "",
        )
        pages.append((path, bank_as_of))

    for bank in banks:
        quarter = bank["latest"]
        qname = quarter_label(quarter["date"]) if quarter else bank_quarter
        faqs = bank_faqs(bank, quarter if quarter and quarter["date"] == bank_as_of else quarter, qname, bank["rbc_share"], rbc_n)
        if quarter:
            page_title = f"Is {bank['name']} safe? FDIC insurance, capital & health ({qname})"
        else:
            page_title = f"Is {bank['name']} safe? FDIC insurance status"
        render(
            "bank.html", f"bank/{bank['cert']}-{bank['slug']}/index.html",
            page_title=page_title,
            description=describe_bank(bank, quarter, qname),
            canonical=bank["path"], bank=bank, faqs=faqs, faq_ld=faq_block(faqs),
            rbc_n=rbc_n, npl_n=npl_n, roa_n=roa_n, qname=qname,
        )
        pages.append((bank["path"], (quarter or {}).get("date") or bank_as_of))

    render(
        "failures.html", "failures/index.html",
        page_title="Failed U.S. banks",
        description=(
            f"Banks the FDIC records as failures. {len(failures)} records with resolution type FAILURE. "
            f"This is a historical list, not a forecast."
        ),
        canonical="/failures/", failures=failures,
        other_resolutions={
            key: value for key, value in (fail_doc["meta"].get("resolution_counts") or {}).items()
            if key and key != "FAILURE"
        },
    )
    pages.append(("/failures/", failures[0]["date"] if failures else today))

    cu_state_links = []
    for code in sorted(cu_by_state, key=lambda item: state_name(item)):
        rows = cu_by_state[code]
        cu_state_links.append({
            "code": code, "name": state_name(code), "count": len(rows),
            "path": f"/credit-unions/state/{code.lower()}/",
            "bank_path": f"/state/{code.lower()}/" if code in by_state else "",
        })
    render(
        "credit_unions.html", "credit-unions/index.html",
        page_title=f"Federally insured credit unions ({cu_quarter})",
        description=(
            f"NCUA share insurance, net worth, shares and deposits, and delinquency for "
            f"{len(credit_unions)} federally insured credit unions, as of {cu_quarter}."
        ),
        canonical="/credit-unions/", states=cu_state_links, cu_count=len(credit_unions),
        military_count=len(military),
    )
    pages.append(("/credit-unions/", today))

    for code, rows in cu_by_state.items():
        name = state_name(code)
        path = f"/credit-unions/state/{code.lower()}/"
        render(
            "cu_state.html", f"credit-unions/state/{code.lower()}/index.html",
            page_title=f"Credit unions in {name}: net worth and deposits ({cu_quarter})",
            description=(
                f"{len(rows)} federally insured credit unions in {name}. Assets, shares and deposits, "
                f"and net worth ratio as of {cu_quarter}."
            ),
            canonical=path, state_name=name, state_code=code, rows=rows,
            bank_path=f"/state/{code.lower()}/" if code in by_state else "",
        )
        pages.append((path, cu_as_of))

    for cu in credit_unions:
        quarter = cu["latest"]
        qname = quarter_label(quarter["date"]) if quarter else cu_quarter
        faqs = cu_faqs(cu, quarter, qname, cu["published_nwr"])
        if quarter:
            page_title = f"Is {cu['name']} safe? NCUA insurance, net worth & deposits ({qname})"
        else:
            page_title = f"Is {cu['name']} safe? NCUA insurance status"
        render(
            "credit_union.html", f"credit-union/{cu['charter']}-{cu['slug']}/index.html",
            page_title=page_title,
            description=describe_cu(cu, quarter, qname, cu["published_nwr"]),
            canonical=cu["path"], cu=cu, faqs=faqs, faq_ld=faq_block(faqs),
            nwr_n=cu_nwr_n, dlq_n=cu_dlq_n, roa_n=cu_roa_n, qname=qname,
        )
        pages.append((cu["path"], (quarter or {}).get("date") or cu_as_of))

    render(
        "military.html", "credit-unions/military/index.html",
        page_title="Military and veteran credit unions",
        description=(
            "Federally insured credit unions whose NCUA name or trade name refers to the military or veterans, "
            "plus a short list of installation and service names. Not an NCUA category and not a safety ranking."
        ),
        canonical="/credit-unions/military/", rows=military, phrases=phrases,
        extra_charters=sorted(extra),
    )
    pages.append(("/credit-unions/military/", cu_as_of))

    render(
        "methodology.html", "methodology/index.html",
        page_title="Methodology: FDIC and NCUA figures",
        description="How this site reads FDIC BankFind and NCUA call reports, which fields it shows, and what it does not calculate.",
        canonical="/methodology/",
        bank_meta=bank_doc["meta"], cu_meta=cu_doc["meta"], fail_meta=fail_doc["meta"],
        rbc_n=rbc_n, npl_n=npl_n, roa_n=roa_n, cu_nwr_n=cu_nwr_n, cu_dlq_n=cu_dlq_n, cu_roa_n=cu_roa_n,
        phrases=phrases, extra_charters=sorted(extra),
    )
    pages.append(("/methodology/", today))

    render(
        "about.html", "about/index.html",
        page_title=f"About {SITE_NAME}",
        description=f"Who runs {SITE_NAME}, where the FDIC and NCUA figures come from, and why the site does not rate banks.",
        canonical="/about/",
    )
    pages.append(("/about/", today))
    render(
        "disclosure.html", "disclosure/index.html",
        page_title=f"Affiliate disclosure | {SITE_NAME}",
        description="Some links may be affiliate links. A commission does not change FDIC or NCUA figures.",
        canonical="/disclosure/",
    )
    pages.append(("/disclosure/", today))
    render(
        "privacy.html", "privacy/index.html",
        page_title=f"Privacy | {SITE_NAME}",
        description=f"{SITE_NAME} is a static site with no accounts and no cookies of its own.",
        canonical="/privacy/",
    )
    pages.append(("/privacy/", today))
    render("404.html", "404.html", page_title="Page not found", description="", canonical="/404.html")

    sitemap(pages)
    write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {PUBLIC}/sitemap.xml\n")
    (OUT / ".nojekyll").write_text("")
    counts = {
        "banks": len(banks),
        "credit_unions": len(credit_unions),
        "states": len(by_state),
        "credit_union_states": len(cu_by_state),
        "failures": len(failures),
        "military": len(military),
        "sitemap_urls": len(pages),
        "bank_quarter": bank_quarter,
        "cu_quarter": cu_quarter,
        "offers": len(offers),
        "newsletter": bool(newsletter["url"]),
    }
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
