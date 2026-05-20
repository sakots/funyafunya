from io import BytesIO
from datetime import date
import json
import mimetypes
import os
from urllib.parse import urlparse

import requests
from PIL import Image

from dotenv import load_dotenv
load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
CARD_IMAGE_SEARCH_REQUIRED_TERMS = "(MTG OR マジック OR ギャザ) (カード OR card)"
SERPAPI_MONTHLY_SEARCH_LIMIT = int(os.getenv("SERPAPI_MONTHLY_SEARCH_LIMIT", "250"))
SERPAPI_USAGE_FILE = os.path.join(
  os.path.dirname(os.path.abspath(__file__)),
  ".serpapi_search_usage.json",
)
REQUEST_HEADERS = {
  "User-Agent": "Mozilla/5.0 (compatible; funyafunya-bot/0.1)"
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CARD_ASPECT_RATIO = 63 / 88
CARD_ASPECT_TOLERANCE = 0.08

def build_card_image_search_query(query):
  query = query.strip()
  if not query:
    return CARD_IMAGE_SEARCH_REQUIRED_TERMS
  return f"{query} {CARD_IMAGE_SEARCH_REQUIRED_TERMS}"

def search_google_images(query, num=10):
  if not SERPAPI_API_KEY:
    raise ValueError("SERPAPI_API_KEY is not set")

  ensure_serpapi_search_quota()

  response = requests.get(
    SERPAPI_SEARCH_URL,
    params={
      "api_key": SERPAPI_API_KEY,
      "engine": "google_images",
      "q": query,
      "ijn": "0",
      "hl": "ja",
      "gl": "jp",
      "google_domain": "google.co.jp",
      "safe": "active",
      "device": "desktop",
    },
    headers=REQUEST_HEADERS,
    timeout=10,
  )
  data = response.json()
  raise_for_serpapi_error(response, data)
  increment_serpapi_search_usage()

  image_urls = extract_serpapi_image_urls(data)

  if not image_urls:
    raise RuntimeError("No image URL found in SerpAPI Google Images result")

  return list(dict.fromkeys(image_urls))[:num]

def extract_serpapi_image_urls(data):
  image_urls = []
  for item in data.get("images_results", []):
    for key in ("original", "thumbnail"):
      image_url = item.get(key)
      if image_url and image_url.startswith(("http://", "https://")):
        image_urls.append(image_url)

  return image_urls

def ensure_serpapi_search_quota():
  usage = load_serpapi_search_usage()
  current_month = usage_month()
  count = usage["count"] if usage["month"] == current_month else 0

  if count >= SERPAPI_MONTHLY_SEARCH_LIMIT:
    raise RuntimeError(
      f"SerpAPI image search monthly limit reached: {count}/{SERPAPI_MONTHLY_SEARCH_LIMIT}"
    )

def increment_serpapi_search_usage():
  usage = load_serpapi_search_usage()
  current_month = usage_month()
  count = usage["count"] if usage["month"] == current_month else 0

  save_serpapi_search_usage({
    "month": current_month,
    "count": count + 1,
  })

def raise_for_serpapi_error(response, data):
  if response.ok and not data.get("error"):
    return

  message = data.get("error") or response.text
  raise RuntimeError(
    f"SerpAPI Google Images error: {response.status_code}: {message}"
  )

def load_serpapi_search_usage():
  try:
    with open(SERPAPI_USAGE_FILE, "r", encoding="utf-8") as usage_file:
      usage = json.load(usage_file)
  except FileNotFoundError:
    return {"month": usage_month(), "count": 0}
  except (json.JSONDecodeError, OSError):
    return {"month": usage_month(), "count": 0}

  if not isinstance(usage, dict):
    return {"month": usage_month(), "count": 0}

  return {
    "month": usage.get("month") or str(usage.get("date", usage_month()))[:7],
    "count": int(usage.get("count", 0)),
  }

def usage_month():
  return date.today().strftime("%Y-%m")

def save_serpapi_search_usage(usage):
  temp_file = f"{SERPAPI_USAGE_FILE}.tmp"
  with open(temp_file, "w", encoding="utf-8") as usage_file:
    json.dump(usage, usage_file)
  os.replace(temp_file, SERPAPI_USAGE_FILE)

def download_first_image(query):
  errors = []
  for image_url in search_google_images(query):
    try:
      return download_image(image_url)
    except Exception as error:
      errors.append(f"{image_url}: {error}")

  raise RuntimeError("Could not download any image: " + " / ".join(errors[:3]))

def download_image(image_url):
  response = requests.get(
    image_url,
    headers=REQUEST_HEADERS,
    stream=True,
    timeout=15,
  )
  response.raise_for_status()

  content_type = response.headers.get("content-type", "").split(";")[0]
  if not content_type.startswith("image/"):
    raise RuntimeError(f"Downloaded URL is not an image: {content_type}")

  data = BytesIO()
  for chunk in response.iter_content(chunk_size=8192):
    data.write(chunk)
    if data.tell() > MAX_IMAGE_BYTES:
      raise RuntimeError("Downloaded image is too large")

  data.seek(0)
  ensure_card_aspect_ratio(data)
  data.seek(0)
  data.name = image_filename(image_url, content_type)
  return data

def ensure_card_aspect_ratio(image_file):
  with Image.open(image_file) as image:
    width, height = image.size

  aspect_ratio = width / height
  difference = abs(aspect_ratio - CARD_ASPECT_RATIO) / CARD_ASPECT_RATIO
  if difference > CARD_ASPECT_TOLERANCE:
    raise RuntimeError(
      f"Image aspect ratio is not card-like: {width}x{height} ({aspect_ratio:.3f})"
    )

def image_filename(image_url, content_type):
  path = urlparse(image_url).path
  name = os.path.basename(path)
  if not name or "." not in name:
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    name = f"google-image{extension}"
  return name

if __name__ == "__main__":
  query = build_card_image_search_query("Black Lotus")
  for image_url in search_google_images(query):
    print(image_url)
