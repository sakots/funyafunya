# funyafunya

MTG あいまいサーチ

## 何

MTGのカードをあいまい検索するmisskeyのBotです。
pythonで動かします。

## 動かす

pythonでインストール。

```python
uv add websockets misskey.py python-dotenv
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

### [2026/05/19]

- pythonをuvで3.14.5に固定
- メンションしたら返事が来るようにまでできた

### [2026/05/18]

- リポジトリ生やした
