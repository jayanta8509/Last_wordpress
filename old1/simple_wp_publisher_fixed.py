"""
Improved WordPress HTML Publisher
Handles CSS, buttons, and styling properly in WordPress
"""

import requests
import base64
import re
from typing import Optional


def post_html_to_wordpress(
    html_content: str,
    wordpress_url: str,
    username: str,
    app_password: str,
    page_title: Optional[str] = None,
    status: str = 'draft',
    fix_wordpress_styles: bool = True
) -> dict:
    """
    Post HTML content directly to WordPress as a page.
    
    Args:
        html_content: Your complete HTML code (string)
        wordpress_url: WordPress site URL (e.g., 'https://yoursite.com')
        username: WordPress username
        app_password: WordPress Application Password
        page_title: Page title (optional, will extract from HTML if None)
        status: 'draft' or 'publish'
        fix_wordpress_styles: If True, wraps content in WordPress-friendly container
    
    Returns:
        dict: {
            'success': True/False,
            'page_id': 123,
            'page_url': 'https://yoursite.com/page',
            'message': 'Success message'
        }
    """
    
    try:
        # Extract title from HTML if not provided
        if not page_title:
            title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE)
            page_title = title_match.group(1).strip() if title_match else "Landing Page"
        
        # Extract CSS from head
        css_content = ""
        css_match = re.search(r'<style[^>]*>(.*?)</style>', html_content, re.IGNORECASE | re.DOTALL)
        if css_match:
            css_content = css_match.group(1).strip()
        
        # Extract body content from HTML
        body_content = html_content
        if '<html' in html_content.lower():
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.IGNORECASE | re.DOTALL)
            if body_match:
                body_content = body_match.group(1).strip()
        
        # Fix WordPress styling issues
        if fix_wordpress_styles:
            # Wrap content in a container that preserves styling
            body_content = f"""
<!-- WordPress Landing Page Container -->
<div id="landing-page-wrapper" style="width: 100%; max-width: 100%; margin: 0; padding: 0; overflow-x: hidden;">

    <!-- Inline Styles -->
    <style type="text/css">
        /* Reset WordPress theme styles */
        #landing-page-wrapper * {{
            box-sizing: border-box;
        }}

        #landing-page-wrapper {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
        }}

        /* Preserve original styles */
        {css_content}

        /* ============================================= */
        /* CRITICAL: FORCE CTA BUTTONS TO BE VISIBLE */
        /* ============================================= */
        #landing-page-wrapper .mega-cta,
        #landing-page-wrapper .mega-cta-final,
        #landing-page-wrapper a.mega-cta,
        #landing-page-wrapper a.mega-cta-final {{
            display: inline-block !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            position: relative !important;
            z-index: 999 !important;
            /* Force these styles */
            min-width: 280px !important;
            padding: 22px 50px !important;
            font-size: 24px !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            text-decoration: none !important;
            text-align: center !important;
            color: #ffffff !important;
            background: linear-gradient(135deg, #FF6B35 0%, #F7931E 100%) !important;
            border: none !important;
            border-radius: 50px !important;
            box-shadow: 0 8px 25px rgba(0,0,0,0.3), 0 0 40px rgba(255,107,53,0.4) !important;
            cursor: pointer !important;
            margin: 20px auto !important;
            line-height: 1.4 !important;
        }}

        /* Final CTA - bigger */
        #landing-page-wrapper .mega-cta-final {{
            min-width: 400px !important;
            padding: 25px 60px !important;
            font-size: 28px !important;
            background: linear-gradient(135deg, #FF6B35 0%, #FF4500 50%, #DC143C 100%) !important;
            border-radius: 60px !important;
        }}

        /* Ensure ALL links/buttons are visible */
        #landing-page-wrapper a[href],
        #landing-page-wrapper button {{
            display: inline-block !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }}

        /* Fix common WordPress theme conflicts */
        #landing-page-wrapper .wp-block-button__link {{
            all: unset;
        }}

        /* Ensure CTAs are visible */
        #landing-page-wrapper .cta,
        #landing-page-wrapper .btn,
        #landing-page-wrapper .button,
        #landing-page-wrapper [class*="cta"],
        #landing-page-wrapper [class*="btn"] {{
            display: inline-block !important;
            visibility: visible !important;
            opacity: 1 !important;
        }}

        /* Mobile responsive for CTAs */
        @media (max-width: 768px) {{
            #landing-page-wrapper .mega-cta,
            #landing-page-wrapper .mega-cta-final {{
                display: block !important;
                width: 100% !important;
                max-width: 100% !important;
                min-width: auto !important;
                padding: 18px 25px !important;
                font-size: 18px !important;
                margin: 15px 0 !important;
                border-radius: 30px !important;
            }}
        }}

        /* Pricing section styles */
        #landing-page-wrapper .price-slash {{
            text-decoration: line-through !important;
            color: #999 !important;
            font-size: 32px !important;
        }}

        #landing-page-wrapper .price-new {{
            font-size: 56px !important;
            font-weight: 900 !important;
            color: #00C853 !important;
        }}

        #landing-page-wrapper .savings-badge {{
            display: inline-block !important;
            padding: 8px 20px !important;
            background: linear-gradient(135deg, #FF0000, #FF4500) !important;
            color: #fff !important;
            font-size: 18px !important;
            font-weight: bold !important;
            border-radius: 25px !important;
        }}

        /* Final CTA section */
        #landing-page-wrapper .final-cta-section {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%) !important;
            padding: 60px 20px !important;
            text-align: center !important;
            border-radius: 20px !important;
            margin: 40px auto !important;
            max-width: 800px !important;
        }}

        #landing-page-wrapper .final-cta-section h2 {{
            color: #fff !important;
            font-size: 36px !important;
            margin-bottom: 20px !important;
        }}
    </style>

    <!-- Original Content -->
    {body_content}

</div>
<!-- End Landing Page Container -->
"""
        
        # Create authentication
        credentials = f"{username}:{app_password}"
        token = base64.b64encode(credentials.encode()).decode()
        headers = {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json'
        }
        
        # Prepare API endpoint
        api_url = f"{wordpress_url.rstrip('/')}/wp-json/wp/v2/pages"
        
        # Prepare payload
        payload = {
            'title': page_title,
            'content': body_content,
            'status': status,
            'template': ''  # Use default template or 'elementor_canvas' for full width
        }
        
        # Send request to WordPress
        response = requests.post(api_url, headers=headers, json=payload)
        
        # Check response
        if response.status_code in [200, 201]:
            data = response.json()
            return {
                'success': True,
                'page_id': data['id'],
                'page_url': data['link'],
                'page_title': data['title']['rendered'],
                'status': data['status'],
                'message': f"Successfully published as {status}",
                'edit_url': f"{wordpress_url.rstrip('/')}/wp-admin/post.php?post={data['id']}&action=edit"
            }
        else:
            return {
                'success': False,
                'error': f"WordPress API Error: {response.status_code}",
                'message': response.text
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': f"Error: {str(e)}"
        }


