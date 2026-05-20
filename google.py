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

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
GOOGLE_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
CARD_IMAGE_SEARCH_REQUIRED_TERMS = "(MTG OR マジック OR ギャザ) (カード OR card)"
GOOGLE_DAILY_SEARCH_LIMIT = 99
GOOGLE_USAGE_FILE = os.path.join(
  os.path.dirname(os.path.abspath(__file__)),
  ".google_search_usage.json",
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
  if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY is not set")
  if not GOOGLE_SEARCH_ENGINE_ID:
    raise ValueError("GOOGLE_SEARCH_ENGINE_ID is not set")

  reserve_google_search_quota()

  response = requests.get(
    GOOGLE_CUSTOM_SEARCH_URL,
    params={
      "key": GOOGLE_API_KEY,
      "cx": GOOGLE_SEARCH_ENGINE_ID,
      "q": query,
      "searchType": "image",
      "num": num,
      "hl": "ja",
      "lr": "lang_ja",
      "gl": "jp",
      "safe": "active",
      "imgType": "photo",
    },
    headers=REQUEST_HEADERS,
    timeout=10,
  )
  response.raise_for_status()

  data = response.json()
  image_urls = [
    item["link"]
    for item in data.get("items", [])
    if item.get("link", "").startswith(("http://", "https://"))
  ]

  if not image_urls:
    raise RuntimeError("No image URL found in Google image search result")

  return list(dict.fromkeys(image_urls))

def reserve_google_search_quota():
  usage = load_google_search_usage()
  today = date.today().isoformat()
  count = usage["count"] if usage["date"] == today else 0

  if count >= GOOGLE_DAILY_SEARCH_LIMIT:
    raise RuntimeError(
      f"Google image search daily limit reached: {count}/{GOOGLE_DAILY_SEARCH_LIMIT}"
    )

  save_google_search_usage({
    "date": today,
    "count": count + 1,
  })

def load_google_search_usage():
  try:
    with open(GOOGLE_USAGE_FILE, "r", encoding="utf-8") as usage_file:
      usage = json.load(usage_file)
  except FileNotFoundError:
    return {"date": date.today().isoformat(), "count": 0}
  except (json.JSONDecodeError, OSError):
    return {"date": date.today().isoformat(), "count": 0}

  if not isinstance(usage, dict):
    return {"date": date.today().isoformat(), "count": 0}

  return {
    "date": str(usage.get("date", date.today().isoformat())),
    "count": int(usage.get("count", 0)),
  }

def save_google_search_usage(usage):
  temp_file = f"{GOOGLE_USAGE_FILE}.tmp"
  with open(temp_file, "w", encoding="utf-8") as usage_file:
    json.dump(usage, usage_file)
  os.replace(temp_file, GOOGLE_USAGE_FILE)

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
