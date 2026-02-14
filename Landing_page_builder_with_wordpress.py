import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openai import OpenAI
import os
from dotenv import load_dotenv
import re
import json

# Import WordPress publisher (fixed version that handles styles properly)
from simple_wp_publisher_fixed import post_html_to_wordpress

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ===================== HELPER FUNCTIONS =====================

def get_media_urls(url):
    """
    Extract all image and video URLs from a given website.
    
    Parameters:
    url (str): The website URL to scrape
    
    Returns:
    dict: A dictionary containing lists of image and video URLs
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract image URLs
        image_urls = set()
        
        # Find all <img> tags
        for img in soup.find_all('img'):
            img_url = img.get('src') or img.get('data-src')
            if img_url:
                absolute_url = urljoin(url, img_url)
                image_urls.add(absolute_url)
        
        # Find images in <source> tags (for <picture> elements)
        for source in soup.find_all('source'):
            srcset = source.get('srcset')
            if srcset:
                for src in srcset.split(','):
                    img_url = src.strip().split()[0]
                    absolute_url = urljoin(url, img_url)
                    image_urls.add(absolute_url)
        
        # Extract video URLs
        video_urls = set()
        
        # Find all <video> tags
        for video in soup.find_all('video'):
            video_src = video.get('src')
            if video_src:
                absolute_url = urljoin(url, video_src)
                video_urls.add(absolute_url)
            
            # Check <source> tags within <video>
            for source in video.find_all('source'):
                src = source.get('src')
                if src:
                    absolute_url = urljoin(url, src)
                    video_urls.add(absolute_url)
        
        # Find iframe embeds (YouTube, Vimeo, etc.)
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src')
            if iframe_src and ('youtube' in iframe_src or 'vimeo' in iframe_src):
                absolute_url = urljoin(url, iframe_src)
                video_urls.add(absolute_url)
        
        return {
            'images': list(image_urls),
            'videos': list(video_urls),
            'total_images': len(image_urls),
            'total_videos': len(video_urls)
        }
        
    except Exception as e:
        return {
            'error': f'Error fetching media: {str(e)}',
            'images': [],
            'videos': [],
            'total_images': 0,
            'total_videos': 0
        }


def scrape_website_content(url):
    """
    Scrape and extract main content from a website.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
        
        # Extract title
        title = soup.find('title')
        title_text = title.get_text().strip() if title else ""
        
        # Extract headings
        headings = []
        for heading in soup.find_all(['h1', 'h2', 'h3']):
            headings.append(heading.get_text().strip())
        
        # Extract main text content
        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if len(text) > 20:
                paragraphs.append(text)
        
        # Extract meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        description = meta_desc['content'] if meta_desc and meta_desc.get('content') else ""
        
        return {
            'url': url,
            'title': title_text,
            'description': description,
            'headings': headings[:10],
            'content': ' '.join(paragraphs[:20])
        }
        
    except Exception as e:
        return {
            'url': url,
            'error': f'Error scraping URL: {str(e)}',
            'title': '',
            'description': '',
            'headings': [],
            'content': ''
        }


def parse_seo_content(seo_text):
    """
    Parse SEO content to extract title, meta description, and keywords.
    """
    seo_data = {
        'title': '',
        'meta_description': '',
        'keywords': [],
        'content': seo_text
    }
    
    # Extract SEO Title
    title_match = re.search(r'SEO Title:\s*(.+?)(?:\n|$)', seo_text, re.IGNORECASE)
    if title_match:
        seo_data['title'] = title_match.group(1).strip()
    
    # Extract Meta Description
    meta_match = re.search(r'Meta Description:\s*(.+?)(?:\n|$)', seo_text, re.IGNORECASE)
    if meta_match:
        seo_data['meta_description'] = meta_match.group(1).strip()
    
    # Extract Keywords
    keywords_match = re.search(r'Keywords:\s*(.+?)(?:\n\n|\n-|$)', seo_text, re.IGNORECASE | re.DOTALL)
    if keywords_match:
        keywords_text = keywords_match.group(1).strip()
        seo_data['keywords'] = [k.strip() for k in keywords_text.replace(',', '\n').split('\n') if k.strip()]
    
    return seo_data


