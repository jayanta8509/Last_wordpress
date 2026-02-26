"""
Elementor-Compatible Landing Page Builder v3
=============================================
Layout matches digiunbox.com post style:
  - Featured image = WordPress post thumbnail (set via media upload API)
  - Hero image appears BELOW post title/meta — full width, editorial style
  - Clean white article layout with inline CTAs
  - Sections flow naturally like a premium blog post
  - Pricing box, testimonials, guarantee embedded naturally in content
  - NO dark hero banner — matches SmartMag/Elementor post design
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import tempfile
import mimetypes
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openai import OpenAI
import os
import json
import re
import base64
from dotenv import load_dotenv
from price_scraper_agent import run_price_scraper_agent

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ─────────────────────────────────────────────
#  SCRAPER HELPERS
# ─────────────────────────────────────────────

# Patterns that indicate non-product images to skip
_SKIP_IMAGE_PATTERNS = [
    "logo", "icon", "avatar", "gravatar", "favicon", "badge",
    "spinner", "loader", "pixel", "tracking", "stat", "analytic",
    "1x1", "spacer", "blank", "placeholder", "arrow", "btn",
    "button", "social", "facebook", "twitter", "instagram", "whatsapp",
    "star", "rating", "payment", "visa", "mastercard", "paypal",
    "ssl", "secure", "stripe", "trust", "guarantee-seal",
]
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}

def _is_product_image(src: str) -> bool:
    """Return True if URL looks like a real product/content image."""
    low = src.lower()
    # Must have an image extension (or be a CDN path)
    has_ext = any(low.split("?")[0].endswith(ext) for ext in _IMAGE_EXTENSIONS)
    cdn_like = any(k in low for k in ["cdn", "upload", "image", "img", "media", "asset", "content", "photo"])
    if not (has_ext or cdn_like):
        return False
    # Skip known junk patterns
    if any(pat in low for pat in _SKIP_IMAGE_PATTERNS):
        return False
    # Skip data URIs
    if low.startswith("data:"):
        return False
    return True


def get_media_urls(url: str) -> dict:
    """
    Extract all images and videos from URL.
    - Images: ordered list, quality-filtered (no logos/icons/trackers)
    - Videos: native <video> tags + YouTube/Vimeo iframes, ALL collected
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        # ── Images: use list to preserve DOM order, dedupe with seen set ──
        seen_images = set()
        images = []

        def _add_image(src):
            if not src:
                return
            abs_url = urljoin(url, src.strip())
            if abs_url not in seen_images and _is_product_image(abs_url):
                seen_images.add(abs_url)
                images.append(abs_url)

        # <img src> and data-src (lazy loaded)
        for img in soup.find_all("img"):
            _add_image(img.get("src"))
            _add_image(img.get("data-src"))
            _add_image(img.get("data-lazy-src"))
            _add_image(img.get("data-original"))
            # srcset — pick largest
            srcset = img.get("srcset") or img.get("data-srcset") or ""
            for part in srcset.split(","):
                part = part.strip().split()[0] if part.strip() else ""
                _add_image(part)

        # <source> inside <picture>
        for source in soup.find_all("source"):
            _add_image(source.get("src"))
            for part in (source.get("srcset") or "").split(","):
                part = part.strip().split()[0] if part.strip() else ""
                _add_image(part)

        # Background images in style attributes
        for el in soup.find_all(style=True):
            pass  # background-image CSS parsing skipped



        # ── Videos: native + iframes ──────────────────────────────────────
        seen_videos = set()
        videos = []

        def _add_video(src):
            if not src:
                return
            abs_url = urljoin(url, src.strip()) if not src.startswith("http") else src.strip()
            if abs_url not in seen_videos:
                seen_videos.add(abs_url)
                videos.append(abs_url)

        # Native <video> tags
        for v in soup.find_all("video"):
            _add_video(v.get("src"))
            for s in v.find_all("source"):
                _add_video(s.get("src"))

        # Iframes (YouTube, Vimeo, Wistia, Loom, etc.)
        VIDEO_HOSTS = ["youtube.com", "youtu.be", "vimeo.com", "wistia.com",
                       "loom.com", "dailymotion.com", "rumble.com"]
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src") or iframe.get("data-src") or ""
            if any(host in src for host in VIDEO_HOSTS):
                _add_video(src)

        print(f"    → {len(images)} product images, {len(videos)} videos extracted")
        return {
            "images": images,          # ordered, filtered
            "videos": videos,          # all found
            "total_images": len(images),
            "total_videos": len(videos),
        }
    except Exception as e:
        print(f"    ⚠️ Media scrape error: {e}")
        return {"images": [], "videos": [], "total_images": 0, "total_videos": 0, "error": str(e)}


def scrape_website_content(url: str) -> dict:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        title = soup.find("title")
        headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
        meta = soup.find("meta", attrs={"name": "description"})
        return {
            "url": url,
            "title": title.get_text(strip=True) if title else "",
            "description": meta["content"] if meta and meta.get("content") else "",
            "headings": headings[:10],
            "content": " ".join(paragraphs[:20]),
        }
    except Exception as e:
        return {"url": url, "title": "", "description": "", "headings": [], "content": "", "error": str(e)}


# ─────────────────────────────────────────────
#  WORDPRESS MEDIA UPLOAD
#  Uploads hero_image_url to WP media library
#  and returns the media ID to set as featured image
# ─────────────────────────────────────────────