def post_html_to_wordpress_advanced(
    html_content: str,
    wordpress_url: str,
    username: str,
    app_password: str,
    page_title: Optional[str] = None,
    status: str = 'draft',
    use_elementor: bool = False,
    custom_css_class: str = "landing-page-custom"
) -> dict:
    """
    Advanced WordPress publishing with better style preservation.
    Use this if the simple version has styling issues.
    
    Args:
        html_content: Your complete HTML code
        wordpress_url: WordPress site URL
        username: WordPress username
        app_password: WordPress Application Password
        page_title: Page title
        status: 'draft' or 'publish'
        use_elementor: If True, uses Elementor canvas template (no header/footer)
        custom_css_class: CSS class for the wrapper
    
    Returns:
        dict with publishing results
    """
    
    try:
        # Extract title
        if not page_title:
            title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE)
            page_title = title_match.group(1).strip() if title_match else "Landing Page"
        
        # Extract all styles
        styles = re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.IGNORECASE | re.DOTALL)
        combined_css = "\n".join(styles)
        
        # Extract body content
        body_content = html_content
        if '<body' in html_content.lower():
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.IGNORECASE | re.DOTALL)
            if body_match:
                body_content = body_match.group(1).strip()
        
        # Create WordPress-optimized content
        wp_content = f"""
<!-- Custom Landing Page -->
<div class="{custom_css_class}" style="all: initial; display: block; width: 100%;">
    
    <style type="text/css" scoped>
        /* Scoped styles for landing page */
        .{custom_css_class} {{
            all: initial;
            display: block;
            width: 100%;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        
        .{custom_css_class} * {{
            all: revert;
        }}
        
        /* Original CSS */
        .{custom_css_class} {combined_css.replace('}', '} .{custom_css_class} ')}
        
        /* Force button visibility */
        .{custom_css_class} a,
        .{custom_css_class} button,
        .{custom_css_class} .btn,
        .{custom_css_class} .cta {{
            display: inline-block !important;
            visibility: visible !important;
            opacity: 1 !important;
            text-decoration: none !important;
        }}
    </style>
    
    <div style="all: initial; display: block;">
        {body_content}
    </div>
    
</div>
"""
        
        # Authentication
        credentials = f"{username}:{app_password}"
        token = base64.b64encode(credentials.encode()).decode()
        headers = {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json'
        }
        
        # API endpoint
        api_url = f"{wordpress_url.rstrip('/')}/wp-json/wp/v2/pages"
        
        # Payload
        payload = {
            'title': page_title,
            'content': wp_content,
            'status': status
        }
        
        # Use Elementor template if requested
        if use_elementor:
            payload['template'] = 'elementor_canvas'
        
        # Send request
        response = requests.post(api_url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            data = response.json()
            return {
                'success': True,
                'page_id': data['id'],
                'page_url': data['link'],
                'page_title': data['title']['rendered'],
                'status': data['status'],
                'message': f"Successfully published as {status}",
                'edit_url': f"{wordpress_url.rstrip('/')}/wp-admin/post.php?post={data['id']}&action=edit"
            }
        else:
            return {
                'success': False,
                'error': f"WordPress API Error: {response.status_code}",
                'message': response.text
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': f"Error: {str(e)}"
        }


# ============= USAGE EXAMPLES =============

if __name__ == "__main__":
    
    # Example HTML with button
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Landing Page</title>
        <style>
            body { font-family: Arial; background: #f0f0f0; margin: 0; padding: 0; }
            .container { max-width: 1200px; margin: 0 auto; padding: 40px 20px; }
            h1 { color: #333; font-size: 48px; }
            .cta-button {
                display: inline-block;
                background: #007bff;
                color: white;
                padding: 15px 30px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                margin: 20px 0;
            }
            .cta-button:hover {
                background: #0056b3;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Welcome to My Product!</h1>
            <p>This is an amazing product you should buy.</p>
            <a href="https://affiliate-link.com" class="cta-button">Learn More</a>
        </div>
    </body>
    </html>
    """
    
    # Method 1: Simple (with fix_wordpress_styles=True)
    print("\n" + "="*80)
    print("METHOD 1: Simple Publishing with Style Fixes")
    print("="*80)
    
    result1 = post_html_to_wordpress(
        html_content=html,
        wordpress_url='https://yoursite.com',
        username='your_username',
        app_password='xxxx xxxx xxxx xxxx',
        page_title='Test Landing Page',
        status='draft',
        fix_wordpress_styles=True  # Enable style fixes
    )
    
    if result1['success']:
        print(f"✅ Published: {result1['page_url']}")
        print(f"Edit: {result1['edit_url']}")
    else:
        print(f"❌ Error: {result1['message']}")
    
    
    # Method 2: Advanced (better style isolation)
    print("\n" + "="*80)
    print("METHOD 2: Advanced Publishing (Better Style Preservation)")
    print("="*80)
    
    result2 = post_html_to_wordpress_advanced(
        html_content=html,
        wordpress_url='https://yoursite.com',
        username='your_username',
        app_password='xxxx xxxx xxxx xxxx',
        page_title='Test Landing Page Advanced',
        status='draft',
        use_elementor=True  # Use full-width template (no theme interference)
    )
    
    if result2['success']:
        print(f"✅ Published: {result2['page_url']}")
        print(f"Edit: {result2['edit_url']}")
    else:
        print(f"❌ Error: {result2['message']}")