# Bank Safety & Savings Board

Free, no-login static site that answers “Is my bank safe?” with official FDIC and NCUA numbers for every active FDIC-insured bank and every federally insured credit union. No letter grades, star ratings, safety scores, or failure predictions.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# FDIC and NCUA requests use this contact string. A repository variable named
# FDIC_USER_AGENT overrides it in GitHub Actions.
export FDIC_USER_AGENT="BankSafetySavingsBoard kennethdavis+banks@mail.grokbot.com"
.venv/bin/python scripts/fetch_fdic.py          # writes data/banks.json and data/failures.json
.venv/bin/python scripts/fetch_ncua.py          # writes data/credit_unions.json
# Add --refresh to re-download. Cached responses live in data/cache/ and are not committed.
# Defaults match the GitHub Pages project site.
# export SITE_URL=https://klicbaitinc.github.io
# export BASE_PATH=/bank-safety-board
.venv/bin/python scripts/build_site.py          # writes site/
.venv/bin/python scripts/check_site.py
python3 -m http.server 8765 -d site             # open http://localhost:8765
```

## Pages

* `/` searches a JSON index of banks, credit unions, and failed banks, and links to every state.
* `/bank/<cert>-<slug>/` is one active FDIC-insured bank: insurance, deposits, assets, capital ratios, noncurrent loans, ROA, an eight-quarter table, offices, and the FDIC BankFind link.
* `/state/<st>/` is a sortable list of banks in that state.
* `/failures/` lists FDIC records with resolution type FAILURE.
* `/credit-union/<charter>-<slug>/` is one federally insured credit union.
* `/credit-unions/military/` lists credit unions whose NCUA name refers to the military or veterans, plus a short configured list of installation and service names.
* `/methodology/`, `/disclosure/`, `/privacy/`, `/about/`.

Dollar amounts from FDIC are published in thousands and multiplied by 1,000 here. NCUA call-report amounts are already in dollars. The as-of quarter is printed on every page.

## Offers and newsletter

`config/offers.yml` is the high-yield savings slot on the homepage and bank pages. `config/newsletter.yml` is the newsletter link. Both stay off the pages while their URL fields are empty. Only `https://` URLs are rendered.

## Deploy

`.github/workflows/refresh-and-deploy.yml` refreshes FDIC and NCUA data, commits the JSON files back to `main`, builds the site, and deploys to GitHub Pages.

* Live site: https://klicbaitinc.github.io/bank-safety-board/
* Schedule: `20 7 * * *` (07:20 UTC daily), plus every push to `main` and manual dispatch.
* Requests use `BankSafetySavingsBoard kennethdavis+banks@mail.grokbot.com` unless the `FDIC_USER_AGENT` repository variable is set.
* Pages source must be **GitHub Actions**. The workflow calls `actions/configure-pages` with `enablement: true`, which tries to turn Pages on when the token is allowed to.
