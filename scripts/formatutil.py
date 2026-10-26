"""Formatting helpers. FDIC dollar fields arrive in thousands; callers convert first."""
import datetime as dt
import re
import unicodedata

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}

BKCLASS = {
    "N": "National bank, supervised by the OCC",
    "NM": "State nonmember bank, supervised by the FDIC",
    "SM": "State member bank, supervised by the Federal Reserve",
    "SB": "Federal savings bank, supervised by the OCC",
    "SA": "Savings association",
    "SI": "State-chartered savings bank, supervised by the FDIC",
    "SL": "State-chartered savings and loan association",
    "OI": "Insured U.S. branch of a foreign bank",
}

CU_TYPES = {
    "FCU": "Federal credit union",
    "FISCU": "Federally insured, state-chartered credit union",
}

_KEEP = {"FCU", "N.A.", "NA", "FSB", "SSB", "USA", "US", "FDIC", "NCUA", "DC", "NJ", "NY"}


def parse_date(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    text = text.split()[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def quarter_label(iso_date):
    if not iso_date:
        return ""
    year, month, _day = iso_date.split("-")
    quarter = {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}.get(month)
    if not quarter:
        return iso_date
    return f"{quarter} {year}"


def nice_date(value):
    if not value:
        return ""
    if isinstance(value, str):
        value = dt.date.fromisoformat(value[:10])
    return value.strftime("%b %-d, %Y")


def _nice_token(word):
    def repl(match):
        token = match.group(0)
        if token.upper() in _KEEP:
            return token.upper()
        lower = token.lower()
        if lower.startswith("mc") and len(lower) > 2 and lower[2].isalpha():
            return "Mc" + lower[2].upper() + lower[3:]
        return token[0].upper() + token[1:].lower()

    return re.sub(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", repl, word)


def nice_name(name):
    """Make an ALL-CAPS filing name readable. Leave mixed-case names alone."""
    if not name:
        return ""
    name = str(name).strip()
    letters = [c for c in name if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return name
    small = {"of", "and", "the", "for", "in", "a"}
    out = []
    words = name.split()
    for i, word in enumerate(words):
        core = word.strip(",.")
        if core.upper() in _KEEP:
            out.append(word.upper() if word.upper() == core.upper() else word)
            continue
        if i and core.lower() in small:
            out.append(core.lower() + word[len(core):])
            continue
        if len(core) == 2 and core.isalpha():
            out.append(core.upper() + word[len(core):])
            continue
        out.append(_nice_token(word))
    return " ".join(out)


def slugify(name, limit=72):
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    text = text[:limit].strip("-")
    return text or "institution"


def money(value):
    if value is None:
        return "—"
    number = float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000_000:
        body = f"${number / 1_000_000_000_000:.2f} trillion"
    elif number >= 1_000_000_000:
        body = f"${number / 1_000_000_000:.2f} billion"
    elif number >= 1_000_000:
        body = f"${number / 1_000_000:.1f} million"
    else:
        body = f"${number:,.0f}"
    return sign + body


def pct(value, digits=2):
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}%"


def comma(value):
    if value is None:
        return "—"
    return f"{int(round(float(value))):,}"


def parse_num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text.lower() in {"null", "na", "n/a", "none"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def dollars_from_thousands(value):
    number = parse_num(value)
    if number is None:
        return None
    return int(round(number * 1000))


def ratio(value, digits=4):
    number = parse_num(value)
    if number is None:
        return None
    return round(number, digits)


def clean_web(value):
    if not value:
        return None
    text = str(value).strip()
    if text.lower() in {"0", "none", "n/a", "na", "null", "http://", "https://"}:
        return None
    if text.startswith("http://"):
        text = "https://" + text[len("http://"):]
    elif not text.startswith("https://"):
        text = "https://" + text.lstrip("/")
    if " " in text or "." not in text:
        return None
    return text


def zip_code(value):
    if value is None:
        return ""
    if isinstance(value, float):
        value = str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    if len(digits) == 4:
        return digits.zfill(5)
    if len(digits) in {5, 9}:
        if len(digits) == 9:
            return f"{digits[:5]}-{digits[5:]}"
        return digits
    return text


def sparkline(values, width=320, height=72):
    """Decorative polyline. The data table next to it is the accessible version."""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    pad = (hi - lo) * 0.12 or 1.0
    lo -= pad
    hi += pad
    span = hi - lo
    n = len(values)
    coords = []
    for i, value in enumerate(values):
        if value is None:
            continue
        x = 8 + (width - 16) * (i / (n - 1))
        y = 8 + (height - 16) * (1 - (value - lo) / span)
        coords.append((x, y))
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    lx, ly = coords[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-hidden="true" focusable="false">'
        f'<polyline fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" '
        f'stroke-linecap="round" points="{points}"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.2" fill="currentColor"/></svg>'
    )


def median(values):
    nums = sorted(v for v in values if v is not None)
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2


def assert_scale(name, values, low, high):
    nums = [v for v in values if v is not None]
    if len(nums) < 50:
        print(f"scale {name}: only {len(nums)} values, skipped")
        return
    mid = median(nums)
    print(f"scale {name}: median {mid:.4f} n={len(nums)}")
    if mid < low or mid > high:
        raise SystemExit(f"median {name} {mid} is outside {low}..{high}; refusing to publish a bad scale")
