"""
Flask API – Bulk WordPress Landing Page Generator
Reads Excel/CSV with hero_img column, streams SSE progress, publishes to WordPress via Elementor-compatible HTML
No HTML files are saved locally.
"""

import os
import sys
import json
import traceback

import pandas as pd
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from elementor_landing_builder import create_and_publish_landing_page

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def get_wp_config(overrides: dict = None) -> dict:
    cfg = {
        "wp_url":          os.getenv("WP_SITE_URL"),
        "wp_username":     os.getenv("WP_USERNAME"),
        "wp_app_password": os.getenv("WP_APP_PASSWORD"),
        "wp_status":       os.getenv("WP_STATUS", "publish"),
    }
    if overrides:
        for k, v in overrides.items():
            if v:
                cfg[k] = v
    return cfg


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"xlsx", "xls", "csv"}


def validate_df(df: pd.DataFrame) -> tuple[bool, str]:
    required = ["sales_page_url", "affiliate_link", "wordpress_page_title"]
    missing  = [c for c in required if c not in df.columns]
    if missing:
        return False, f"Missing columns: {', '.join(missing)}"
    return True, "OK"


def safe_str(val) -> str:
    if val is None or (isinstance(val, float) and str(val) == "nan"):
        return ""
    return str(val).strip()


# ─────────────────────────────────────────────
#  ROW PROCESSOR
# ─────────────────────────────────────────────

def process_row(row: pd.Series, wp_config: dict) -> dict:
    try:
        url          = safe_str(row.get("sales_page_url"))
        aff_link     = safe_str(row.get("affiliate_link"))
        page_title   = safe_str(row.get("wordpress_page_title"))
        hero_img     = safe_str(row.get("hero_img") or row.get("Hero_image") or row.get("hero_image"))
        url2         = safe_str(row.get("jv_doc_url"))

        if not url:
            return {"success": False, "error": "Missing sales_page_url"}
        if not aff_link:
            return {"success": False, "error": "Missing affiliate_link"}
        if not page_title:
            return {"success": False, "error": "Missing wordpress_page_title"}

        result = create_and_publish_landing_page(
            url                  = url,
            affiliate_link       = aff_link,
            wordpress_page_title = page_title,
            hero_image_url       = hero_img or None,
            url2                 = url2 or None,
            wp_url               = wp_config.get("wp_url"),
            wp_username          = wp_config.get("wp_username"),
            wp_app_password      = wp_config.get("wp_app_password"),
            wp_status            = wp_config.get("wp_status", "publish"),
        )

        wp = result.get("wordpress", {})
        return {
            "success":      wp.get("success", False),
            "title":        page_title,
            "post_url":     wp.get("page_url"),
            "post_id":      wp.get("post_id"),
            "edit_url":     wp.get("edit_url"),
            "status":       wp.get("status"),
            "pricing":      result.get("pricing", {}),
            "media":        result.get("media", {}),
            "error":        wp.get("error"),
        }

    except Exception as e:
        return {
            "success":   False,
            "error":     str(e),
            "traceback": traceback.format_exc(),
        }


# ─────────────────────────────────────────────
#  STREAMING PROCESSOR
# ─────────────────────────────────────────────

def stream_excel(file_path: str, wp_config: dict):
    try:
        df = pd.read_excel(file_path) if not file_path.endswith(".csv") else pd.read_csv(file_path)
        total = len(df)

        yield json.dumps({
            "type": "started",
            "total_rows": total,
            "columns": list(df.columns),
            "message": f"Processing {total} rows…",
        }) + "\n"

        valid, msg = validate_df(df)
        if not valid:
            yield json.dumps({"type": "error", "message": msg}) + "\n"
            return

        success_count = 0
        error_count   = 0

        for idx, row in df.iterrows():
            row_num = idx + 1
            title   = safe_str(row.get("wordpress_page_title", f"Row {row_num}"))

            yield json.dumps({
                "type":    "progress",
                "row":     row_num,
                "total":   total,
                "title":   title,
                "message": f"⏳ Processing ({row_num}/{total}): {title}",
            }) + "\n"

            result = process_row(row, wp_config)

            if result.get("success"):
                success_count += 1
                yield json.dumps({
                    "type":     "row_success",
                    "row":      row_num,
                    "total":    total,
                    "data":     result,
                    "message":  f"✅ ({row_num}/{total}) {title} → {result.get('post_url')}",
                }) + "\n"
            else:
                error_count += 1
                yield json.dumps({
                    "type":    "row_error",
                    "row":     row_num,
                    "total":   total,
                    "data":    result,
                    "message": f"❌ ({row_num}/{total}) {title} – {result.get('error')}",
                }) + "\n"

        yield json.dumps({
            "type":          "complete",
            "total_rows":    total,
            "success_count": success_count,
            "error_count":   error_count,
            "message":       f"🎉 Done! {success_count} published, {error_count} failed.",
        }) + "\n"

    except Exception as e:
        yield json.dumps({
            "type":      "fatal_error",
            "message":   str(e),
            "traceback": traceback.format_exc(),
        }) + "\n"


# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "name": "WordPress Bulk Landing Page Generator (Elementor Edition)",
        "version": "2.0.0",
        "changes": [
            "No local HTML files saved",
            "Elementor-compatible HTML published directly to WordPress",
            "Price Scraper Agent extracts real prices from sales pages",
            "hero_img column supported in Excel/CSV",
        ],
        "excel_columns": {
            "sales_page_url":       "REQUIRED – URL to scrape",
            "affiliate_link":       "REQUIRED – Your affiliate link",
            "wordpress_page_title": "REQUIRED – Post title",
            "hero_img":             "OPTIONAL – Custom hero image URL",
            "jv_doc_url":           "OPTIONAL – Second URL for comparison",
        },
        "endpoints": {
            "POST /api/upload":         "Upload Excel/CSV → streaming SSE",
            "POST /api/process-single": "Process one row as JSON",
            "GET  /api/health":         "Health check",
        },
    })


@app.route("/api/health", methods=["GET"])
def health():
    cfg = get_wp_config()
    return jsonify({
        "status": "healthy",
        "wordpress_configured": all([cfg.get("wp_url"), cfg.get("wp_username"), cfg.get("wp_app_password")]),
        "wordpress_url": cfg.get("wp_url"),
        "default_status": cfg.get("wp_status"),
    })


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"error": "Invalid file – use .xlsx, .xls, or .csv"}), 400

    path = os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(f.filename))
    f.save(path)

    wp_config = get_wp_config({
        "wp_url":          request.form.get("wordpress_url"),
        "wp_username":     request.form.get("wordpress_username"),
        "wp_app_password": request.form.get("wordpress_app_password"),
        "wp_status":       request.form.get("wordpress_status"),
    })

    return Response(
        stream_with_context(stream_excel(path, wp_config)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/process-single", methods=["POST"])
def process_single():
    data = request.get_json() or {}
    required = ["sales_page_url", "affiliate_link", "wordpress_page_title"]
    missing  = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    wp_config = get_wp_config({
        "wp_url":          data.get("wordpress_url"),
        "wp_username":     data.get("wordpress_username"),
        "wp_app_password": data.get("wordpress_app_password"),
        "wp_status":       data.get("wordpress_status"),
    })

    row = pd.Series(data)
    result = process_row(row, wp_config)

    if result.get("success"):
        return jsonify({"success": True, **result}), 200
    else:
        return jsonify({"success": False, **result}), 500


# ─────────────────────────────────────────────
#  ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large (max 16 MB)"}), 413

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    cfg = get_wp_config()
    print("=" * 70)
    print("  WordPress Bulk Landing Page Generator v2 (Elementor Edition)")
    print("=" * 70)
    print(f"  WP URL:    {cfg.get('wp_url', 'NOT SET')}")
    print(f"  WP User:   {cfg.get('wp_username', 'NOT SET')}")
    print(f"  WP Pass:   {'SET ✅' if cfg.get('wp_app_password') else 'NOT SET ❌'}")
    print(f"  Status:    {cfg.get('wp_status')}")
    print("=" * 70)
    print("  Endpoints:")
    print("    GET  http://localhost:5000/")
    print("    GET  http://localhost:5000/api/health")
    print("    POST http://localhost:5000/api/upload          (Excel/CSV streaming)")
    print("    POST http://localhost:5000/api/process-single  (JSON single)")
    print("=" * 70)
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
