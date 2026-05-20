import asyncio
import html
from io import BytesIO
import json
import mimetypes
import os
import re
from urllib.parse import urlparse, urlunparse

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

MISSKEY_URL = build_misskey_url(MISSKEY_HOST, MISSKEY_PORT)
WS_URL = build_streaming_url(MISSKEY_URL, TOKEN)
BING_IMAGE_SEARCH_URL = "https://www.bing.com/images/search"
REQUEST_HEADERS = {
  "User-Agent": "Mozilla/5.0 (compatible; funyafunya-bot/0.1)"
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CARD_ASPECT_RATIO = 63 / 88
CARD_ASPECT_TOLERANCE = 0.08

msk = Misskey(MISSKEY_URL, i=TOKEN)
MY_ID = msk.i()['id']

async def runner():
  async with websockets.connect(WS_URL) as ws:
    await ws.send(json.dumps({
      "type": "connect",
      "body": {
        "channel": "hybridTimeline", # すべてのイベントを受け取るチャンネル
        "id": "funyafunya" 
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
        # Bing画像検索でMTGのカードっぽい画像を探す
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
        msk.notes_create(text=f'{mention} 画像を取ってこれなかったよ', reply_id=note['id'])

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

def build_card_image_search_query(query):
  return f'+{query} MTGカード'

def search_bing_images(query):
  response = requests.get(
    BING_IMAGE_SEARCH_URL,
    # 検索パラメーター
    params={
      "q": query,
      "form": "HDRSC2",
      "first": "1",
      "mkt": "ja-JP",
      "cc": "JP",
      "setLang": "ja",
      "qft": "+filterui:aspect-tall", # 縦長の画像に絞る
      "safeSearch": "Moderate", # セーフサーチを適度に厳しく
    },
    headers=REQUEST_HEADERS,
    timeout=10,
  )
  response.raise_for_status()

  image_urls = []
  for match in re.finditer(r'class="iusc"[^>]+m="([^"]+)"', response.text):
    metadata = json.loads(html.unescape(match.group(1)))
    for key in ("murl", "turl"):
      image_url = metadata.get(key)
      if image_url and image_url.startswith(("http://", "https://")):
        image_urls.append(image_url)

  if not image_urls:
    raise RuntimeError("No image URL found in Bing image search result")

  return list(dict.fromkeys(image_urls))

def download_first_image(query):
  errors = []
  for image_url in search_bing_images(query):
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
    name = f"bing-image{extension}"
  return name

if __name__ == "__main__":
  asyncio.run(runner())
