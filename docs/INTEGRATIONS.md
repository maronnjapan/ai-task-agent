# MCP 連携ガイド

外部サービスは MCP（Model Context Protocol）経由で利用します。設定画面「MCP 連携」から接続先を追加・編集・削除・接続テストできます。

## 接続方式

| transport | 設定項目 |
|---|---|
| `stdio` | `command`, `args`, `env`（アプリが子プロセスとして起動） |
| `streamable_http` | `url`, `headers`, `timeout_seconds` |

OS ごとのコマンド解決（`npx` → Windows では `npx.cmd`、`~` 展開、PATH 検索）はアプリ側で行います。

## 認証

| auth_type | 説明 |
|---|---|
| `none` | 認証なし |
| `api_token` | `auth_config.header_name`（既定 `X-API-Key`）に `secret` を送信 |
| `bearer` | `Authorization: Bearer <secret>` |
| `oauth2` | 認可コードフロー（PKCE）。`auth_config` に `client_id`, `authorization_url`, `token_url`, `scope`, `redirect_uri`（既定 `http://127.0.0.1:8765/api/integrations/oauth/callback`）を設定。クライアントシークレットは `secret` に入力。「OAuth 認証」ボタン → ブラウザで認可 → コールバックでトークン取得。期限切れ時は自動更新、401 時は再認証 |
| `custom` | Adapter が提供する固有の認証 |

トークン・シークレットはすべて Secret Provider（Keychain / .env）に保存され、SQLite には保存されません。環境変数（`env`）や HTTP ヘッダーのうち名前に `TOKEN` / `KEY` / `SECRET` / `PASSWORD` / `AUTHORIZATION` などを含むものも自動的に Secret Provider へ移され、SQLite と API 応答には `<secret>` というプレースホルダーだけが残ります（値を空にすると削除）。

## 標準 Adapter とプリセット

| adapter | 想定 MCP サーバー（プリセット） | 必要な環境変数（env） |
|---|---|---|
| `slack` | `npx -y @modelcontextprotocol/server-slack` | `SLACK_BOT_TOKEN`, `SLACK_TEAM_ID` |
| `google_drive` | `npx -y @modelcontextprotocol/server-gdrive` | `GDRIVE_CREDENTIALS_PATH` |
| `confluence` | `uvx mcp-atlassian` | `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` |
| `jira` | `uvx mcp-atlassian` | `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN` |
| `generic` | 任意の MCP サーバー | — |

Adapter は検索ツールの選択、引数の変換（例: Jira の JQL、Confluence の CQL）、レスポンスの正規化（title / snippet / url / id）、ツール権限の既定値、エラー変換、レート制限の待機を担当します。Worker AI の `search_slack` / `search_google_drive` / `search_confluence` / `search_jira` は対応する adapter の接続を使用します。新しいサービスは `backend/app/integrations/mcp/adapters/` に `ServiceAdapter` を実装し `register_adapter()` で登録します。

## ツール権限（SPEC 17.14）

| 権限 | 動作 |
|---|---|
| `read` | 自由に実行 |
| `internal_write` | アプリ内への書き込み。自由に実行 |
| `external_write` | 実行前にユーザー承認が必要。承認待ちはタスク一覧の「承認待ち」に表示され、承認/却下できます |

権限はツール名から自動分類され（`search`, `get`, `list`, `read` などは `read`、`post`, `send`, `create`, `update`, `delete` などは `external_write`、判別できない名前は安全のため `external_write`）、接続テスト / ツール一覧の表で上書きできます。`external_write` の呼び出しは承認要求（通知 + タスク一覧の「承認待ち」）を作成し、Worker は `MCP_APPROVAL_WAIT_SECONDS` の間承認を待ちます。間に合わなかった場合は作業が `blocked` になり、あとから承認すると該当作業が自動で再開され、承認済みの呼び出しは一度だけ実行されます。外部文書に含まれる指示で権限が変わることはありません。Slack への投稿、外部文書の更新、メール送信は承認なしでは実行されません。

## ローカルファイル

設定画面「ローカル情報源」で検索対象ディレクトリと拡張子（既定: .md .txt .json .yaml .yml .csv .py .ts .js .go）を指定します。Worker AI の `search_local_files` / `read_local_file` は指定ディレクトリの外や未許可の拡張子にはアクセスできません。

## 動作確認

`backend/tests/mcp_test_server.py` は stdio と Streamable HTTP の両方で動くテスト用サーバーです。

```bash
cd backend
uv run python tests/mcp_test_server.py            # stdio
uv run python tests/mcp_test_server.py http 8900  # http://127.0.0.1:8900/mcp
```

設定画面で `command: <python>`, `args: tests/mcp_test_server.py` の stdio 接続を追加して接続テストを実行すると、ツール一覧（`search_messages`, `get_item`, `post_message`）が表示されます。
