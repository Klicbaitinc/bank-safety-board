#!/usr/bin/env python3
"""Fail the build if pages, sitemap, or the no-rating rule look wrong."""
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "scripts"))
from siteconfig import BASE, PUBLIC  # noqa: E402

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BANNED = (
    "safety score",
    "star rating",
    "letter grade",
    "out of 5",
    "failure prediction",
    "likely to fail",
    "predicted to fail",
)
FOOTER = "Data from FDIC and NCUA public records. Not financial advice. Not affiliated with the FDIC or NCUA. Some links may be affiliate links."


def read(rel):
    path = SITE / rel
    if not path.exists():
        raise SystemExit(f"missing {rel}")
    return path.read_text(errors="replace")


def main():
    home = read("index.html")
    for needle in (
        FOOTER,
        "See disclosure",
        f'href="{BASE}/static/style.css"',
        f'href="{PUBLIC}/"',
        "FDIC-insured",
        "Is my bank safe?",
    ):
        if needle not in home:
            raise SystemExit(f"homepage missing {needle!r}")
    if 'class="offer"' in home or 'id="newsletter"' in home:
        raise SystemExit("empty affiliate or newsletter slot is visible")

    jpm_paths = list(SITE.glob("bank/628-*/index.html"))
    if len(jpm_paths) != 1:
        raise SystemExit(f"expected one JPM page, found {jpm_paths}")
    jpm = jpm_paths[0].read_text(errors="replace")
    for needle in ("FDIC insured: Yes", "Certificate number", ">628<", "trillion", "Total risk-based capital ratio", "FAQPage"):
        if needle not in jpm:
            raise SystemExit(f"JPM page missing {needle!r}")
    if f'href="{PUBLIC}/bank/628-' not in jpm:
        raise SystemExit("JPM canonical is wrong")
    if "banks.data.fdic.gov/bankfind-suite/bankfind/details/628" not in jpm:
        raise SystemExit("JPM page missing BankFind link")
    low = jpm.lower()
    for phrase in BANNED:
        if phrase in low:
            raise SystemExit(f"JPM page contains banned phrase {phrase!r}")
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', jpm, re.S)
    if not ld:
        raise SystemExit("JPM page missing JSON-LD")
    data = json.loads(ld.group(1))
    if data.get("@type") != "FAQPage":
        raise SystemExit("JSON-LD is not FAQPage")
    questions = [item["name"] for item in data["mainEntity"]]
    if not any(q.startswith("Is ") and "FDIC insured" in q for q in questions):
        raise SystemExit(f"FAQ questions do not include insurance: {questions}")
    for question in questions:
        if question not in jpm:
            raise SystemExit(f"FAQ question not visible: {question}")

    navy_dir = next(SITE.glob("credit-union/5536-*"))
    navy = (navy_dir / "index.html").read_text(errors="replace")
    for needle in ("Federally insured: Yes", "5536", "Net worth", "Shares and deposits"):
        if needle not in navy:
            raise SystemExit(f"Navy Federal page missing {needle!r}")

    failures = read("failures/index.html")
    if "Silicon Valley Bank" not in failures and "SILICON VALLEY" not in failures.upper():
        raise SystemExit("failures page missing Silicon Valley Bank")
    military = read("credit-unions/military/index.html")
    for needle in ("Navy Federal", "Pentagon", "24921", "not a safety ranking"):
        if needle not in military:
            raise SystemExit(f"military page missing {needle!r}")
    if "66530" not in military:
        raise SystemExit("military page should name the Green Bay SERVICE charter it excludes")

    state = read("state/nv/index.html")
    if "Banks in Nevada: capital and health data" not in state:
        raise SystemExit("Nevada title is wrong")
    if "sortable" not in state:
        raise SystemExit("Nevada table is not sortable")

    robots = read("robots.txt")
    if f"Sitemap: {PUBLIC}/sitemap.xml" not in robots:
        raise SystemExit("robots.txt sitemap URL is wrong")

    root = ElementTree.parse(SITE / "sitemap.xml").getroot()
    tag = root.tag.split("}")[-1]
    locs = []
    if tag == "sitemapindex":
        for node in root.findall("s:sitemap/s:loc", NS):
            name = node.text.rstrip("/").split("/")[-1]
            child = ElementTree.parse(SITE / name).getroot()
            locs.extend(item.text for item in child.findall("s:url/s:loc", NS))
    else:
        locs = [item.text for item in root.findall("s:url/s:loc", NS)]
    if len(locs) != len(set(locs)):
        raise SystemExit("sitemap has duplicate URLs")
    if len(locs) < 8000:
        raise SystemExit(f"sitemap unexpectedly small: {len(locs)}")
    missing = 0
    for loc in locs:
        if not loc.startswith(PUBLIC + "/"):
            raise SystemExit(f"bad sitemap loc {loc}")
        path = loc[len(PUBLIC):]
        rel = "index.html" if path == "/" else path.strip("/") + "/index.html"
        if not (SITE / rel).exists():
            missing += 1
            if missing <= 5:
                print("missing file for", loc)
    if missing:
        raise SystemExit(f"{missing} sitemap URLs have no file")

    index = json.loads((SITE / "search-index.json").read_text())
    kinds = {item["k"] for item in index}
    if kinds != {"b", "c", "f"}:
        raise SystemExit(f"search kinds {kinds}")
    print(f"ok pages={len(locs)} search={len(index)} public={PUBLIC}")


if __name__ == "__main__":
    main()
