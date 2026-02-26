"""
Flask API for Bulk WordPress Landing Page Generation from Excel
Processes rows step-by-step and returns post URLs as they complete
"""

import os
import sys
import json
import pandas as pd
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename
from typing import Generator, Dict, Any
import traceback

# Import the landing page generator functions
from Landing_page_builder_with_wordpress import create_affiliate_landing_page
from dotenv import load_dotenv

# Fix UTF-8 encoding for Windows console (only if running in terminal)
if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

load_dotenv()

app = Flask(__name__)
# Enable CORS for all routes
CORS(app, supports_credentials=True)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ===================== CONFIGURATION =====================

def get_wordpress_config():
    """Get WordPress configuration from environment or request"""
    return {
        'wordpress_url': os.getenv('WP_SITE_URL'),
        'wordpress_username': os.getenv('WP_USERNAME'),
        'wordpress_app_password': os.getenv('WP_APP_PASSWORD'),
        'wordpress_status': os.getenv('WP_STATUS', 'publish')
    }


# ===================== HELPER FUNCTIONS =====================

def allowed_file(filename: str, allowed_extensions: set = None) -> bool:
    """Check if file has allowed extension"""
    if allowed_extensions is None:
        allowed_extensions = {'xlsx', 'xls', 'csv'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def validate_excel_columns(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Validate that required columns exist in the Excel file

    Required columns:
    - sales_page_url
    - jv_doc_url (optional, used as url2)
    - affiliate_link
    - wordpress_page_title
    """
    required_columns = ['sales_page_url', 'affiliate_link', 'wordpress_page_title']
    optional_columns = ['jv_doc_url']

    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        return False, f"Missing required columns: {', '.join(missing_columns)}"

    return True, "Validation successful"


def process_single_row(row: pd.Series, wp_config: dict, output_dir: str) -> dict:
    """
    Process a single row and create a WordPress post

    Args:
        row: Pandas Series containing the row data
        wp_config: WordPress configuration dict
        output_dir: Directory to save output files

    Returns:
        dict with processing results
    """
    try:
        # Extract data from row
        sales_page_url = str(row['sales_page_url']).strip()
        affiliate_link = str(row['affiliate_link']).strip()
        wordpress_page_title = str(row['wordpress_page_title']).strip()

        # Optional jv_doc_url (used as url2 for comparison)
        url2 = None
        if 'jv_doc_url' in row and pd.notna(row['jv_doc_url']):
            url2 = str(row['jv_doc_url']).strip()

        # Validate required fields
        if not sales_page_url or sales_page_url == 'nan':
            return {
                'success': False,
                'error': 'Invalid or missing sales_page_url',
                'row_data': row.to_dict()
            }

        if not affiliate_link or affiliate_link == 'nan':
            return {
                'success': False,
                'error': 'Invalid or missing affiliate_link',
                'row_data': row.to_dict()
            }

        if not wordpress_page_title or wordpress_page_title == 'nan':
            return {
                'success': False,
                'error': 'Invalid or missing wordpress_page_title',
                'row_data': row.to_dict()
            }

        # Create output directory for this specific page
        page_output_dir = os.path.join(output_dir, secure_filename(wordpress_page_title))

        # Generate landing page and publish to WordPress
        result = create_affiliate_landing_page(
            url=sales_page_url,
            affiliate_link=affiliate_link,
            url2=url2,
            output_dir=page_output_dir,
            publish_to_wordpress=True,
            wordpress_url=wp_config.get('wordpress_url'),
            wordpress_username=wp_config.get('wordpress_username'),
            wordpress_app_password=wp_config.get('wordpress_app_password'),
            wordpress_page_title=wordpress_page_title,
            wordpress_status=wp_config.get('wordpress_status', 'publish')
        )

        # Extract WordPress result
        wp_result = result.get('wordpress', {})

        if wp_result.get('success'):
            return {
                'success': True,
                'wordpress_page_title': wordpress_page_title,
                'post_url': wp_result.get('page_url'),
                'post_id': wp_result.get('page_id'),
                'edit_url': wp_result.get('edit_url'),
                'status': wp_result.get('status'),
                'sales_page_url': sales_page_url,
                'affiliate_link': affiliate_link,
                'files_generated': result.get('files', []),
                'images_found': result.get('media', {}).get('total_images', 0),
                'videos_found': result.get('media', {}).get('total_videos', 0)
            }
        else:
            return {
                'success': False,
                'error': wp_result.get('error', 'Unknown WordPress error'),
                'wordpress_page_title': wordpress_page_title,
                'sales_page_url': sales_page_url
            }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'row_data': row.to_dict() if hasattr(row, 'to_dict') else str(row)
        }


# ===================== STREAMING PROCESSOR =====================

def process_excel_streaming(file_path: str, wp_config: dict, output_base_dir: str = 'output') -> Generator[str, None, None]:
    """
    Process Excel file and yield SSE (Server-Sent Events) updates as each row completes

    Yields JSON strings with progress updates
    """
    try:
        # Read Excel file
        df = pd.read_excel(file_path)

        total_rows = len(df)
        yield json.dumps({
            'type': 'progress',
            'stage': 'started',
            'total_rows': total_rows,
            'message': f'Starting to process {total_rows} rows...'
        }) + '\n'

        # Validate columns
        is_valid, message = validate_excel_columns(df)
        if not is_valid:
            yield json.dumps({
                'type': 'error',
                'message': message
            }) + '\n'
            return

        # Process each row
        success_count = 0
        error_count = 0

        for index, row in df.iterrows():
            row_number = index + 1

            yield json.dumps({
                'type': 'progress',
                'stage': 'processing',
                'row': row_number,
                'total': total_rows,
                'message': f'Processing row {row_number}/{total_rows}: {row.get("wordpress_page_title", "Unknown")}'
            }) + '\n'

            # Process the row
            result = process_single_row(row, wp_config, output_base_dir)

            if result.get('success'):
                success_count += 1
                yield json.dumps({
                    'type': 'success',
                    'row': row_number,
                    'total': total_rows,
                    'data': result,
                    'message': f'✅ Created: {result.get("wordpress_page_title")} - {result.get("post_url")}'
                }) + '\n'
            else:
                error_count += 1
                yield json.dumps({
                    'type': 'error',
                    'row': row_number,
                    'total': total_rows,
                    'data': result,
                    'message': f'❌ Failed row {row_number}: {result.get("error")}'
                }) + '\n'

        # Final summary
        yield json.dumps({
            'type': 'complete',
            'total_rows': total_rows,
            'success_count': success_count,
            'error_count': error_count,
            'message': f'Processing complete! {success_count} succeeded, {error_count} failed.'
        }) + '\n'

    except Exception as e:
        yield json.dumps({
            'type': 'error',
            'message': f'Fatal error: {str(e)}',
            'traceback': traceback.format_exc()
        }) + '\n'


# ===================== API ROUTES =====================

@app.route('/', methods=['GET'])
def home():
    """API Home / Documentation"""
    return jsonify({
        'name': 'WordPress Bulk Landing Page Generator API',
        'version': '1.0.0',
        'endpoints': {
            'POST /api/upload': {
                'description': 'Upload Excel file and process rows step-by-step',
                'content_type': 'multipart/form-data',
                'parameters': {
                    'file': 'Excel file (.xlsx, .xls, .csv) - REQUIRED',
                    'output_dir': 'Output directory name (default: output)',
                    'wordpress_url': 'WordPress site URL (overrides .env)',
                    'wordpress_username': 'WordPress username (overrides .env)',
                    'wordpress_app_password': 'WordPress app password (overrides .env)',
                    'wordpress_status': 'Post status: draft or publish (default: draft)'
                },
                'excel_columns': {
                    'sales_page_url': 'REQUIRED - URL to scrape for content',
                    'jv_doc_url': 'OPTIONAL - Second URL for comparison',
                    'affiliate_link': 'REQUIRED - Affiliate link for CTAs',
                    'wordpress_page_title': 'REQUIRED - Title for the WordPress page'
                }
            },
            'GET /api/health': 'Health check endpoint'
        },
        'response_types': {
            'streaming': 'Server-Sent Events (SSE) - Get real-time updates as each post is created',
            'json': 'Final summary with all post URLs'
        }
    })


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    wp_config = get_wordpress_config()

    return jsonify({
        'status': 'healthy',
        'wordpress_configured': bool(
            wp_config.get('wordpress_url') and
            wp_config.get('wordpress_username') and
            wp_config.get('wordpress_app_password')
        ),
        'wordpress_url': wp_config.get('wordpress_url')
    })


@app.route('/api/upload', methods=['POST'])
def upload_and_process():
    """
    Upload Excel file and process rows with streaming response

    Returns Server-Sent Events (SSE) stream with real-time updates
    """
    # Check if file is in request
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({
            'error': 'Invalid file type. Allowed: .xlsx, .xls, .csv'
        }), 400

    # Save uploaded file
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Get WordPress config (from request or .env)
    wp_config = get_wordpress_config()

    # Override with request parameters if provided
    if request.form.get('wordpress_url'):
        wp_config['wordpress_url'] = request.form.get('wordpress_url')
    if request.form.get('wordpress_username'):
        wp_config['wordpress_username'] = request.form.get('wordpress_username')
    if request.form.get('wordpress_app_password'):
        wp_config['wordpress_app_password'] = request.form.get('wordpress_app_password')
    if request.form.get('wordpress_status'):
        wp_config['wordpress_status'] = request.form.get('wordpress_status')

    # Get output directory
    output_dir = request.form.get('output_dir', 'output')

    # Return streaming response
    return Response(
        stream_with_context(
            process_excel_streaming(file_path, wp_config, output_dir)
        ),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/process-single', methods=['POST'])
def process_single():
    """
    Process a single landing page creation request

    Expected JSON body:
    {
        "sales_page_url": "https://example.com",
        "jv_doc_url": "https://example2.com", (optional)
        "affiliate_link": "https://affiliate-link.com",
        "wordpress_page_title": "My Landing Page",
        "wordpress_status": "draft" (optional, default: draft)
    }
    """
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['sales_page_url', 'affiliate_link', 'wordpress_page_title']
        missing_fields = [f for f in required_fields if not data.get(f)]

        if missing_fields:
            return jsonify({
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400

        # Get WordPress config
        wp_config = get_wordpress_config()

        # Override with request data
        for key in ['wordpress_url', 'wordpress_username', 'wordpress_app_password', 'wordpress_status']:
            if data.get(key):
                wp_config[key] = data[key]

        # Validate WordPress config
        if not all([wp_config.get('wordpress_url'), wp_config.get('wordpress_username'), wp_config.get('wordpress_app_password')]):
            return jsonify({
                'error': 'WordPress credentials not configured. Set them in .env or provide in request.',
                'required_fields': ['wordpress_url', 'wordpress_username', 'wordpress_app_password']
            }), 400

        # Create output directory
        output_dir = os.path.join('output', secure_filename(data['wordpress_page_title']))

        # Process the landing page
        result = create_affiliate_landing_page(
            url=data['sales_page_url'],
            affiliate_link=data['affiliate_link'],
            url2=data.get('jv_doc_url'),
            output_dir=output_dir,
            publish_to_wordpress=True,
            wordpress_url=wp_config.get('wordpress_url'),
            wordpress_username=wp_config.get('wordpress_username'),
            wordpress_app_password=wp_config.get('wordpress_app_password'),
            wordpress_page_title=data['wordpress_page_title'],
            wordpress_status=wp_config.get('wordpress_status', 'publish')
        )

        wp_result = result.get('wordpress', {})

        if wp_result.get('success'):
            return jsonify({
                'success': True,
                'message': 'Landing page created and published successfully',
                'post_url': wp_result.get('page_url'),
                'post_id': wp_result.get('page_id'),
                'edit_url': wp_result.get('edit_url'),
                'status': wp_result.get('status'),
                'files_generated': result.get('files', []),
                'media': {
                    'images': result.get('media', {}).get('total_images', 0),
                    'videos': result.get('media', {}).get('total_videos', 0)
                }
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': wp_result.get('error', 'Failed to publish to WordPress'),
                'details': wp_result
            }), 500

    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


# ===================== ERROR HANDLERS =====================

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413


@app.errorhandler(500)
def internal_server_error(error):
    return jsonify({'error': 'Internal server error', 'details': str(error)}), 500


# ===================== MAIN =====================

if __name__ == '__main__':
    print("="*80)
    print("WordPress Bulk Landing Page Generator API")
    print("="*80)
    print(f"Upload Folder: {app.config['UPLOAD_FOLDER']}")
    print(f"Max File Size: {app.config['MAX_CONTENT_LENGTH'] / (1024*1024)}MB")

    wp_config = get_wordpress_config()
    print(f"\nWordPress Configuration:")
    print(f"  URL: {wp_config.get('wordpress_url', 'NOT SET')}")
    print(f"  Username: {wp_config.get('wordpress_username', 'NOT SET')}")
    print(f"  Password: {'SET' if wp_config.get('wordpress_app_password') else 'NOT SET'}")
    print(f"  Default Status: {wp_config.get('wordpress_status', 'draft')}")

    print("\n" + "="*80)
    print("API Endpoints:")
    print("  GET  http://localhost:5000/           - API Documentation")
    print("  GET  http://localhost:5000/api/health - Health Check")
    print("  POST http://localhost:5000/api/upload       - Upload Excel (Streaming SSE)")
    print("  POST http://localhost:5000/api/process-single - Process Single Page")
    print("="*80)
    print("\nStarting Flask server...")

    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
