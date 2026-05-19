import asyncio
import json
import os
from urllib.parse import urlparse, urlunparse

import websockets
from misskey import Misskey

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
      msk.notes_create(text=f'{mention} 呼んだ？', reply_id=note['id'])

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

if __name__ == "__main__":
  asyncio.run(runner())
