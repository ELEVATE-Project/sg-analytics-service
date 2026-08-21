import os
import json
import logging
from typing import Dict, Any

import requests
from google.cloud import storage
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables from .env
load_dotenv()

GCP_BUCKET_NAME = os.getenv("GCP_BUCKET_NAME", "dev-sg-dashboard")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_TOKEN = os.getenv("API_TOKEN", "")

GCS_FOLDER = "backend"  # All operations scoped to this folder only


def fetch_data(endpoint: str) -> Dict[str, Any]:
    url = f"{API_BASE_URL}{endpoint}"
    headers = {"X-Triggered-By": "cron"}
    if API_TOKEN:
        headers["X-Auth-Token"] = API_TOKEN  # ⚠️ Verify this matches your API's expected header

    logging.info(f"Fetching data from {url}")
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def ensure_folder_exists(bucket: storage.Bucket, folder: str):
    """
    GCS doesn't have real folders, but we can check/create a placeholder object
    (a zero-byte blob with a trailing slash) to represent the folder.
    """
    folder_blob_name = f"{folder}/"
    folder_blob = bucket.blob(folder_blob_name)

    if not folder_blob.exists():
        logging.info(f"Folder gs://{bucket.name}/{folder_blob_name} not found. Creating it.")
        folder_blob.upload_from_string("", content_type="application/x-www-form-urlencoded")
        logging.info(f"Folder placeholder created: gs://{bucket.name}/{folder_blob_name}")
    else:
        logging.info(f"Folder gs://{bucket.name}/{folder_blob_name} already exists.")


def delete_if_exists(bucket: storage.Bucket, blob_name: str):
    """Check if a blob exists and delete it before re-uploading."""
    blob = bucket.blob(blob_name)
    if blob.exists():
        logging.info(f"Existing file found at gs://{bucket.name}/{blob_name}. Deleting...")
        blob.delete()
        logging.info(f"Deleted gs://{bucket.name}/{blob_name}")
    else:
        logging.info(f"No existing file at gs://{bucket.name}/{blob_name}. Skipping delete.")


def upload_to_gcs(bucket_name: str, destination_blob_name: str, data: Dict[str, Any]):
    logging.info(f"Uploading data to gs://{bucket_name}/{destination_blob_name}")
    try:
        # Client automatically uses GOOGLE_APPLICATION_CREDENTIALS from env
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        # Step 1: Ensure the backend/ folder exists
        ensure_folder_exists(bucket, GCS_FOLDER)

        # Step 2: Delete existing file if present
        delete_if_exists(bucket, destination_blob_name)

        # Step 3: Upload fresh data
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(
            data=json.dumps(data, indent=2),
            content_type="application/json"
        )
        logging.info(f"Successfully uploaded to gs://{bucket_name}/{destination_blob_name}")

    except Exception as e:
        logging.error(f"Failed to upload to GCS: {e}")
        raise


def main():
    endpoints = {
        "animations.json": "/api/v1/voices/animations",
        "metrics.json": "/api/v1/voices/big-numbers"
    }

    for filename, endpoint in endpoints.items():
        destination = f"{GCS_FOLDER}/{filename}"  # Always scoped under backend/
        try:
            data = fetch_data(endpoint)
            upload_to_gcs(GCP_BUCKET_NAME, destination, data)
        except Exception as e:
            logging.error(f"Error processing {filename}: {e}")


if __name__ == "__main__":
    main()