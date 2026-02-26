"""
Price Scraper Agent v2
=======================
Extraction pipeline (in order, no fabrication):
  1. Regex scan on raw HTML for price patterns  ($9.99, £47, €197, ¥1000 etc.)
  2. Targeted DOM scan — elements with CSS classes/IDs commonly used for prices
  3. JSON-LD / meta structured-data  (schema.org Offer / Product)
  4. OpenGraph / meta price tags
  5. GPT-4o-mini — ONLY interprets what was already found, NEVER invents prices
     (returns null if no prices found — no guessing, no estimating)
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

# Matches:  $9  $9.99  $1,997  £47  €197  ¥1000  USD 47  47 USD  etc.
PRICE_RE = re.compile(
    r"""
    (?:
        (?P<sym1>[\$\xA3\u20AC\xA5\u20B9\u20A9\u20BD])   # leading currency symbol
        \s*
        (?P<amt1>\d{1,5}(?:[.,]\d{2,3})?)
    )
    |
    (?:
        (?P<amt2>\d{1,5}(?:[.,]\d{2,3})?)
        \s*
        (?P<sym2>USD|GBP|EUR|CAD|AUD)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# DOM selectors that commonly hold price info (class/id fragments)
PRICE_CLASS_HINTS = [
    "price", "pricing", "cost", "amount", "offer", "discount",
    "sale", "original", "regular", "special", "today", "checkout",
    "total", "fee", "rate", "plan", "tier",
]

# Button/CTA keyword hints
CTA_KEYWORDS = [
    "buy", "get", "order", "purchase", "access", "claim", "grab",
    "start", "join", "enroll", "subscribe", "download", "instant",
    "yes", "add to cart", "checkout",
]

URGENCY_RE = re.compile(
    r"(only\s+\d+\s+(?:left|remaining|spots?|copies|seats?)|"
    r"limited\s+time|expires?\s+(?:in|soon)|"
    r"today\s+only|price\s+(?:goes?\s+up|increases?)|"
    r"hurry|don'?t\s+miss|last\s+chance|ends?\s+(?:soon|tonight|today)|"
    r"countdown|timer|\d+\s+hours?\s+(?:left|remaining))",
    re.IGNORECASE,
)


# ──────────────────────────────────────────────────────────────────
#  STEP 1 — FETCH
# ──────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        return {"url": url, "soup": soup, "html": r.text, "ok": True}
    except Exception as e:
        return {"url": url, "soup": None, "html": "", "ok": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────
#  STEP 2 — REGEX PRICE EXTRACTION
# ──────────────────────────────────────────────────────────────────

def _normalise_amount(raw: str):
    try:
        return float(raw.replace(",", ""))
    except Exception:
        return None


def regex_extract_prices(html: str) -> list:
    prices = set()
    for m in PRICE_RE.finditer(html):
        amt_str = m.group("amt1") or m.group("amt2")
        amt = _normalise_amount(amt_str)
        if amt and 0.5 <= amt <= 50000:
            prices.add(amt)
    return sorted(prices)


# ──────────────────────────────────────────────────────────────────
#  STEP 3 — DOM TARGETED EXTRACTION
# ──────────────────────────────────────────────────────────────────

def _has_price_hint(el) -> bool:
    classes  = " ".join(el.get("class", [])).lower()
    el_id    = (el.get("id") or "").lower()
    combined = classes + " " + el_id
    return any(h in combined for h in PRICE_CLASS_HINTS)


def dom_extract_prices(soup) -> list:
    found = []
    if soup is None:
        return found
    for el in soup.find_all(True):
        if not _has_price_hint(el):
            continue
        text = el.get_text(strip=True)
        if not text:
            continue
        for m in PRICE_RE.finditer(text):
            amt_str = m.group("amt1") or m.group("amt2")
            amt = _normalise_amount(amt_str)
            if amt and 0.5 <= amt <= 50000:
                found.append({
                    "text":   text[:120],
                    "amount": amt,
                    "tag":    el.name,
                    "class":  " ".join(el.get("class", [])),
                })
    return found


# ──────────────────────────────────────────────────────────────────
#  STEP 4 — STRUCTURED DATA (JSON-LD / meta)
# ──────────────────────────────────────────────────────────────────

def structured_data_prices(soup) -> dict:
    result = {}
    if soup is None:
        return result

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data    = json.loads(script.string or "")
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
                if "price" in obj:
                    try:
                        result["jsonld_product_price"] = float(str(obj["price"]).replace(",", ""))
                    except Exception:
                        pass
        except Exception:
            pass

    # Open Graph / meta tags
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
#  STEP 5 — CTA BUTTON EXTRACTION
# ──────────────────────────────────────────────────────────────────

def extract_cta_buttons(soup) -> list:
    if soup is None:
        return []
    ctas = []
    for el in soup.find_all(["button", "a", "input"]):
        text = (
            el.get_text(strip=True)
            or el.get("value", "")
            or el.get("aria-label", "")
        ).strip()
        if not text or len(text) > 150:
            continue
        lower = text.lower()
        if any(kw in lower for kw in CTA_KEYWORDS):
            ctas.append(text)
    # Dedupe while preserving order
    seen   = set()
    unique = []
    for c in ctas:
        if c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)
    return unique[:20]


# ──────────────────────────────────────────────────────────────────
#  STEP 6 — URGENCY TEXT
# ──────────────────────────────────────────────────────────────────

def extract_urgency(soup) -> str:
    if soup is None:
        return None
    text = soup.get_text(separator=" ", strip=True)
    m = URGENCY_RE.search(text)
    if m:
        start = max(0, m.start() - 20)
        end   = min(len(text), m.end() + 60)
        return text[start:end].strip()
    return None


# ──────────────────────────────────────────────────────────────────
#  STEP 7 — AI INTERPRETER
#  Receives only what was actually found on the page.
#  MUST NOT invent prices.
# ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a pricing data extractor.
Your ONLY job is to interpret pricing data already extracted from a sales page.

STRICT RULES — read carefully:
1. NEVER invent, estimate, or guess prices.
2. ONLY use prices from "prices_found_by_regex", "dom_price_snippets", or "structured_data_prices".
3. If no prices are found in those fields, set original_price AND discounted_price to null.
4. Do NOT use "industry typical" or "common" prices as substitutes.
5. The discounted_price is usually the LOWEST prominent price shown.
6. The original_price is the higher price, often crossed-out/strikethrough.
7. Pick the best CTA button text from "cta_buttons_found" (not invented).

Return ONLY valid JSON — no markdown fences, no explanation:
{
  "original_price":   "$X" or null,
  "discounted_price": "$X" or null,
  "savings_amount":   "$X" or null,
  "savings_percent":  "X%" or null,
  "price_display":    "human-readable string" or null,
  "currency":         "USD",
  "primary_cta":      "best CTA text from page",
  "cta_button_texts": ["..."],
  "urgency_text":     "urgency text" or null,
  "pricing_type":     "one-time / monthly / annual / unknown",
  "confidence":       "high / medium / low / none",
  "pricing_notes":    "brief note"
}"""


def ai_interpret_pricing(
    url: str,
    regex_prices: list,
    dom_snippets: list,
    structured: dict,
    cta_buttons: list,
    urgency: str,
    page_text_sample: str,
) -> dict:
    payload = {
        "url":                   url,
        "prices_found_by_regex": regex_prices,
        "dom_price_snippets":    dom_snippets[:15],
        "structured_data":       structured,
        "cta_buttons_found":     cta_buttons,
        "urgency_text_found":    urgency,
        "page_text_sample":      page_text_sample[:3000],
    }

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=700,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)

    except Exception as e:
        # Pure regex fallback — still no fabrication
        prices = regex_prices or []
        disc   = min(prices) if prices else None
        orig   = max(prices) if len(prices) > 1 else None
        sym    = "$"

        def fmt(v):
            return f"{sym}{v:.2f}".rstrip("0").rstrip(".") if v else None

        savings_pct = (
            f"{round((orig - disc) / orig * 100)}%"
            if orig and disc and orig > disc else None
        )
        savings_amt = fmt(orig - disc) if orig and disc else None

        return {
            "original_price":   fmt(orig),
            "discounted_price": fmt(disc),
            "savings_amount":   savings_amt,
            "savings_percent":  savings_pct,
            "price_display":    fmt(disc),
            "currency":         "USD",
            "primary_cta":      cta_buttons[0] if cta_buttons else "Get Instant Access",
            "cta_button_texts": cta_buttons[:5],
            "urgency_text":     urgency,
            "pricing_type":     "unknown",
            "confidence":       "low",
            "pricing_notes":    f"AI failed ({e}); raw regex prices: {prices}",
        }


# ──────────────────────────────────────────────────────────────────
#  EMPTY RESULT (used on fetch failure)
# ──────────────────────────────────────────────────────────────────

def _empty_pricing(note: str = "") -> dict:
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

def run_price_scraper_agent(url: str) -> dict:
    """
    Full 7-step pipeline.
    Prices are ALWAYS from the actual page — null if not found, never fabricated.
    """
    print(f"  🔍 Price Agent → {url}")

    # 1. Fetch
    page = fetch_page(url)
    if not page["ok"]:
        print(f"  ⚠️  Fetch failed: {page.get('error')}")
        return _empty_pricing(f"Fetch error: {page.get('error')}")

    soup = page["soup"]
    html = page["html"]

    # 2. Regex
    regex_prices = regex_extract_prices(html)
    print(f"  📊 Regex candidates ({len(regex_prices)}): {regex_prices[:8]}")

    # 3. DOM
    dom_snippets = dom_extract_prices(soup)
    print(f"  🏷️  DOM snippets: {len(dom_snippets)}")

    # 4. Structured data
    structured = structured_data_prices(soup)
    if structured:
        print(f"  📋 Structured data: {structured}")

    # 5. CTA buttons
    cta_buttons = extract_cta_buttons(soup)
    print(f"  🔘 CTAs ({len(cta_buttons)}): {cta_buttons[:3]}")

    # 6. Urgency
    urgency = extract_urgency(soup)
    if urgency:
        print(f"  ⏰ Urgency: {urgency[:80]}")

    # 7. Clean text for AI
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    page_text = soup.get_text(separator="\n", strip=True)

    # 8. AI interpretation
    print(f"  🤖 AI interpreting extracted data...")
    pricing = ai_interpret_pricing(
        url=url,
        regex_prices=regex_prices,
        dom_snippets=dom_snippets,
        structured=structured,
        cta_buttons=cta_buttons,
        urgency=urgency,
        page_text_sample=page_text,
    )

    conf = pricing.get("confidence", "?")
    disc = pricing.get("discounted_price", "—")
    orig = pricing.get("original_price", "—")
    print(f"  ✅ [{conf}] orig={orig}  sale={disc}  cta='{pricing.get('primary_cta')}'")

    return pricing


# ──────────────────────────────────────────────────────────────────
#  CLI TEST  →  python price_scraper_agent.py https://example.com
# ──────────────────────────────────────────────────────────────────
# if __name__ == "__main__":
#     import sys
#     test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.ketoflow.app/d"
#     result = run_price_scraper_agent(test_url)
#     print("\n" + "=" * 60)
#     print("FINAL PRICING RESULT:")
#     print(json.dumps(result, indent=2, ensure_ascii=False))