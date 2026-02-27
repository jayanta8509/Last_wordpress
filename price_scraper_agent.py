"""
Price Scraper Agent v3
======================
Multi-strategy pipeline — extracts REAL prices from any sales page.

Strategy order:
  1. Fetch main page + follow affiliate redirect if detected
  2. Regex scan on full raw HTML (all currency formats)
  3. DOM targeted scan (price-hinted elements)
  4. JSON-LD / schema.org / OpenGraph structured data
  5. Strikethrough <s>/<del> tag detection (original vs sale price)
  6. CTA button text extraction (often contains price)
  7. Urgency / scarcity signals
  8. GPT-4o reads full visible page text and finds prices directly
     (never invents — returns null if truly not found)
"""

import re
import json
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ──────────────────────────────────────────────────────────────────
#  CONSTANTS
# ──────────────────────────────────────────────────────────────────

PRICE_RE = re.compile(
    r"""
    (?:
        (?P<sym1>[\$\xA3\u20AC\xA5\u20B9\u20A9\u20BD])
        \s*
        (?P<amt1>\d{1,5}(?:[.,]\d{2,3})?)
    )
    |
    (?:
        (?P<amt2>\d{1,5}(?:[.,]\d{2,3})?)
        \s*
        (?P<sym2>USD|GBP|EUR|CAD|AUD|INR)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

PRICE_CLASS_HINTS = [
    "price", "pricing", "cost", "amount", "offer", "discount",
    "sale", "original", "regular", "special", "today", "checkout",
    "total", "fee", "rate", "plan", "tier", "buy", "order",
    "woo", "product", "cart", "upsell", "downsell", "oto",
]

CTA_KEYWORDS = [
    "buy", "get", "order", "purchase", "access", "claim", "grab",
    "start", "join", "enroll", "subscribe", "download", "instant",
    "yes", "add to cart", "checkout", "pay", "secure", "unlock",
]

URGENCY_RE = re.compile(
    r"(only\s+\d+\s+(?:left|remaining|spots?|copies|seats?)|"
    r"limited\s+time|expires?\s+(?:in|soon)|"
    r"today\s+only|price\s+(?:goes?\s+up|increases?)|"
    r"hurry|don'?t\s+miss|last\s+chance|ends?\s+(?:soon|tonight|today)|"
    r"countdown|timer|\d+\s+hours?\s+(?:left|remaining))",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ──────────────────────────────────────────────────────────────────
#  STEP 1 — FETCH (follows meta-refresh + iframe embeds)
# ──────────────────────────────────────────────────────────────────

def fetch_page(url):
    pages = []
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        r = session.get(url, timeout=25, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        pages.append({"url": r.url, "soup": soup, "html": r.text})

        # Follow meta-refresh redirect
        meta_refresh = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta_refresh:
            content = meta_refresh.get("content", "")
            m = re.search(r"url=(.+)", content, re.I)
            if m:
                rurl = m.group(1).strip().strip("'\"")
                if rurl.startswith("http"):
                    try:
                        r2 = session.get(rurl, timeout=20, allow_redirects=True)
                        soup2 = BeautifulSoup(r2.content, "html.parser")
                        pages.append({"url": r2.url, "soup": soup2, "html": r2.text})
                    except Exception:
                        pass

        return {"ok": True, "pages": pages}
    except Exception as e:
        return {"ok": False, "pages": [], "error": str(e)}


# ──────────────────────────────────────────────────────────────────
#  STEP 2 — REGEX EXTRACTION
# ──────────────────────────────────────────────────────────────────

def _normalise(raw):
    try:
        return float(raw.replace(",", "").replace(" ", ""))
    except Exception:
        return None


def regex_extract_prices(html):
    prices = set()
    for m in PRICE_RE.finditer(html):
        amt_str = m.group("amt1") or m.group("amt2")
        amt = _normalise(amt_str)
        if amt and 0.99 <= amt <= 9999:
            prices.add(round(amt, 2))
    return sorted(prices)


# ──────────────────────────────────────────────────────────────────
#  STEP 3 — DOM TARGETED EXTRACTION
# ──────────────────────────────────────────────────────────────────

def dom_extract_prices(soup):
    found = []
    if soup is None:
        return found
    seen_amounts = set()
    for el in soup.find_all(True):
        classes  = " ".join(el.get("class", [])).lower()
        el_id    = (el.get("id") or "").lower()
        combined = classes + " " + el_id
        if not any(h in combined for h in PRICE_CLASS_HINTS):
            continue
        text = el.get_text(strip=True)
        if not text or len(text) > 300:
            continue
        for m in PRICE_RE.finditer(text):
            amt_str = m.group("amt1") or m.group("amt2")
            amt = _normalise(amt_str)
            if amt and 0.99 <= amt <= 9999 and amt not in seen_amounts:
                seen_amounts.add(amt)
                found.append({
                    "text":   text[:150],
                    "amount": round(amt, 2),
                    "tag":    el.name,
                    "class":  classes[:80],
                })
    return found


# ──────────────────────────────────────────────────────────────────
#  STEP 4 — STRIKETHROUGH PRICE DETECTION
# ──────────────────────────────────────────────────────────────────

def strikethrough_prices(soup):
    result = {}
    if soup is None:
        return result
    for tag_name in ["s", "del", "strike"]:
        for el in soup.find_all(tag_name):
            text = el.get_text(strip=True)
            m = PRICE_RE.search(text)
            if m:
                amt_str = m.group("amt1") or m.group("amt2")
                amt = _normalise(amt_str)
                if amt and 0.99 <= amt <= 9999:
                    result["original"] = round(amt, 2)
                    parent = el.parent
                    if parent:
                        parent_text = parent.get_text(strip=True)
                        for m2 in PRICE_RE.finditer(parent_text):
                            a2 = _normalise(m2.group("amt1") or m2.group("amt2"))
                            if a2 and 0.99 <= a2 < amt:
                                result["sale"] = round(a2, 2)
                                break
                    break
    return result


# ──────────────────────────────────────────────────────────────────
#  STEP 5 — STRUCTURED DATA
# ──────────────────────────────────────────────────────────────────

def structured_data_prices(soup):
    result = {}
    if soup is None:
        return result
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            objects = data if isinstance(data, list) else [data]
            for obj in objects:
                offers = obj.get("offers") or obj.get("Offers")
                if isinstance(offers, dict):
                    p = offers.get("price") or offers.get("lowPrice")
                    if p:
                        try:
                            result["jsonld_price"]    = float(str(p).replace(",", ""))
                            result["jsonld_currency"] = offers.get("priceCurrency", "USD")
                        except Exception:
                            pass
        except Exception:
            pass
    for meta in soup.find_all("meta"):
        prop    = (meta.get("property") or meta.get("name") or "").lower()
        content = meta.get("content", "")
        if "price" in prop or "amount" in prop:
            try:
                result[f"meta_{prop}"] = float(content.replace(",", ""))
            except Exception:
                if content:
                    result[f"meta_{prop}_raw"] = content
    return result


# ──────────────────────────────────────────────────────────────────
#  STEP 6 — CTA BUTTONS
# ──────────────────────────────────────────────────────────────────

def extract_cta_buttons(soup):
    if soup is None:
        return []
    ctas = []
    for el in soup.find_all(["button", "a", "input"]):
        text = (
            el.get_text(strip=True)
            or el.get("value", "")
            or el.get("aria-label", "")
        ).strip()
        if not text or len(text) > 200:
            continue
        lower = text.lower()
        if any(kw in lower for kw in CTA_KEYWORDS):
            ctas.append(text)
    seen   = set()
    unique = []
    for c in ctas:
        if c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)
    return unique[:25]


# ──────────────────────────────────────────────────────────────────
#  STEP 7 — URGENCY TEXT
# ──────────────────────────────────────────────────────────────────

def extract_urgency(soup):
    if soup is None:
        return None
    text = soup.get_text(separator=" ", strip=True)
    m = URGENCY_RE.search(text)
    if m:
        start = max(0, m.start() - 20)
        end   = min(len(text), m.end() + 80)
        return text[start:end].strip()
    return None


# ──────────────────────────────────────────────────────────────────
#  STEP 8 — CLEAN VISIBLE TEXT FOR AI
# ──────────────────────────────────────────────────────────────────

def extract_visible_text(soup, max_chars=6000):
    if soup is None:
        return ""
    from bs4 import BeautifulSoup as BS
    s = BS(str(soup), "html.parser")
    for tag in s(["script", "style", "noscript", "nav", "header",
                  "footer", "svg", "img", "video", "iframe"]):
        tag.decompose()
    full_text = s.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Score lines — price-related lines get higher score
    scored = []
    for i, line in enumerate(lines):
        score = 0
        if PRICE_RE.search(line):
            score += 10
        if any(w in line.lower() for w in ["price", "save", "off", "discount",
                                            "today", "only", "buy", "order",
                                            "get", "access", "offer", "deal"]):
            score += 5
        if any(c in line for c in ["$", "£", "€", "%"]):
            score += 3
        scored.append((i, score, line))

    top = sorted(scored, key=lambda x: -x[1])[:40]
    top_sorted = sorted(top, key=lambda x: x[0])
    price_section = "\n".join(l for _, _, l in top_sorted)

    combined = "=== PRICE-DENSE SECTION ===\n" + price_section + "\n\n=== FULL PAGE TEXT ===\n" + full_text
    return combined[:max_chars]


# ──────────────────────────────────────────────────────────────────
#  STEP 9 — GPT-4o INTERPRETER
# ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a pricing extraction specialist for affiliate sales pages.

Your job: find the REAL current prices shown on this sales page.

STRICT RULES:
1. ONLY use prices that actually appear in the provided page text/data.
2. NEVER invent, estimate, or guess prices.
3. If no prices found → set original_price AND discounted_price to null.
4. discounted_price = the CURRENT selling price (the price buyer actually pays today).
5. original_price = the higher crossed-out/was-price (if shown).
6. Prices in CTA buttons like "Get Access for $47" → $47 is the discounted_price.
7. Ignore numbers that are clearly not prices (percentages like "100% guaranteed", quantities like "24 hours").
8. If only ONE price is shown → discounted_price = that price; original_price = null.
9. savings_amount and savings_percent: calculate ONLY when both prices available.
10. pricing_type: "one-time" if shows "one-time payment", "monthly" if /month, else "unknown".

Return ONLY valid JSON (no markdown fences, no extra text):
{
  "original_price":   "$X" or null,
  "discounted_price": "$X" or null,
  "savings_amount":   "$X" or null,
  "savings_percent":  "X%" or null,
  "price_display":    "e.g. $297 → $47 (84% OFF)" or null,
  "currency":         "USD",
  "primary_cta":      "best CTA button text found on page",
  "cta_button_texts": ["..."],
  "urgency_text":     "urgency phrase from page" or null,
  "pricing_type":     "one-time / monthly / annual / unknown",
  "confidence":       "high / medium / low / none",
  "pricing_notes":    "brief note explaining what was found"
}"""


def ai_interpret_pricing(url, regex_prices, dom_snippets, structured,
                          strikethrough, cta_buttons, urgency, visible_text):
    payload = {
        "source_url":            url,
        "prices_found_by_regex": regex_prices[:20],
        "dom_price_snippets":    dom_snippets[:20],
        "structured_data":       structured,
        "strikethrough_prices":  strikethrough,
        "cta_buttons_found":     cta_buttons[:20],
        "urgency_text_found":    urgency,
        "page_visible_text":     visible_text,
    }

    try:
        resp = client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=800,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)

    except Exception as e:
        # Fallback: pure regex, no fabrication
        prices = sorted(set(regex_prices or []))
        disc   = min(prices) if prices else None
        orig   = max(prices) if len(prices) > 1 else None

        def fmt(v):
            if v is None: return None
            return f"${int(v)}" if v == int(v) else f"${v:.2f}"

        return {
            "original_price":   fmt(orig),
            "discounted_price": fmt(disc),
            "savings_amount":   fmt(orig - disc) if orig and disc else None,
            "savings_percent":  f"{round((orig-disc)/orig*100)}%" if orig and disc else None,
            "price_display":    fmt(disc),
            "currency":         "USD",
            "primary_cta":      cta_buttons[0] if cta_buttons else "Get Instant Access",
            "cta_button_texts": cta_buttons[:5],
            "urgency_text":     urgency,
            "pricing_type":     "unknown",
            "confidence":       "low",
            "pricing_notes":    f"AI failed ({e}); regex found: {prices}",
        }