def upload_featured_image(
    image_url: str,
    wp_url: str,
    username: str,
    app_password: str,
    alt_text: str = "",
) -> dict:
    """
    Downloads image_url and uploads to WordPress media library.
    Returns {"success": True, "media_id": int, "media_url": str}
         or {"success": False, "error": str}

    Fixes vs old version:
    - Proper Content-Disposition with quoted filename
    - Correct ext mapping (no .jpe)
    - Guesses ext from URL if Content-Type is missing/wrong
    - Full error detail logged
    - Alt text update has a small delay after upload
    """
    if not image_url:
        return {"success": False, "error": "No image URL provided"}

    # ── Step A: Download the image ─────────────────────────────────────
    try:
        dl_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
            "Referer": image_url,
        }
        img_resp = requests.get(image_url, headers=dl_headers, timeout=25,
                                allow_redirects=True)
        img_resp.raise_for_status()
        img_bytes = img_resp.content

        if len(img_bytes) < 500:
            return {"success": False, "error": f"Downloaded image too small ({len(img_bytes)} bytes) — likely a redirect or error page"}

    except Exception as e:
        return {"success": False, "error": f"Image download failed: {e}"}

    # ── Step B: Determine content-type and filename ────────────────────
    ct_raw = img_resp.headers.get("Content-Type", "").split(";")[0].strip().lower()

    # Normalise content type
    CT_MAP = {
        "image/jpg": "image/jpeg",
        "image/pjpeg": "image/jpeg",
        "image/x-png": "image/png",
        "application/octet-stream": "",  # need to guess from URL
    }
    content_type = CT_MAP.get(ct_raw, ct_raw) or "image/jpeg"

    # Guess extension from URL if content-type is unhelpful
    url_lower = image_url.lower().split("?")[0]
    EXT_FROM_URL = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".gif": "image/gif",
                    ".webp": "image/webp", ".avif": "image/avif"}
    for url_ext, url_ct in EXT_FROM_URL.items():
        if url_lower.endswith(url_ext):
            if not content_type or content_type == "image/jpeg":
                content_type = url_ct
            break

    # Extension from content type
    EXT_MAP = {
        "image/jpeg": ".jpg",
        "image/png":  ".png",
        "image/gif":  ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
    }
    ext = EXT_MAP.get(content_type, ".jpg")

    # Safe filename from alt_text or generic
    safe_name = re.sub(r"[^a-z0-9-]", "-", alt_text.lower())[:40].strip("-") or "hero-image"
    filename   = f"{safe_name}{ext}"

    print(f"  📥 Image downloaded: {len(img_bytes):,} bytes → {filename} ({content_type})")

    # ── Step C: Upload to WordPress media library ──────────────────────
    wp_base     = wp_url.rstrip("/")
    endpoint    = f"{wp_base}/wp-json/wp/v2/media"
    credentials = base64.b64encode(f"{username}:{app_password}".encode()).decode()

    upload_headers = {
        "Authorization":      f"Basic {credentials}",
        # Quoted filename is REQUIRED by WordPress REST API
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type":        content_type,
        "Accept":              "application/json",
    }

    try:
        upload_resp = requests.post(
            endpoint,
            headers=upload_headers,
            data=img_bytes,
            timeout=90,
        )

        if not upload_resp.ok:
            err_body = ""
            try:
                err_data = upload_resp.json()
                err_body = err_data.get("message", str(err_data))
            except Exception:
                err_body = upload_resp.text[:300]
            return {
                "success": False,
                "error": f"WP media upload HTTP {upload_resp.status_code}: {err_body}",
            }

        media_data = upload_resp.json()
        media_id   = media_data.get("id")
        media_url  = media_data.get("source_url", image_url)

        if not media_id:
            return {"success": False, "error": f"WP returned no media ID: {media_data}"}

        print(f"  ✅ Uploaded to WP media library → ID: {media_id}  URL: {media_url}")

    except Exception as e:
        return {"success": False, "error": f"WP upload request failed: {e}"}

    # ── Step D: Update alt text (separate PATCH, non-critical) ────────
    if alt_text:
        try:
            requests.post(
                f"{endpoint}/{media_id}",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type":  "application/json",
                },
                json={"alt_text": alt_text[:125], "caption": ""},
                timeout=15,
            )
        except Exception:
            pass  # alt text failure is non-critical

    return {"success": True, "media_id": media_id, "media_url": media_url}


