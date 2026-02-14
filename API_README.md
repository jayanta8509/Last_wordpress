# WordPress Bulk Landing Page Generator API

A Flask-based API that processes Excel files to create multiple WordPress landing pages automatically. Uses Server-Sent Events (SSE) for real-time streaming updates as each page is created.

## Features

- Upload Excel file (.xlsx, .xls, .csv) with bulk data
- Process rows step-by-step
- Real-time streaming updates via SSE
- Get post URLs immediately after each page is created
- WordPress credentials from `.env` or request parameters
- Built-in web client for testing

## Installation

```bash
pip install flask pandas openpyxl requests beautifulsoup4 python-dotenv openai
```

## Configuration (.env)

```env
OPENAI_API_KEY=sk-your-key-here
WP_SITE_URL=https://yoursite.com
WP_USERNAME=your_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx
WP_STATUS=draft
```

## Excel File Format

| Column | Required | Description |
|--------|----------|-------------|
| `sales_page_url` | Yes | URL to scrape for content |
| `jv_doc_url` | No | Second URL for comparison |
| `affiliate_link` | Yes | Affiliate link for all CTAs |
| `wordpress_page_title` | Yes | Title for the WordPress page |

Generate a template:
```bash
python excel_template.py
```

## API Endpoints

### 1. POST /api/upload - Bulk Process (Streaming)

Upload Excel file and get real-time updates via Server-Sent Events.

**Request:**
```bash
curl -X POST http://localhost:5000/api/upload \
  -F "file=@bulk_upload.xlsx" \
  -F "output_dir=output" \
  -F "wordpress_status=draft"
```

**Response (SSE Stream):**
```
data: {"type":"progress","stage":"started","total_rows":3,"message":"Starting to process 3 rows..."}

data: {"type":"success","row":1,"total":3,"data":{"post_url":"https://...","post_id":123},"message":"✅ Created: KetoFlow Review"}

data: {"type":"complete","total_rows":3,"success_count":3,"error_count":0}
```

### 2. POST /api/process-single - Single Page

Create a single landing page.

**Request:**
```json
POST http://localhost:5000/api/process-single
Content-Type: application/json

{
  "sales_page_url": "https://example.com",
  "affiliate_link": "https://affiliate-link.com",
  "wordpress_page_title": "My Landing Page",
  "wordpress_status": "publish"
}
```

**Response:**
```json
{
  "success": true,
  "post_url": "https://yoursite.com/my-landing-page",
  "post_id": 123,
  "edit_url": "https://yoursite.com/wp-admin/post.php?post=123&action=edit"
}
```

### 3. GET /api/health - Health Check

Check if API is running and WordPress is configured.

**Response:**
```json
{
  "status": "healthy",
  "wordpress_configured": true,
  "wordpress_url": "https://yoursite.com"
}
```

## Running the Server

```bash
python app.py
```

Server starts at `http://localhost:5000`

## Using the Web Client

1. Open `api_client.html` in your browser
2. Or navigate to `http://localhost:5000` and open the client
3. Upload your Excel file
4. Click "Start Processing"
5. Watch real-time progress and results

## JavaScript SSE Client Example

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const response = await fetch('http://localhost:5000/api/upload', {
  method: 'POST',
  body: formData
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const chunk = decoder.decode(value);
  const lines = chunk.split('\n');

  for (const line of lines) {
    if (!line.trim()) continue;
    const data = JSON.parse(line);

    if (data.type === 'success') {
      console.log('Post created:', data.post_url);
      // Store the post URL immediately
    }
  }
}
```

## Response Types

| Type | Description |
|------|-------------|
| `progress` | Processing status update |
| `success` | A post was successfully created (includes post_url) |
| `error` | A row failed to process |
| `complete` | All rows processed |

## Output Files

Each landing page generates:
- `output/{page_title}/affiliate_landing_page.html` - The landing page HTML
- `output/{page_title}/media_urls.json` - Extracted media URLs
- `output/{page_title}/seo_content.txt` - Generated SEO content
- `output/{page_title}/metadata.json` - Processing metadata

## Error Handling

- Missing required columns → Returns error immediately
- Invalid URL → Skips row, returns error for that row
- WordPress publish failure → Returns error with details
- Network timeout → Returns error with traceback

## Security Notes

- App passwords are transmitted over HTTPS in production
- File size limited to 16MB
- All uploaded files are sanitized with `secure_filename()`