# ──────────────────────────────────────────────────────────────────
#  EMPTY RESULT
# ──────────────────────────────────────────────────────────────────

def _empty_pricing(note=""):
    return {
        "original_price":   None,
        "discounted_price": None,
        "savings_amount":   None,
        "savings_percent":  None,
        "price_display":    None,
        "currency":         "USD",
        "primary_cta":      "Get Instant Access",
        "cta_button_texts": ["Get Instant Access"],
        "urgency_text":     None,
        "pricing_type":     "unknown",
        "confidence":       "none",
        "pricing_notes":    note,
    }


# ──────────────────────────────────────────────────────────────────
#  PUBLIC API
# ──────────────────────────────────────────────────────────────────

def run_price_scraper_agent(url):
    """
    Full 9-step pipeline. Prices always come from the actual page.
    Returns dict with original_price, discounted_price, savings, CTA, urgency, etc.
    """
    print(f"  🔍 Price Agent → {url}")

    # 1. Fetch
    result = fetch_page(url)
    if not result["ok"]:
        print(f"  ⚠️  Fetch failed: {result.get('error')}")
        return _empty_pricing(f"Fetch error: {result.get('error')}")

    pages = result["pages"]
    print(f"  📄 Pages fetched: {len(pages)}")

    # Aggregate across all pages
    all_regex   = set()
    all_dom     = []
    all_struct  = {}
    all_strike  = {}
    all_ctas    = []
    all_urgency = None
    all_text    = []

    for page in pages:
        soup = page["soup"]
        html = page["html"]
        purl = page["url"]

        rp = regex_extract_prices(html)
        all_regex.update(rp)

        ds = dom_extract_prices(soup)
        all_dom.extend(ds)

        sd = structured_data_prices(soup)
        all_struct.update(sd)

        st = strikethrough_prices(soup)
        if st and not all_strike:
            all_strike = st

        cb = extract_cta_buttons(soup)
        for c in cb:
            if c not in all_ctas:
                all_ctas.append(c)

        if not all_urgency:
            all_urgency = extract_urgency(soup)

        vt = extract_visible_text(soup)
        if vt:
            all_text.append(f"[Page: {purl[:80]}]\n{vt}")

    regex_prices  = sorted(all_regex)
    combined_text = "\n\n---\n\n".join(all_text[:2])

    print(f"  📊 Regex prices ({len(regex_prices)}): {regex_prices[:10]}")
    print(f"  🏷️  DOM snippets: {len(all_dom)}")
    if all_struct:
        print(f"  📋 Structured data: {all_struct}")
    if all_strike:
        print(f"  ~~  Strikethrough: {all_strike}")
    print(f"  🔘 CTAs ({len(all_ctas)}): {all_ctas[:4]}")
    if all_urgency:
        print(f"  ⏰ Urgency: {all_urgency[:80]}")

    # 9. AI
    print(f"  🤖 GPT-4o interpreting pricing data...")
    pricing = ai_interpret_pricing(
        url          = url,
        regex_prices = regex_prices,
        dom_snippets = all_dom,
        structured   = all_struct,
        strikethrough= all_strike,
        cta_buttons  = all_ctas,
        urgency      = all_urgency,
        visible_text = combined_text,
    )

    conf = pricing.get("confidence", "?")
    disc = pricing.get("discounted_price", "—")
    orig = pricing.get("original_price", "—")
    disp = pricing.get("price_display") or ""
    print(f"  ✅ [{conf}] orig={orig}  sale={disc}  {disp}")
    print(f"     cta='{pricing.get('primary_cta')}'")
    if pricing.get("pricing_notes"):
        print(f"     notes: {pricing['pricing_notes']}")

    return pricing


# ──────────────────────────────────────────────────────────────────
#  CLI TEST:  python price_scraper_agent.py <url>
# ──────────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     import sys
#     test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.ketoflow.app/d"
#     result = run_price_scraper_agent(test_url)
#     print("\n" + "=" * 60)
#     print("FINAL PRICING RESULT:")
#     print(json.dumps(result, indent=2, ensure_ascii=False))