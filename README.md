# funyafunya

MTG あいまいサーチ

## 何

MTGのカードをあいまい検索するmisskeyのBotです。
pythonで動かします。

## 動かす

pythonでインストール。

```python
uv add misskey.py websockets python-dotenv pillow requests
```

`.env`ファイルを作成し、以下を用意します。

```.env
MISSKEY_HOST=(misskeyのURL)
TOKEN=(BOTのアクセストークン)
```

ローカルのMisskeyに接続する場合は以下のようにします。

```.env
MISSKEY_HOST=localhost
MISSKEY_PORT=3000
TOKEN=(BOTのアクセストークン)
```

uvで起動します。

```bash
uv run python main.py
```

## 更新履歴

### [2026/05/20]

- yahoo検索版`yahoo.py`でおっぱいチャレンジ（運命の逆転を持ってくること）に成功
- 再接続ループ処理

### [2026/05/19]

- pythonをuvで3.14.5に固定
- とりあえず実装

### [2026/05/18]

- リポジトリ生やした
