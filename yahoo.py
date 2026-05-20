import asyncio
import html
from io import BytesIO
import json
import mimetypes
import os
import re
from urllib.parse import unquote, urlparse, urlunparse

import requests
import websockets
from misskey import Misskey
from PIL import Image

from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("TOKEN")
MISSKEY_HOST = os.getenv("MISSKEY_HOST")
MISSKEY_PORT = os.getenv("MISSKEY_PORT")

def build_misskey_url(host, port=None):
  if not host:
    raise ValueError("MISSKEY_HOST is not set")

  if "://" not in host:
    scheme = "http" if host in ("localhost", "127.0.0.1", "::1") or port else "https"
    host = f"{scheme}://{host}"

  parsed = urlparse(host)
  netloc = parsed.netloc
  if port and ":" not in netloc:
    netloc = f"{netloc}:{port}"

  return urlunparse((parsed.scheme, netloc, parsed.path.rstrip("/"), "", "", ""))

def build_streaming_url(base_url, token):
  parsed = urlparse(base_url)
  scheme = "wss" if parsed.scheme == "https" else "ws"
  path = f"{parsed.path}/streaming" if parsed.path else "/streaming"
  return urlunparse((scheme, parsed.netloc, path, "", f"i={token}", ""))

YAHOO_IMAGE_SEARCH_URL = "https://search.yahoo.co.jp/image/search"
CARD_IMAGE_SEARCH_REQUIRED_TERMS = "(MTG OR マジック OR ギャザ) (カード OR card)"
REQUEST_HEADERS = {
  "User-Agent": (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
  ),
  "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CARD_ASPECT_RATIO = 63 / 88
CARD_ASPECT_TOLERANCE = 0.08

msk = None
MY_ID = None

async def runner():
  misskey_url = build_misskey_url(MISSKEY_HOST, MISSKEY_PORT)
  ws_url = build_streaming_url(misskey_url, TOKEN)
  setup_misskey(misskey_url)

  async with websockets.connect(ws_url) as ws:
    await ws.send(json.dumps({
      "type": "connect",
      "body": {
        "channel": "hybridTimeline", # すべてのイベントを受け取るチャンネル
        "id": "funyafunya-yahoo"
      }
    }))
    while True:
      data = json.loads(await ws.recv())
      print(data)
      if data['type'] == 'channel':
        if data['body']['type'] == 'note':
          note = data['body']['body']
          await on_note(note)
        elif data['body']['type'] == 'followed':
          user = data['body']['body']
          await on_follow(user)
      elif data['type'] == 'followed':
        user = data['body']
        await on_follow(user)

def setup_misskey(misskey_url):
  global msk, MY_ID
  msk = Misskey(misskey_url, i=TOKEN)
  MY_ID = msk.i()['id']

# メンションされたときの処理（メイン）
async def on_note(note):
  if note.get('mentions'):
    if MY_ID in note['mentions']:
      user = note['user']
      mention = user_mention(user)
      query = extract_search_query(note.get('text') or '')
      if not query:
        msk.notes_create(text=f'{mention} MTGのカードを検索するよ！', reply_id=note['id'])
        return

      try:
        # Yahoo画像検索でMTGのカードっぽい画像を探す
        search_query = build_card_image_search_query(query)
        image_file = download_first_image(search_query)
        drive_file = msk.drive_files_create(
          image_file,
          name=image_file.name,
          force=True,
        )
        msk.notes_create(
          text=f'{mention} 「{query}」の画像だよ',
          reply_id=note['id'],
          file_ids=[drive_file['id']],
        )
      except Exception as error:
        print(f"image reply failed: {error}")
        msk.notes_create(
          text=f'{mention} 画像を取ってこれなかったよ\n{short_error(error)}',
          reply_id=note['id'],
        )

async def on_follow(user):
  mention = user_mention(user)
  msk.notes_create(text=f'{mention} フォローありがとう！')
  try:
    msk.following_create(user['id'])
  except:
    pass

def user_mention(user):
  username = user['username']
  host = user.get('host')
  if host:
    return f'@{username}@{host}'
  return f'@{username}'

def extract_search_query(text):
  text = re.sub(r'@[A-Za-z0-9_]+(?:@[A-Za-z0-9_.-]+)?', ' ', text)
  return ' '.join(text.split())

def short_error(error):
  message = str(error)
  if len(message) > 180:
    return f"{message[:177]}..."
  return message

def build_card_image_search_query(query):
  query = query.strip()
  if not query:
    return CARD_IMAGE_SEARCH_REQUIRED_TERMS
  return f'{query} {CARD_IMAGE_SEARCH_REQUIRED_TERMS}'

def search_yahoo_images(query):
  response = requests.get(
    YAHOO_IMAGE_SEARCH_URL,
    params={
      "p": query,
      "ei": "UTF-8",
      "b": "1",
    },
    headers=REQUEST_HEADERS,
    timeout=10,
  )
  response.raise_for_status()

  image_urls = extract_yahoo_image_urls(response.text)
  if not image_urls:
    raise RuntimeError("No image URL found in Yahoo image search result")

  return image_urls

def extract_yahoo_image_urls(page_html):
  image_urls = []
  decoded_html = html.unescape(page_html)

  # Yahoo画像検索はページ内のJSONに元画像URLを埋め込むことがある。
  for key in ("originalUrl", "imageUrl", "thumbnailUrl", "contentUrl"):
    pattern = rf'"{key}"\s*:\s*"((?:https?:)?\\/\\/[^"]+)"'
    for match in re.finditer(pattern, decoded_html):
      add_image_url(image_urls, decode_url(match.group(1)))

  for pattern in (
    r'<img[^>]+(?:src|data-src)="([^"]+)"',
    r'<img[^>]+(?:src|data-src)=\'([^\']+)\'',
  ):
    for match in re.finditer(pattern, decoded_html):
      add_image_url(image_urls, decode_url(match.group(1)))

  # リンク先や属性値にURLエンコードされた画像URLが入っている場合の保険。
  for match in re.finditer(r'https?%3A%2F%2F[^"&\']+', decoded_html):
    add_image_url(image_urls, decode_url(match.group(0)))

  for match in re.finditer(r'https?://[^"\'<> ]+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^"\'<> ]*)?', decoded_html):
    add_image_url(image_urls, decode_url(match.group(0)))

  return list(dict.fromkeys(image_urls))

def decode_url(value):
  value = html.unescape(value).replace(r"\/", "/")
  value = unquote(value)
  try:
    return json.loads(f'"{value}"')
  except json.JSONDecodeError:
    return value

def add_image_url(image_urls, image_url):
  image_url = normalize_image_url(image_url)
  if image_url.startswith("//"):
    image_url = f"https:{image_url}"
  if not image_url.startswith(("http://", "https://")):
    return
  netloc = urlparse(image_url).netloc
  if netloc.endswith("yahoo.co.jp") or netloc == "s.yimg.jp":
    return
  image_urls.append(image_url)

def normalize_image_url(image_url):
  image_url = image_url.strip()
  for metadata_key in ("&refurl=", "&title=", "&domain=", "&w=", "&h=", "&faviconurl="):
    if metadata_key in image_url:
      image_url = image_url.split(metadata_key, 1)[0]
  return image_url

def download_first_image(query):
  errors = []
  for image_url in sort_image_urls(search_yahoo_images(query)):
    try:
      return download_image(image_url)
    except Exception as error:
      print(f"image candidate failed: {image_url}: {error}")
      errors.append(f"{image_url}: {error}")

  raise RuntimeError("Could not download any image: " + " / ".join(errors[:5]))

def sort_image_urls(image_urls):
  thumbnail_hosts = (
    "encrypted-tbn0.gstatic.com",
    "encrypted-tbn1.gstatic.com",
    "encrypted-tbn2.gstatic.com",
    "encrypted-tbn3.gstatic.com",
  )
  return sorted(
    image_urls,
    key=lambda image_url: urlparse(image_url).netloc in thumbnail_hosts,
  )

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
    name = f"yahoo-image{extension}"
  return name

if __name__ == "__main__":
  asyncio.run(runner())