# ===================== MAIN ALL-IN-ONE FUNCTION =====================

def create_affiliate_landing_page(
    url, 
    affiliate_link, 
    url2=None, 
    output_dir="output",
    publish_to_wordpress=False,
    wordpress_url=None,
    wordpress_username=None,
    wordpress_app_password=None,
    wordpress_page_title=None,
    wordpress_status='draft'
):
    """
    ALL-IN-ONE FUNCTION: Creates a complete landing page with:
    - Extracted images and videos from the URL
    - SEO-optimized content
    - Affiliate links on all CTAs
    - OPTIONAL: Publish directly to WordPress
    
    Parameters:
    url (str): Primary website URL to analyze
    affiliate_link (str): Your affiliate link for CTAs
    url2 (str): Optional second URL for comparison
    output_dir (str): Directory to save output files
    publish_to_wordpress (bool): If True, publish to WordPress after generation
    wordpress_url (str): WordPress site URL (required if publish_to_wordpress=True)
    wordpress_username (str): WordPress username (or from .env)
    wordpress_app_password (str): WordPress app password (or from .env)
    wordpress_page_title (str): Custom page title for WordPress
    wordpress_status (str): 'draft' or 'publish'
    
    Returns:
    dict: Complete results with file paths and WordPress info
    """
    
    print("="*80)
    print("🚀 AFFILIATE LANDING PAGE GENERATOR")
    print("="*80)
    
    results = {
        'success': False,
        'media': {},
        'seo': {},
        'landing_page': {},
        'files': [],
        'wordpress': {}
    }
    
    # ============== STEP 1: Extract Media URLs ==============
    print("\n[STEP 1/5] 📸 Extracting Images and Videos...")
    print("-"*80)
    
    media_data = get_media_urls(url)
    results['media'] = media_data
    
    print(f"✓ Found {media_data['total_images']} images")
    print(f"✓ Found {media_data['total_videos']} videos")
    
    if media_data['total_images'] > 0:
        print(f"\nSample images (first 3):")
        for img in media_data['images'][:3]:
            print(f"  • {img}")
    
    if media_data['total_videos'] > 0:
        print(f"\nSample videos (first 3):")
        for vid in media_data['videos'][:3]:
            print(f"  • {vid}")
    
    # ============== STEP 2: Generate SEO Content ==============
    print("\n[STEP 2/5] ✍️ Generating SEO-Optimized Content...")
    print("-"*80)
    
    content1 = scrape_website_content(url)
    content2 = scrape_website_content(url2) if url2 else None
    
    # Build SEO prompt
    if content2:
        seo_prompt = f"""Analyze these two websites and create comprehensive SEO-optimized content:

**Website 1:**
URL: {content1['url']}
Title: {content1['title']}
Description: {content1['description']}
Key Headings: {', '.join(content1['headings'])}
Content Preview: {content1['content'][:1000]}

**Website 2:**
URL: {content2['url']}
Title: {content2['title']}
Description: {content2['description']}
Key Headings: {', '.join(content2['headings'])}
Content Preview: {content2['content'][:1000]}

Create SEO-optimized content for a HIGH-CONVERTING AFFILIATE SALES PAGE that:
1. Combines insights from both websites with EXCITEMENT
2. Includes a compelling SEO title (55-60 characters) with power words
3. Includes a meta description (150-160 characters) that creates curiosity
4. Has 5-7 relevant keywords
5. Includes engaging H1, H2, and H3 headings that grab attention
6. Contains 800-1000 words of PERSUASIVE, MONEY-MAKING copy
7. Highlights benefits over features (what's in it for them)
8. Creates URGENCY and FOMO throughout
9. Includes psychological triggers (scarcity, social proof potential)
10. Drives readers toward taking IMMEDIATE action

Format the output EXACTLY as:
SEO Title: [title]
Meta Description: [description]
Keywords: [keyword1, keyword2, keyword3, etc.]

Content:
[full article with H1, H2, H3 headings and persuasive paragraphs optimized for conversions]"""
    else:
        seo_prompt = f"""Analyze this website and create comprehensive SEO-optimized content:

**Website:**
URL: {content1['url']}
Title: {content1['title']}
Description: {content1['description']}
Key Headings: {', '.join(content1['headings'])}
Content Preview: {content1['content'][:1500]}

Create SEO-optimized content for a HIGH-CONVERTING AFFILIATE SALES PAGE that:
1. Expands on the website's main topics and products with EXCITEMENT
2. Includes a compelling SEO title (55-60 characters) with power words
3. Includes a meta description (150-160 characters) that creates curiosity
4. Has 5-7 relevant keywords
5. Includes engaging H1, H2, and H3 headings that grab attention
6. Contains 800-1000 words of PERSUASIVE, MONEY-MAKING copy
7. Highlights benefits over features (what's in it for them)
8. Creates URGENCY and FOMO throughout
9. Includes psychological triggers (scarcity, social proof potential)
10. Drives readers toward taking IMMEDIATE action

Format the output EXACTLY as:
SEO Title: [title]
Meta Description: [description]
Keywords: [keyword1, keyword2, keyword3, etc.]

Content:
[full article with H1, H2, H3 headings and persuasive paragraphs optimized for conversions]"""
    
    try:
        seo_response = client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {
                    "role": "system",
                    "content": "You are a world-class direct-response copywriter and SEO specialist. You write conversion-focused sales copy that gets people to take ACTION. Your writing creates urgency, highlights massive value, and compels readers to click. Use power words, emotional triggers, and psychological tactics that drive conversions."
                },
                {
                    "role": "user",
                    "content": seo_prompt
                }
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        seo_content = seo_response.choices[0].message.content
        parsed_seo = parse_seo_content(seo_content)
        
        results['seo'] = {
            'success': True,
            'content': seo_content,
            'parsed': parsed_seo,
            'word_count': len(seo_content.split()),
            'tokens_used': seo_response.usage.total_tokens
        }
        
        print(f"✓ SEO Content Generated!")
        print(f"  Title: {parsed_seo['title']}")
        print(f"  Words: {len(seo_content.split())}")
        print(f"  Keywords: {', '.join(parsed_seo['keywords'][:3])}...")
        
    except Exception as e:
        results['seo'] = {'success': False, 'error': str(e)}
        print(f"✗ Error generating SEO: {str(e)}")
        return results
    
    # ============== STEP 3: Generate Landing Page with Everything ==============
    print("\n[STEP 3/5] 🎨 Creating Affiliate Landing Page...")
    print("-"*80)
    
    # Prepare media URLs as JSON for the prompt
    images_json = json.dumps(media_data['images'][:10], indent=2)  # Top 10 images
    videos_json = json.dumps(media_data['videos'][:5], indent=2)    # Top 5 videos
    
    landing_prompt = f"""Create a HIGH-CONVERTING AFFILIATE SALES PAGE with MAXIMUM CONVERSIONS. This must be a money-making machine!

**SOURCE WEBSITE:**
URL: {content1['url']}
Title: {content1['title']}

**SEO INFORMATION:**
Page Title: {parsed_seo['title']}
Meta Description: {parsed_seo['meta_description']}
Keywords: {', '.join(parsed_seo['keywords'])}

**AFFILIATE LINK (USE EVERYWHERE):**
{affiliate_link}
CRITICAL: ALL buttons, CTAs, and clickable elements MUST link to this affiliate URL.

**AVAILABLE MEDIA:**
Images to use (pick the best ones):
{images_json}

Videos to embed:
{videos_json}

**SEO CONTENT TO INCLUDE:**
{seo_content[:2000]}

**REQUIREMENTS - HIGH CONVERTING SALES PAGE:**
Create a production-ready, money-making affiliate sales page with:

1. **HTML Structure:**
   - Proper DOCTYPE and HTML5 tags
   - SEO meta tags (title, description, keywords, Open Graph)
   - Mobile-responsive viewport settings

2. **HERO SECTION (CRITICAL - Must Grab Attention):**
   - MASSIVE headline (48-64px) using power words
   - Compelling subheadline with benefit promise
   - Hero image from the provided images
   - **MEGA CTA BUTTON** (This is the most important element!):
     * Size: MINIMUM 320px wide × 70px tall
     * Font-size: 22-26px, BOLD, uppercase
     * Gradient: Linear gradient from #FF6B35 to #F7931E (orange) OR #00C853 to #00E676 (green)
     * Border-radius: 50px (pill shape)
     * Box-shadow: 0 8px 25px rgba(0,0,0,0.3), 0 0 40px rgba(255,107,53,0.4)
     * Hover: transform: scale(1.08), brighter gradient
     * Text: "🚀 GET INSTANT ACCESS - 80% OFF TODAY" or "⚡ CLAIM YOUR DISCOUNT NOW"
   - **PRICE SLASH DISPLAY** right next to/below CTA:
     * Original price: LARGE crossed out (~~$297~~) - color: #999, font-size: 32px
     * Discounted price: HUGE in green/red ($47) - font-size: 56px, font-weight: 900
     * Savings badge: "🔥 SAVE $250 (84% OFF!)" in bright red/yellow badge
     * Add urgency text: "⏰ Price increases in 24 hours!"

3. **PRICING SECTION (Must Show Massive Value):**
   - Create a prominent pricing card with dark/bright background
   - Display THREE price points vertically:
     * REGULAR PRICE: ~~$497~~ (strikethrough, gray, 28px)
     * TODAY'S PRICE: $67 (HUGE, green or red, 72px, bold)
     * YOU SAVE: $430 (87% OFF) in bright yellow/green badge
   - Add "BEST VALUE" or "🔥 LIMITED TIME OFFER" badge
   - Include comparison visual: "Others charge $997 → You pay only $67"
   - Add scarcity text: "⚠️ Only 23 spots left at this price!"
   - HUGE CTA button below pricing with same specs as hero

4. **Product Features Section:**
   - Use 3-6 best images from the list
   - Feature cards with images, icons, titles, descriptions
   - Each card should have a smaller CTA linking to: {affiliate_link}

5. **Video Section (if videos available):**
   - Embed videos using iframe or video tags
   - Add "Watch Now" text with play icon
   - Add MEGA CTA button below video: "🚀 GET ACCESS NOW - SPECIAL PRICE"

6. **SEO Content Section:**
   - Include the full SEO-optimized content
   - Properly formatted with H2/H3 headings
   - Add 2-3 CTA buttons within content sections
   - Highlight key benefits in colored boxes

7. **Social Proof Section:**
   - Testimonials (4-5) with photos, names, 5-star ratings
   - "⭐⭐⭐⭐⭐ Verified Purchase" badges
   - Real-looking review text praising the product
   - Add "Join 10,000+ Happy Customers" counter
   - Trust badges: SSL, Money-Back Guarantee icons

8. **GUARANTEE Section:**
   - 30-Day Money Back Guarantee badge (large, prominent)
   - "100% Risk-Free" text
   - Shield icon or checkmark
   - "If you're not satisfied, get a full refund - no questions asked"

9. **Call-to-Action Sections (MINIMUM 5 HUGE CTAs):**
   - Place CTAs strategically throughout:
     * After hero section
     * After features
     * After pricing
     * After testimonials
     * At the end (final push)
   - **CTA Button Specs (ALL must follow this):**
     * Minimum: 280px wide × 65px tall
     * Font: 20-24px, bold, uppercase
     * Gradient background (orange→red, green→blue, or red→orange)
     * Box-shadow for 3D depth effect
     * Hover: scale up 5-8%, glow effect
     * Add animation: subtle pulse or glow every 2 seconds
   - **Button text examples (use variations):**
     * "🚀 GET INSTANT ACCESS - 84% OFF"
     * "⚡ YES! I WANT THIS DEAL NOW"
     * "🔥 CLAIM YOUR 80% DISCOUNT"
     * "💰 UNLOCK HUGE SAVINGS NOW"
     * "🎁 GET IT BEFORE IT'S GONE"
   - **Micro-copy below EACH button:**
     * "✅ 30-Day Money-Back Guarantee • ✅ Instant Access • ✅ Secure Checkout"
     * "🔒 Your purchase is 100% secure and encrypted"

10. **URGENCY & SCARCITY Elements (CRITICAL):**
    - Countdown timer visual (placeholder): "⏰ Offer expires in: 02:47:33"
    - "🔥 47 people are viewing this page right now"
    - "📦 Only 17 copies remaining at this price"
    - "💰 Price goes up to $297 in 2 hours"
    - Add these near CTAs and pricing sections

11. **Footer:**
    - Quick links
    - Disclaimer: "This page contains affiliate links. We may earn a commission at no extra cost to you."
    - Contact info
    - Copyright

12. **Design Requirements:**
    - HIGH-CONVERTING colors: Use red (#FF0000) for urgency, green (#00C853) for savings, orange (#FF6B35) for CTAs
    - Dark sections for pricing (creates contrast and focus)
    - Gradient backgrounds on key sections
    - Smooth hover animations on all buttons
    - Mobile-first responsive (buttons must remain HUGE on mobile)
    - White space around CTAs to make them pop
    - Use icons and emojis to increase engagement

13. **Technical:**
    - Inline CSS (no external stylesheets)
    - Clean, semantic HTML5
    - Fast loading optimization
    - Accessibility considerations
    - Add CSS animations for buttons:
      ```css
      @keyframes pulse {{
        0%, 100% {{ box-shadow: 0 0 0 0 rgba(255, 107, 53, 0.7); }}
        50% {{ box-shadow: 0 0 0 20px rgba(255, 107, 53, 0); }}
      }}
      .mega-cta {{ animation: pulse 2s infinite; }}
      ```

CRITICAL RULES - THESE ARE NON-NEGOTIABLE:
- ⚠️ Every single button, link, and CTA MUST use href="{affiliate_link}"
- ⚠️ CTA buttons must be HUGE (minimum 280px × 65px) - this is for conversions!
- ⚠️ Show SLASHED PRICES everywhere (~~$297~~ → $47) - create perceived value!
- ⚠️ Include urgency/scarcity elements throughout
- ⚠️ Use actual images from the provided image URLs
- ⚠️ Make it IMPOSSIBLE to miss the CTA buttons
- ⚠️ The page should feel like a LIMITED-TIME OPPORTUNITY
- ⚠️ Every section should drive toward clicking the affiliate link

Provide ONLY the complete HTML code. No explanations, no markdown formatting, just pure HTML that will convert visitors into buyers!"""

    try:
        landing_response = client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {
                    "role": "system",
                    "content": "You are an elite direct-response copywriter and conversion-focused web designer. You create money-making affiliate sales pages that generate massive conversions. Your specialties: HUGE attention-grabbing CTA buttons, psychological pricing tactics (slashed prices, discount badges), urgency/scarcity elements, and persuasive copy that compels visitors to BUY NOW. Every element you design is optimized for maximum conversions and revenue. Output ONLY valid HTML code with inline CSS."
                },
                {
                    "role": "user",
                    "content": landing_prompt
                }
            ],
            temperature=0.7,
            max_tokens=10000
        )
        
        landing_html = landing_response.choices[0].message.content
        
        # Clean up HTML
        if '```html' in landing_html:
            landing_html = landing_html.split('```html')[1].split('```')[0].strip()
        elif '```' in landing_html:
            landing_html = landing_html.split('```')[1].split('```')[0].strip()
        
        results['landing_page'] = {
            'success': True,
            'html': landing_html,
            'file_size': len(landing_html),
            'tokens_used': landing_response.usage.total_tokens
        }
        
        print(f"✓ Landing Page Generated!")
        print(f"  HTML Size: {len(landing_html)} characters")
        print(f"  Images Used: {min(10, media_data['total_images'])}")
        print(f"  Videos Used: {min(5, media_data['total_videos'])}")
        print(f"  Affiliate Link: {affiliate_link}")
        
    except Exception as e:
        results['landing_page'] = {'success': False, 'error': str(e)}
        print(f"✗ Error generating landing page: {str(e)}")
        return results
    
    # ============== STEP 4: Save All Files ==============
    print("\n[STEP 4/5] 💾 Saving Files...")
    print("-"*80)
    
    # Create output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    saved_files = []
    
    # Save media URLs
    media_file = os.path.join(output_dir, 'media_urls.json')
    with open(media_file, 'w', encoding='utf-8') as f:
        json.dump(media_data, f, indent=2)
    saved_files.append(media_file)
    print(f"✓ Media URLs: {media_file}")
    
    # Save SEO content
    seo_file = os.path.join(output_dir, 'seo_content.txt')
    with open(seo_file, 'w', encoding='utf-8') as f:
        f.write(seo_content)
    saved_files.append(seo_file)
    print(f"✓ SEO Content: {seo_file}")
    
    # Save landing page
    html_file = os.path.join(output_dir, 'affiliate_landing_page.html')
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(landing_html)
    saved_files.append(html_file)
    print(f"✓ Landing Page: {html_file}")
    
    # Save metadata
    metadata = {
        'source_url': url,
        'affiliate_link': affiliate_link,
        'seo_title': parsed_seo['title'],
        'seo_description': parsed_seo['meta_description'],
        'keywords': parsed_seo['keywords'],
        'total_images': media_data['total_images'],
        'total_videos': media_data['total_videos'],
        'word_count': len(seo_content.split()),
        'generated_at': str(os.path.getmtime(html_file)) if os.path.exists(html_file) else None
    }
    
    metadata_file = os.path.join(output_dir, 'metadata.json')
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    saved_files.append(metadata_file)
    print(f"✓ Metadata: {metadata_file}")
    
    results['files'] = saved_files
    results['success'] = True
    
    # ============== STEP 5: Publish to WordPress (Optional) ==============
    if publish_to_wordpress:
        print("\n[STEP 5/5] 🚀 Publishing to WordPress...")
        print("-"*80)
        
        try:
            # Use credentials from parameters or environment variables
            wp_username = wordpress_username or os.getenv('WP_USERNAME')
            wp_password = wordpress_app_password or os.getenv('WP_APP_PASSWORD')
            wp_url = wordpress_url or os.getenv('WP_SITE_URL')
            
            if not wp_url or not wp_username or not wp_password:
                print("✗ WordPress credentials missing!")
                print("  Set WP_USERNAME, WP_APP_PASSWORD, WP_SITE_URL in .env")
                print("  Or pass them as parameters")
                results['wordpress'] = {
                    'success': False,
                    'error': 'Missing WordPress credentials'
                }
            else:
                # Publish to WordPress using the HTML content (not file)
                wp_result = post_html_to_wordpress(
                    html_content=landing_html,  # Pass HTML content directly
                    wordpress_url=wp_url,
                    username=wp_username,
                    app_password=wp_password,
                    page_title=wordpress_page_title or parsed_seo['title'],
                    status=wordpress_status,
                    fix_wordpress_styles=True  # Enable style fixes for buttons/CSS
                )
                
                results['wordpress'] = wp_result
                
                if wp_result['success']:
                    print(f"✓ Published to WordPress!")
                    print(f"  Page URL: {wp_result['page_url']}")
                    print(f"  Page ID: {wp_result['page_id']}")
                    print(f"  Status: {wp_result['status']}")
                else:
                    print(f"✗ WordPress publishing failed!")
                    print(f"  Error: {wp_result.get('error', 'Unknown error')}")
                    
        except Exception as e:
            print(f"✗ Error publishing to WordPress: {str(e)}")
            results['wordpress'] = {
                'success': False,
                'error': str(e)
            }
    else:
        print("\n[STEP 5/5] ⏭️ Skipping WordPress Publishing")
        print("-"*80)
        print("  Set publish_to_wordpress=True to publish automatically")
    
    # ============== Final Summary ==============
    print("\n" + "="*80)
    print("✅ GENERATION COMPLETE!")
    print("="*80)
    print(f"\n📊 Summary:")
    print(f"  • Images Found: {media_data['total_images']}")
    print(f"  • Videos Found: {media_data['total_videos']}")
    print(f"  • SEO Words: {len(seo_content.split())}")
    print(f"  • HTML Size: {len(landing_html)} chars")
    print(f"  • Affiliate Link: {affiliate_link}")
    
    if publish_to_wordpress and results['wordpress'].get('success'):
        print(f"\n🌐 WordPress:")
        print(f"  • Published: ✅")
        print(f"  • URL: {results['wordpress']['page_url']}")
    
    print(f"\n📁 Files Generated:")
    for file in saved_files:
        print(f"  • {file}")
    print("\n🎉 Your affiliate landing page is ready!")
    print(f"   Open: {html_file}")
    print("="*80)
    
    return results
