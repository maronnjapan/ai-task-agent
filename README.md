# Autonomous AI Work Manager

ユーザーが目標（タスク）を管理し、AI がその達成のための計画・調査・作業・レビュー・進捗管理を主体的に進める、個人用のローカル AI タスクマネージャーです。仕様は [SPEC.md](SPEC.md) を参照してください。

- Manager AI がタスクを把握して優先順位を決め、関連タスクをまとめた Execution Plan と Work Item を作成
- Worker AI が調査（ローカルファイル / MCP 経由の Slack・Google Drive・Confluence・Jira）と Markdown 成果物の作成を順次実行
- Review AI が完了条件への達成度を評価し、不合格なら Manager AI が再計画（上限あり）
- 合格した成果物はユーザーの確認待ちに。承認・修正依頼・追加調査依頼・保留を UI から操作
- 複数チャット、正式な決定事項、長期記憶（Global / Category / Task、FTS5 検索）
- プロアクティブ通知（アプリ内 + OS デスクトップ通知）、スケジューラー、再起動時の復旧、バックアップ/復元
- macOS / Windows 11 / WSL2 対応。API キーは macOS Keychain または `.env` から安全に注入

## 技術スタック

| 層 | 技術 |
|---|---|
| フロントエンド | Svelte 5, TypeScript, Vite, CSS, Fetch API, Server-Sent Events |
| バックエンド | Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic, LangChain, LangGraph, SQLite (FTS5), MCP |
| パッケージ管理 | **uv**（Python）, npm（フロントエンド） |

## クイックスタート

### 必要なもの

- [uv](https://docs.astral.sh/uv/)（Python 3.12 は uv が自動取得します）
- Node.js 20 以上（フロントエンドのビルド用）
- LLM プロバイダーの API キー（標準は OpenAI。Anthropic / Google Gemini も設定可能）

### macOS

```bash
git clone <this repository> ai-work-manager && cd ai-work-manager
./scripts/install.sh          # uv / 依存関係 / フロントエンドビルド / .env 作成 / API キー登録（Keychain）
./scripts/start.sh --open     # セッショントークン付き URL をブラウザで開く
./scripts/stop.sh
```

起動時に表示される `http://127.0.0.1:8765/?token=...` を一度開くとブラウザにセッション Cookie が保存され、以後は `http://127.0.0.1:8765` だけでアクセスできます（URL は `cd backend && uv run aiwm url` でいつでも再表示できます）。

初回起動時に API キーが未登録なら CLI が入力を求め、macOS Keychain に保存します（`.env` の API キー欄は空のままで OK）。自動起動（launchd）は設定画面か `./scripts/install.sh --autostart` で登録できます。

### Windows 11

```powershell
git clone <this repository> ai-work-manager; cd ai-work-manager
scripts\install.ps1           # uv / 依存関係 / フロントエンドビルド / .env 作成
notepad .env                  # SECRET_BACKEND=dotenv、OPENAI_API_KEY=... を記入
scripts\start.ps1 -Open
scripts\stop.ps1
```

`PowerShell` の実行ポリシーで止まる場合は `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` を実行してください。自動起動はタスクスケジューラに登録されます（設定画面 / `scripts\install.ps1 -Autostart`）。

### WSL2（Ubuntu など）

```bash
# WSL のシェルで、Linux ファイルシステム内（例: ~/projects）にクローン
git clone <this repository> ~/projects/ai-work-manager && cd ~/projects/ai-work-manager
./scripts/install.sh          # .env は SECRET_BACKEND=dotenv で作成されるので API キーを記入
./scripts/start.sh
```

Windows 側のブラウザで `http://localhost:8765` を開きます（WSL2 は localhost を自動転送。古い WSL で届かない場合は `wsl hostname -I` の IP を使うか、`APP_HOST=0.0.0.0` にして Windows ファイアウォールを許可）。デスクトップ通知は Windows ホストへブリッジされ、自動起動は systemd（`/etc/wsl.conf` で `systemd=true`）または `~/.profile` 方式を自動選択します。

### 手動セットアップ（全 OS 共通）

```bash
cp .env.example .env
cd backend && uv sync && uv run aiwm setup && uv run aiwm start
cd ../frontend && npm install && npm run build   # UI をビルド（FastAPI が配信）
```

## 設定

`.env`（一般設定）とアプリ内設定画面（LLM / Manager / 通知 / ローカル情報源 / バックアップ / MCP 連携 / 自動起動）を使います。主な `.env` 項目は [.env.example](.env.example) を参照してください。

| 項目 | 説明 |
|---|---|
| `SECRET_BACKEND` | `auto`（macOS: Keychain、それ以外: .env）/ `keychain` / `dotenv` |
| `AIWM_DATA_DIR` | データ保存先（既定: macOS/WSL `~/.ai-work-manager/`、Windows `%LOCALAPPDATA%\AIWorkManager\`） |
| `MANAGER_MODEL` 等 | エージェントごとのモデル。設定画面でプロバイダー・温度・タイムアウト・再試行・カスタムプロンプトも変更可 |
| `AUTO_START_MANAGER` | 起動時に Manager AI の自律実行を開始するか |
| `API_SESSION_TOKEN_REQUIRED` | ローカル API のセッション保護（既定 true。`false` でトークンなしアクセスを許可） |
| `MCP_APPROVAL_WAIT_SECONDS` | external_write ツールの承認を Worker が待つ秒数（既定 300） |

## CLI

```bash
cd backend
uv run aiwm start [--open] [--no-prompt]   # バックエンド起動
uv run aiwm setup                            # API キーの対話登録
uv run aiwm url                              # セッショントークン付きの UI URL を表示
uv run aiwm stop | status                    # 停止 / 状態表示
uv run aiwm backup [--directory DIR]         # バックアップ
uv run aiwm restore <archive.zip>            # 復元（復元前に自動バックアップ）
uv run aiwm autostart install|remove|status  # OS 自動起動
uv run aiwm migrate                          # DB マイグレーション
```

## ドキュメント

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 構成、データモデル、AI 実行フロー、復旧、セキュリティ
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — 開発環境、テスト、マイグレーション
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — 起動・停止、API キー、自動起動、通知、バックアップ、トラブルシューティング
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — MCP 接続、認証（API Token / Bearer / OAuth 2.0）、Slack / Google Drive / Confluence / Jira、権限

## テスト

```bash
cd backend && uv run pytest -q && uv run ruff check .
cd frontend && npm run check && npm run test && npm run build
```

## ライセンス

MIT