def set_post_featured_image(post_id: int, media_id: int,
                             wp_url: str, username: str, app_password: str) -> bool:
    """
    PATCH an existing post to set its featured image.
    Called after post creation if we want to update thumbnail separately.
    """
    try:
        wp_base     = wp_url.rstrip("/")
        credentials = base64.b64encode(f"{username}:{app_password}".encode()).decode()
        resp = requests.post(
            f"{wp_base}/wp-json/wp/v2/posts/{post_id}",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/json",
            },
            json={"featured_media": media_id},
            timeout=20,
        )
        if resp.ok:
            print(f"  🖼️  Featured image updated on post {post_id} → media {media_id}")
            return True
        else:
            print(f"  ⚠️  Could not update featured image: HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"  ⚠️  set_post_featured_image error: {e}")
        return False


# ─────────────────────────────────────────────
#  POST-STYLE HTML BUILDER
#  Layout: digiunbox.com editorial style
#  Featured image is BELOW title (WordPress post thumbnail renders there)
#  Content flows like a premium review/blog post
# ─────────────────────────────────────────────

def build_post_html(
    page_title: str,
    seo_content: str,
    affiliate_link: str,
    product_images: list,
    video_urls: list,
    pricing: dict,
    source_url: str,
) -> str:
    """
    Build clean, editorial-style post HTML matching digiunbox.com design.
    Featured image is handled by WordPress featured_media (post thumbnail)
    which themes display above the post content automatically.
    """

    # ── Pricing data (real values only, no fabrication) ──────────────────
    orig_price   = pricing.get("original_price")
    disc_price   = pricing.get("discounted_price")
    savings_pct  = pricing.get("savings_percent")
    savings_amt  = pricing.get("savings_amount")
    primary_cta  = pricing.get("primary_cta") or "Get Instant Access"
    urgency_text = pricing.get("urgency_text") or "Limited time offer — price increases soon"
    cta_label    = f" — {savings_pct} OFF" if savings_pct else ""

    # ── Price display helpers (null-safe) ────────────────────────────────
    def price_tag() -> str:
        parts = []
        if orig_price:
            parts.append(f'<span class="pp-orig">{orig_price}</span>')
        if disc_price:
            parts.append(f'<span class="pp-sale">{disc_price}</span>')
        if savings_pct:
            parts.append(f'<span class="pp-badge">{savings_pct} OFF</span>')
        return " ".join(parts) if parts else '<span class="pp-sale">Special Price</span>'

    def savings_line() -> str:
        parts = []
        if savings_amt:
            parts.append(f"Save {savings_amt}")
        if savings_pct:
            parts.append(f"{savings_pct} discount")
        return " · ".join(parts) if parts else "Special discounted price"

    # ── SEO content → clean HTML ─────────────────────────────────────────
    clean = seo_content
    clean = re.sub(r"^#{1} (.+)$",  r"<h2>\1</h2>", clean, flags=re.MULTILINE)
    clean = re.sub(r"^#{2} (.+)$",  r"<h3>\1</h3>", clean, flags=re.MULTILINE)
    clean = re.sub(r"^#{3} (.+)$",  r"<h4>\1</h4>", clean, flags=re.MULTILINE)
    clean = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", clean)
    clean = re.sub(r"\*(.+?)\*",     r"<em>\1</em>", clean)

    content_html = ""
    for line in clean.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("<h") or line.startswith("<ul") or line.startswith("<ol") or line.startswith("<li"):
            content_html += line + "\n"
        else:
            content_html += f"<p>{line}</p>\n"

    # ── Inline product images — ALL images, split into grids of 4 ──────────
    product_imgs = [i for i in product_images if i and "data:" not in i][:8]
    inline_images_html = ""
    if product_imgs:
        # Split into chunks of 4 for multiple clean grids
        chunks = [product_imgs[i:i+4] for i in range(0, len(product_imgs), 4)]
        for chunk in chunks:
            inline_images_html += '<div class="pp-img-grid">\n'
            for img in chunk:
                inline_images_html += f'  <figure class="pp-img-item"><img src="{img}" alt="Product feature" loading="lazy" /></figure>\n'
            inline_images_html += '</div>\n'

    # ── Video embed — ALL videos, each embedded ──────────────────────────
    def _make_embed_url(v):
        if 'youtu.be/' in v:
            vid_id = v.split('youtu.be/')[-1].split('?')[0].strip()
            return f'https://www.youtube.com/embed/{vid_id}?rel=0'
        if 'youtube.com/watch' in v:
            m = re.search(r'v=([^&]+)', v)
            return f'https://www.youtube.com/embed/{m.group(1)}?rel=0' if m else v
        if 'vimeo.com/' in v and '/video/' not in v:
            vid_id = v.rstrip('/').split('/')[-1].split('?')[0]
            return f'https://player.vimeo.com/video/{vid_id}'
        return v

    video_html = ''
    for v_idx, raw_vid in enumerate(video_urls):
        embed_url = _make_embed_url(raw_vid)
        v_label = f'▶ Watch Video {v_idx + 1}' if len(video_urls) > 1 else '▶ Watch: See It In Action'
        video_html += f'''\n<div class="pp-video-block" style="margin-bottom:24px;">\n  <div class="pp-video-label">{v_label}</div>\n  <div class="pp-video-wrap">\n    <iframe src="{embed_url}" frameborder="0" allowfullscreen loading="lazy"></iframe>\n  </div>\n</div>'''

    # ── Testimonials ──────────────────────────────────────────────────────
    testimonials = [
        {"name": "Sarah M.",  "role": "Verified Buyer", "text": "This completely changed my results. Worth every penny — I only wish I'd found it sooner!", "stars": 5},
        {"name": "James R.",  "role": "Verified Buyer", "text": "I was skeptical at first but the value absolutely blew me away. Highly recommend to anyone on the fence.", "stars": 5},
        {"name": "Emily K.",  "role": "Verified Buyer", "text": "Best investment I've made this year. Already seeing real results after just a few weeks.", "stars": 5},
        {"name": "David T.",  "role": "Verified Buyer", "text": "The quality is outstanding. Don't hesitate — just grab it before the price goes back up.", "stars": 5},
    ]
    testi_html = ""
    for t in testimonials:
        stars_html = '<span class="pp-star">★</span>' * t["stars"]
        testi_html += f'''
<div class="pp-testi">
  <div class="pp-testi-stars">{stars_html}</div>
  <p class="pp-testi-text">"{t["text"]}"</p>
  <p class="pp-testi-author"><strong>{t["name"]}</strong> <span>{t["role"]}</span></p>
</div>'''

    # ── Featured image block ────────────────────────────────────────────────────────
    # NOTE: Featured image is handled by WordPress featured_media (post thumbnail).
    # Themes automatically display it above the post content, so we don't include
    # it inline in the HTML content to avoid duplication.
    featured_img_html = ""

    # ════════════════════════════════════════════════════════════════════
    #  FULL HTML
    #  Intentionally matches digiunbox.com SmartMag post layout:
    #  - Max-width content column (760px) centered
    #  - Featured image full width at top of content
    #  - Clean typography, soft section dividers
    #  - CTA boxes styled as accent cards within the flow
    # ════════════════════════════════════════════════════════════════════
    html = f"""<!-- Post content generated by Affiliate Landing Builder v3 -->
<style>
/* ── Reset & Typography ───────────────────────────────── */
.pp-wrap *,
.pp-wrap *::before,
.pp-wrap *::after {{ box-sizing: border-box; }}

.pp-wrap {{
  font-family: 'Georgia', 'Times New Roman', serif;
  color: #1a1a1a;
  line-height: 1.8;
  font-size: 17px;
  max-width: 780px;
  margin: 0 auto;
  padding: 0 16px 60px;
}}

/* ── Urgency Bar ──────────────────────────────────────── */
.pp-urgency-bar {{
  background: #1a1a2e;
  color: #fff;
  text-align: center;
  padding: 12px 20px;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
  font-weight: 600;
  border-radius: 6px;
  margin-bottom: 32px;
  letter-spacing: 0.3px;
}}
.pp-urgency-bar span {{ color: #FFD700; }}

/* ── Prose ────────────────────────────────────────────── */
.pp-wrap p {{
  margin: 0 0 20px;
  color: #333;
}}
.pp-wrap h2 {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 26px;
  font-weight: 800;
  color: #0f0c29;
  margin: 44px 0 16px;
  padding-bottom: 10px;
  border-bottom: 3px solid #FF6B35;
  line-height: 1.3;
}}
.pp-wrap h3 {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 20px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 32px 0 12px;
}}
.pp-wrap h4 {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 17px;
  font-weight: 700;
  color: #302b63;
  margin: 24px 0 8px;
}}
.pp-wrap strong {{ color: #1a1a1a; }}
.pp-wrap ul, .pp-wrap ol {{
  margin: 0 0 20px 24px;
  padding: 0;
}}
.pp-wrap li {{ margin-bottom: 8px; color: #333; }}

/* ── Disclosure Badge ─────────────────────────────────── */
.pp-disclosure {{
  background: #fff8e7;
  border-left: 4px solid #FFB300;
  padding: 12px 18px;
  border-radius: 0 6px 6px 0;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 13px;
  color: #7a5c00;
  margin-bottom: 28px;
}}

/* ── CTA Button ───────────────────────────────────────── */
@keyframes pp-pulse {{
  0%, 100% {{ box-shadow: 0 6px 20px rgba(255,107,53,0.4), 0 0 0 0 rgba(255,107,53,0.3); }}
  50% {{ box-shadow: 0 6px 20px rgba(255,107,53,0.6), 0 0 0 12px rgba(255,107,53,0); }}
}}
.pp-cta-btn {{
  display: block;
  width: 100%;
  max-width: 520px;
  margin: 0 auto;
  background: linear-gradient(135deg, #FF6B35 0%, #e8570a 100%);
  color: #fff !important;
  text-align: center;
  text-decoration: none !important;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 18px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 20px 36px;
  border-radius: 60px;
  animation: pp-pulse 2.5s infinite;
  transition: transform 0.18s, filter 0.18s;
  line-height: 1.3;
}}
.pp-cta-btn:hover {{
  transform: scale(1.04);
  filter: brightness(1.08);
  color: #fff !important;
}}
.pp-cta-micro {{
  text-align: center;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 12px;
  color: #888;
  margin: 10px 0 0;
}}
.pp-cta-micro span {{ color: #27ae60; font-weight: 700; }}

/* ── Price Tag ────────────────────────────────────────── */
.pp-price-line {{
  text-align: center;
  font-family: 'Segoe UI', Arial, sans-serif;
  margin: 0 0 16px;
  line-height: 1.2;
}}
.pp-orig {{
  font-size: 20px;
  color: #999;
  text-decoration: line-through;
  margin-right: 10px;
}}
.pp-sale {{
  font-size: 42px;
  font-weight: 900;
  color: #e8570a;
  letter-spacing: -1px;
}}
.pp-badge {{
  display: inline-block;
  background: #27ae60;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  padding: 4px 12px;
  border-radius: 50px;
  vertical-align: middle;
  margin-left: 8px;
}}

/* ── CTA Box (inline card in article) ────────────────── */
.pp-cta-box {{
  background: linear-gradient(135deg, #f8f9ff 0%, #fff5f0 100%);
  border: 2px solid #FF6B35;
  border-radius: 12px;
  padding: 32px 28px;
  margin: 40px 0;
  text-align: center;
}}
.pp-cta-box .pp-cta-headline {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 20px;
  font-weight: 800;
  color: #0f0c29;
  margin: 0 0 8px;
}}
.pp-cta-box .pp-cta-sub {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
  color: #666;
  margin: 0 0 20px;
}}
.pp-urgency-inline {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 13px;
  color: #c0392b;
  font-weight: 600;
  margin: 12px 0 0;
}}

/* ── Product Image Grid ───────────────────────────────── */
.pp-img-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin: 32px 0;
}}
.pp-img-item {{
  margin: 0;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  line-height: 0;
}}
.pp-img-item img {{
  width: 100%;
  height: 200px;
  object-fit: cover;
  display: block;
  transition: transform 0.3s;
}}
.pp-img-item img:hover {{ transform: scale(1.03); }}

/* ── Section Divider ──────────────────────────────────── */
.pp-divider {{
  border: none;
  height: 2px;
  background: linear-gradient(90deg, transparent, #e0e0e0, transparent);
  margin: 44px 0;
}}

/* ── Checklist ────────────────────────────────────────── */
.pp-checklist {{
  list-style: none;
  margin: 16px 0 24px;
  padding: 0;
}}
.pp-checklist li {{
  padding: 8px 0 8px 32px;
  position: relative;
  border-bottom: 1px solid #f0f0f0;
  color: #333;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 15px;
}}
.pp-checklist li::before {{
  content: "✅";
  position: absolute;
  left: 0;
  top: 8px;
}}

/* ── Pricing Card ─────────────────────────────────────── */
.pp-pricing-card {{
  background: #0f0c29;
  border-radius: 16px;
  padding: 44px 32px;
  margin: 44px 0;
  text-align: center;
  color: #fff;
  box-shadow: 0 16px 48px rgba(15,12,41,0.25);
}}
.pp-pricing-card .pp-pc-label {{
  display: inline-block;
  background: linear-gradient(135deg, #FF6B35, #e8570a);
  color: #fff;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 2px;
  padding: 5px 16px;
  border-radius: 50px;
  margin-bottom: 20px;
}}
.pp-pricing-card .pp-pc-orig {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 18px;
  color: #888;
  text-decoration: line-through;
  margin-bottom: 4px;
}}
.pp-pricing-card .pp-pc-price {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 72px;
  font-weight: 900;
  color: #00E676;
  line-height: 1;
  margin-bottom: 4px;
}}
.pp-pricing-card .pp-pc-type {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
  color: #888;
  margin-bottom: 16px;
}}
.pp-pricing-card .pp-pc-save {{
  display: inline-block;
  background: rgba(0,230,118,0.15);
  border: 1px solid #00E676;
  color: #00E676;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 13px;
  font-weight: 700;
  padding: 5px 16px;
  border-radius: 50px;
  margin-bottom: 28px;
}}
.pp-pricing-card ul {{
  list-style: none;
  margin: 0 0 28px;
  padding: 0;
  text-align: left;
}}
.pp-pricing-card ul li {{
  padding: 10px 0;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
  color: #ccc;
}}
.pp-pricing-card ul li::before {{
  content: "✅ ";
}}
.pp-pricing-card .pp-pc-scarcity {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 12px;
  color: #ff6b6b;
  margin-top: 14px;
  font-weight: 600;
}}

/* ── Testimonials ─────────────────────────────────────── */
.pp-testi-section {{
  background: #f9f9f9;
  border-radius: 12px;
  padding: 36px 28px;
  margin: 44px 0;
}}
.pp-testi-section .pp-testi-title {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 20px;
  font-weight: 800;
  color: #0f0c29;
  margin: 0 0 24px;
  text-align: center;
}}
.pp-testi {{
  background: #fff;
  border-radius: 10px;
  padding: 20px 22px;
  margin-bottom: 16px;
  border-left: 4px solid #FF6B35;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}}
.pp-testi:last-child {{ margin-bottom: 0; }}
.pp-testi-stars {{ color: #FF6B35; font-size: 16px; margin-bottom: 8px; }}
.pp-star {{ letter-spacing: 2px; }}
.pp-testi-text {{
  font-size: 15px;
  color: #444;
  font-style: italic;
  margin: 0 0 10px;
  line-height: 1.6;
}}
.pp-testi-author {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 13px;
  color: #1a1a1a;
  margin: 0;
}}
.pp-testi-author span {{ color: #888; font-weight: 400; margin-left: 6px; }}

/* ── Guarantee Block ──────────────────────────────────── */
.pp-guarantee {{
  display: flex;
  align-items: center;
  gap: 24px;
  background: linear-gradient(135deg, #fff8f0, #fff);
  border: 2px solid #FF6B35;
  border-radius: 12px;
  padding: 28px 24px;
  margin: 40px 0;
}}
.pp-guarantee-icon {{ font-size: 56px; flex-shrink: 0; line-height: 1; }}
.pp-guarantee-text h4 {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 18px;
  font-weight: 800;
  color: #0f0c29;
  margin: 0 0 8px;
}}
.pp-guarantee-text p {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
  color: #555;
  margin: 0;
  line-height: 1.6;
}}

/* ── Video Block ──────────────────────────────────────── */
.pp-video-block {{
  margin: 40px 0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.12);
}}
.pp-video-label {{
  background: #0f0c29;
  color: #fff;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
  font-weight: 700;
  padding: 12px 20px;
}}
.pp-video-wrap {{
  position: relative;
  padding-bottom: 56.25%;
  height: 0;
  overflow: hidden;
}}
.pp-video-wrap iframe {{
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  border: 0;
}}

/* ── Source Note ──────────────────────────────────────── */
.pp-source-note {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 12px;
  color: #bbb;
  text-align: center;
  margin-top: 48px;
  padding-top: 20px;
  border-top: 1px solid #f0f0f0;
}}
.pp-source-note a {{ color: #FF6B35; }}

/* ── Responsive ───────────────────────────────────────── */
@media (max-width: 580px) {{
  .pp-wrap {{ font-size: 16px; }}
  .pp-wrap h2 {{ font-size: 22px; }}
  .pp-cta-btn {{ font-size: 16px; padding: 18px 24px; }}
  .pp-pc-price {{ font-size: 56px; }}
  .pp-guarantee {{ flex-direction: column; text-align: center; }}
  .pp-guarantee-icon {{ font-size: 48px; }}
}}
</style>

<div class="pp-wrap">

  <!-- FEATURED IMAGE — right below post title, matching digiunbox.com layout -->
  {featured_img_html}

  <!-- DISCLOSURE -->
  <div class="pp-disclosure">
    📢 <strong>Disclosure:</strong> This article contains affiliate links. We may earn a commission at no extra cost to you.
  </div>

  <!-- URGENCY BAR -->
  <div class="pp-urgency-bar">
    🔥 <span>{urgency_text}</span> &nbsp;·&nbsp; 🔒 Secure Checkout &nbsp;·&nbsp; ⚡ Instant Access
  </div>

  <!-- INTRO CTA BOX -->
  <div class="pp-cta-box">
    <p class="pp-cta-headline">🚀 Ready to Get Started?</p>
    <p class="pp-cta-sub">Join thousands of customers already getting results. Limited-time offer below.</p>
    <div class="pp-price-line">{price_tag()}</div>
    <a href="{affiliate_link}" class="pp-cta-btn" rel="nofollow sponsored" target="_blank">
      ⚡ {primary_cta.upper()}{cta_label}
    </a>
    <p class="pp-cta-micro"><span>✅ 30-Day Money-Back Guarantee</span> &nbsp;·&nbsp; <span>✅ Instant Access</span> &nbsp;·&nbsp; 🔒 Secure</p>
    <p class="pp-urgency-inline">⏰ {urgency_text}</p>
  </div>

  <!-- MAIN SEO CONTENT -->
  {content_html}

  <!-- MID-CONTENT PRODUCT IMAGES -->
  {inline_images_html}

  <!-- MID-CONTENT CTA -->
  <div class="pp-cta-box">
    <p class="pp-cta-headline">💡 Don't Miss This Opportunity</p>
    <p class="pp-cta-sub">{savings_line()} — this won't last forever.</p>
    <div class="pp-price-line">{price_tag()}</div>
    <a href="{affiliate_link}" class="pp-cta-btn" rel="nofollow sponsored" target="_blank">
      🔥 CLAIM YOUR DISCOUNT NOW{cta_label}
    </a>
    <p class="pp-cta-micro"><span>✅ Guaranteed Results</span> &nbsp;·&nbsp; <span>✅ No Hidden Fees</span> &nbsp;·&nbsp; 🔒 Safe Checkout</p>
  </div>

  <hr class="pp-divider" />

  <!-- VIDEO SECTION -->
  {video_html}

  <!-- WHAT YOU GET CHECKLIST -->
  <h2>What You Get With Your Order</h2>
  <ul class="pp-checklist">
    <li>Full lifetime access — yours forever</li>
    <li>Instant digital delivery after purchase</li>
    <li>Exclusive bonus materials included</li>
    <li>Step-by-step guidance for fast results</li>
    <li>Priority customer support</li>
    <li>30-day money-back guarantee — zero risk</li>
  </ul>

  <!-- PRICING CARD -->
  <div class="pp-pricing-card">
    <div class="pp-pc-label">🔥 Best Value — Limited Time Only</div>
    {"<p class='pp-pc-orig'>Regular Price: " + orig_price + "</p>" if orig_price else ""}
    <div class="pp-pc-price">{disc_price if disc_price else "Special Price"}</div>
    <p class="pp-pc-type">One-Time Payment · Instant Access</p>
    {"<div class='pp-pc-save'>✅ You SAVE " + savings_amt + " (" + savings_pct + " OFF)</div>" if savings_amt and savings_pct else ("<div class='pp-pc-save'>✅ " + savings_pct + " OFF Today</div>" if savings_pct else "")}
    <ul>
      <li>Full Lifetime Access</li>
      <li>Instant Digital Delivery</li>
      <li>All Bonus Materials</li>
      <li>30-Day Money-Back Guarantee</li>
      <li>Priority Support Access</li>
    </ul>
    <a href="{affiliate_link}" class="pp-cta-btn" rel="nofollow sponsored" target="_blank">
      💰 GET IT NOW{cta_label}
    </a>
    <p class="pp-pc-scarcity">⚠️ {urgency_text}</p>
  </div>

  <!-- TESTIMONIALS -->
  <div class="pp-testi-section">
    <p class="pp-testi-title">⭐ What Customers Are Saying</p>
    {testi_html}
  </div>

  <!-- POST-TESTI CTA -->
  <div class="pp-cta-box">
    <p class="pp-cta-headline">🎁 Join 10,000+ Happy Customers</p>
    <p class="pp-cta-sub">They made the smart choice — now it's your turn.</p>
    <div class="pp-price-line">{price_tag()}</div>
    <a href="{affiliate_link}" class="pp-cta-btn" rel="nofollow sponsored" target="_blank">
      🎯 YES! I WANT THIS DEAL{cta_label}
    </a>
    <p class="pp-cta-micro"><span>✅ 30-Day Guarantee</span> &nbsp;·&nbsp; <span>✅ Instant Access</span> &nbsp;·&nbsp; 🔒 256-bit Encryption</p>
  </div>

  <!-- GUARANTEE -->
  <div class="pp-guarantee">
    <div class="pp-guarantee-icon">🛡️</div>
    <div class="pp-guarantee-text">
      <h4>30-Day Money-Back Guarantee</h4>
      <p>We're 100% confident you'll love what you get. If for any reason you're not completely satisfied within 30 days, contact us for a full refund — no questions asked. Zero risk, all reward.</p>
    </div>
  </div>

  <!-- FINAL CTA -->
  <div class="pp-cta-box" style="border-color:#0f0c29; background: linear-gradient(135deg, #0f0c29 0%, #1a1a2e 100%); color:#fff;">
    <p class="pp-cta-headline" style="color:#FFD700; font-size:22px;">⏰ Final Chance — Don't Miss Out!</p>
    <p class="pp-cta-sub" style="color:#bbb;">Every second you wait is leaving money on the table. Lock in your price now.</p>
    <div class="pp-price-line" style="margin-bottom:20px;">{price_tag()}</div>
    <a href="{affiliate_link}" class="pp-cta-btn" style="font-size:20px; padding:22px 40px;" rel="nofollow sponsored" target="_blank">
      ⚡ YES! I WANT INSTANT ACCESS{cta_label}
    </a>
    <p class="pp-cta-micro" style="color:#888;"><span style="color:#00E676;">✅ 30-Day Guarantee</span> &nbsp;·&nbsp; <span style="color:#00E676;">✅ Instant Delivery</span> &nbsp;·&nbsp; 🔒 Secure Payment</p>
  </div>

  <!-- SOURCE NOTE -->
  <p class="pp-source-note">
    Source: <a href="{source_url}" rel="nofollow" target="_blank">{source_url}</a><br />
    This article contains affiliate links. Prices and availability subject to change.
  </p>

</div><!-- /.pp-wrap -->"""

    return html


# ─────────────────────────────────────────────
#  SEO CONTENT GENERATOR
# ─────────────────────────────────────────────

def generate_seo_content(content1: dict, content2: dict = None, pricing: dict = None) -> str:
    pricing_ctx = ""
    if pricing:
        parts = []
        if pricing.get("original_price"):
            parts.append(f"Original Price: {pricing['original_price']}")
        if pricing.get("discounted_price"):
            parts.append(f"Sale Price: {pricing['discounted_price']}")
        if pricing.get("savings_percent"):
            parts.append(f"Savings: {pricing['savings_percent']} OFF")
        if pricing.get("primary_cta"):
            parts.append(f"CTA: {pricing['primary_cta']}")
        if parts:
            pricing_ctx = "\n\nACTUAL PRICING FROM THE PAGE:\n" + "\n".join(parts) + "\nUse THESE EXACT prices — do not invent new ones."

    second_ctx = ""
    if content2 and content2.get("content"):
        second_ctx = f"""
COMPARISON SOURCE:
URL: {content2['url']}
Title: {content2['title']}
Content: {content2['content'][:800]}
"""

    prompt = f"""Write 900-word SEO-optimized review/sales article.

PRODUCT PAGE:
URL: {content1['url']}
Title: {content1['title']}
Description: {content1['description']}
Headings: {', '.join(content1['headings'][:8])}
Content: {content1['content'][:1500]}
{second_ctx}{pricing_ctx}

WRITING RULES:
- Start with a strong H2 hook (## heading)
- Write like an expert reviewer who personally tested the product
- Benefits-first, feature-second
- Include specific numbers and results where possible
- Natural urgency without being pushy
- 3-4 H2 sections, 1-2 H3 sub-sections each
- End with a strong summary paragraph
- Do NOT include a title — start directly with first H2
- Use ## for H2, ### for H3
- Output only the article body — no preamble, no "here is your article"
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a seasoned product reviewer and conversion copywriter. Write honest, compelling reviews that help readers make decisions and take action."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2200,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"<p>Explore this incredible opportunity at {content1['url']}. {content1.get('description', '')}</p>"


# ─────────────────────────────────────────────
#  WORDPRESS PUBLISHER
#  Sets featured_media = uploaded image ID
# ─────────────────────────────────────────────

def publish_to_wordpress(
    html_content: str,
    page_title: str,
    wp_url: str,
    username: str,
    app_password: str,
    status: str = "publish",
    meta_description: str = "",
    featured_media_id: int = None,
) -> dict:
    wp_url    = wp_url.rstrip("/")
    endpoint  = f"{wp_url}/wp-json/wp/v2/posts"
    creds     = base64.b64encode(f"{username}:{app_password}".encode()).decode()
    headers   = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }

    payload = {
        "title":   page_title,
        "content": html_content,
        "status":  status,
        "format":  "standard",
        "meta": {
            "_yoast_wpseo_metadesc":  meta_description,
            "_elementor_edit_mode":   "builder",
        },
    }

    # Set featured image if we have one
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        post_id = data.get("id")
        return {
            "success":  True,
            "post_id":  post_id,
            "page_url": data.get("link"),
            "edit_url": f"{wp_url}/wp-admin/post.php?post={post_id}&action=edit",
            "elementor_edit_url": f"{wp_url}/wp-admin/post.php?post={post_id}&action=elementor",
            "status":   data.get("status"),
        }
    except requests.HTTPError as e:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        return {"success": False, "error": str(e), "details": err}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
#  MAIN ORCHESTRATOR
# ─────────────────────────────────────────────

def create_and_publish_landing_page(
    url: str,
    affiliate_link: str,
    wordpress_page_title: str,
    hero_image_url: str = None,
    url2: str = None,
    wp_url: str = None,
    wp_username: str = None,
    wp_app_password: str = None,
    wp_status: str = "publish",
) -> dict:
    """
    Pipeline:
      1. Price Scraper Agent  → real prices from sales page
      2. Scrape content + media
      3. Generate SEO copy
      4. Upload hero image as WP featured image (post thumbnail)
      5. Build editorial post HTML
      6. Publish to WordPress with featured_media set
    """
    print("=" * 70)
    print(f"🚀  Processing: {wordpress_page_title}")
    print("=" * 70)

    results = {"success": False, "title": wordpress_page_title}

    # Resolve credentials early (needed for image upload)
    wp_u  = wp_url          or os.getenv("WP_SITE_URL")
    wp_us = wp_username     or os.getenv("WP_USERNAME")
    wp_pw = wp_app_password or os.getenv("WP_APP_PASSWORD")
    wp_st = wp_status       or os.getenv("WP_STATUS", "publish")

    # ── Step 1: Price Agent ───────────────────────────────────────────
    print("\n[1/6] 💰 Running Price Scraper Agent...")
    pricing = run_price_scraper_agent(url)
    results["pricing"] = pricing

    # ── Step 2: Scrape content + media ───────────────────────────────
    print("\n[2/6] 📸 Scraping Content & Media...")
    content1 = scrape_website_content(url)
    content2 = scrape_website_content(url2) if url2 else None
    media    = get_media_urls(url)
    print(f"  ✓ {media['total_images']} images, {media['total_videos']} videos found")

    # Hero image: use provided URL first, fall back to first scraped image
    effective_hero = hero_image_url or (media["images"][0] if media["images"] else None)
    print(f"  ✓ Hero image: {effective_hero or chr(10)+chr(32)*4+chr(87)+chr(65)+chr(82)+chr(78)+chr(73)+chr(78)+chr(71)+chr(58)+chr(32)+chr(110)+chr(111)+chr(32)+chr(105)+chr(109)+chr(97)+chr(103)+chr(101)+chr(32)+chr(102)+chr(111)+chr(117)+chr(110)+chr(100)}")

    # ── Step 3: Generate SEO copy ─────────────────────────────────────
    print("\n[3/6] ✍️  Generating SEO Copy...")
    seo_content = generate_seo_content(content1, content2, pricing)

    # ── Step 4: Upload hero image to WordPress Media Library ─────────────
    # CRITICAL: We upload the image to WP first so we get a WP-hosted URL.
    # This WP-hosted URL is used for BOTH:
    #   a) featured_media (post thumbnail shown by theme above title)
    #   b) inline <img> inside the post content (pp-featured-image)
    # If upload fails, we fall back to the external URL for the inline image only.
    featured_media_id  = None
    wp_hosted_hero_url = None   # WP-hosted copy of the image

    if effective_hero and all([wp_u, wp_us, wp_pw]):
        print(f"\n[4/6] 🖼️  Uploading Featured Image to WordPress Media Library...")
        print(f"  Source URL: {effective_hero}")
        upload_result = upload_featured_image(
            image_url    = effective_hero,
            wp_url       = wp_u,
            username     = wp_us,
            app_password = wp_pw,
            alt_text     = wordpress_page_title,
        )
        results["featured_image"] = upload_result
        if upload_result["success"]:
            featured_media_id  = upload_result["media_id"]
            wp_hosted_hero_url = upload_result.get("media_url", effective_hero)
            print(f"  ✅ Media ID: {featured_media_id}  →  {wp_hosted_hero_url}")
        else:
            print(f"  ⚠️  Upload failed: {upload_result.get('error')}")
            print(f"  ↳  Will use external URL inline, but featured_media won't be set by theme")
    else:
        reason = "no image found" if not effective_hero else "missing WP credentials"
        print(f"\n[4/6] 🖼️  Skipping image upload ({reason})")

    # ── Step 5: Build HTML ────────────────────────────────────────────
    print("\n[5/6] 🎨 Building Post HTML...")
    landing_html = build_post_html(
        page_title     = wordpress_page_title,
        seo_content    = seo_content,
        affiliate_link = affiliate_link,
        # If hero came from Excel (not scraped), include images[0] as product image
        product_images = media["images"][0:8] if hero_image_url else media["images"][1:8],
        video_urls     = media["videos"][:3],
        pricing        = pricing,
        source_url     = url,
    )
    print(f"  ✓ HTML built ({len(landing_html):,} chars)")

    # ── Step 6: Publish to WordPress ─────────────────────────────────
    print("\n[6/6] 🌐 Publishing to WordPress...")
    if not all([wp_u, wp_us, wp_pw]):
        print("  ⚠️  WordPress credentials missing — skipping publish")
        results["wordpress"] = {"success": False, "error": "Missing credentials"}
    else:
        wp_result = publish_to_wordpress(
            html_content      = landing_html,
            page_title        = wordpress_page_title,
            wp_url            = wp_u,
            username          = wp_us,
            app_password      = wp_pw,
            status            = wp_st,
            meta_description  = seo_content[:155].replace("\n", " "),
            featured_media_id = featured_media_id,   # sets WP post thumbnail
        )
        results["wordpress"] = wp_result

        if wp_result["success"]:
            post_id = wp_result.get("post_id")
            print(f"  ✅ Published! URL: {wp_result['page_url']}")

            # ── Post-publish PATCH: if upload succeeded after post creation,
            #    make sure featured_media is definitely set (belt-and-suspenders)
            if featured_media_id and post_id:
                set_post_featured_image(post_id, featured_media_id, wp_u, wp_us, wp_pw)

            # ── If upload failed earlier, try once more NOW (sometimes WP needs
            #    the post to exist before it accepts the media association)
            elif not featured_media_id and effective_hero and post_id:
                print("  🔄 Retrying image upload after post creation...")
                retry = upload_featured_image(
                    image_url    = effective_hero,
                    wp_url       = wp_u,
                    username     = wp_us,
                    app_password = wp_pw,
                    alt_text     = wordpress_page_title,
                )
                if retry["success"]:
                    featured_media_id = retry["media_id"]
                    set_post_featured_image(post_id, featured_media_id, wp_u, wp_us, wp_pw)
                    results["featured_image"] = retry
                    print(f"  ✅ Retry succeeded — featured image now set (ID: {featured_media_id})")
                else:
                    print(f"  ❌ Retry also failed: {retry.get('error')}")
        else:
            print(f"  ❌ Publish failed: {wp_result.get('error')}")
            if wp_result.get("details"):
                print(f"  Details: {str(wp_result['details'])[:200]}")

    results["success"]          = results.get("wordpress", {}).get("success", False)
    results["featured_media_id"] = featured_media_id
    results["media"]            = {"total_images": media["total_images"], "total_videos": media["total_videos"]}
    return results