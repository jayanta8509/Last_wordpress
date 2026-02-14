"""
Excel Template Generator for Bulk WordPress Landing Page API
Creates a sample Excel file with the correct format
"""

import pandas as pd
import sys

# Fix UTF-8 encoding for Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Sample data for the Excel file
sample_data = {
    'sales_page_url': [
        'https://www.ketoflow.app/d',
        'https://www.example.com/product2',
        'https://www.example.com/product3'
    ],
    'jv_doc_url': [
        'https://example.com/jv1',  # Optional - for comparison
        None,  # Can be empty
        'https://example.com/jv3'
    ],
    'affiliate_link': [
        'https://warriorplus.com/o2/link1',
        'https://example.com/affiliate2',
        'https://example.com/affiliate3'
    ],
    'wordpress_page_title': [
        'KetoFlow Review - Weight Loss',
        'Product Two Review',
        'Product Three Review'
    ]
}

# Create DataFrame
df = pd.DataFrame(sample_data)

# Save to Excel
output_file = 'bulk_upload_template.xlsx'
df.to_excel(output_file, index=False)

print(f"Excel template created: {output_file}")
print(f"\nExpected columns:")
print(f"  - sales_page_url       (REQUIRED) URL to scrape for content")
print(f"  - jv_doc_url           (OPTIONAL) Second URL for comparison")
print(f"  - affiliate_link       (REQUIRED) Affiliate link for CTAs")
print(f"  - wordpress_page_title (REQUIRED) Title for the WordPress page")
print(f"\nSample data preview:")
print(df.to_string())
