# 開発ガイド

## 前提

- Python 3.12 以上（uv が自動で取得します）
- [uv](https://docs.astral.sh/uv/)（Python パッケージマネージャ）
- Node.js 20 以上 + npm（フロントエンド）

## セットアップ

```bash
cd backend
uv sync            # 依存関係と仮想環境（backend/.venv）を作成
uv run aiwm --help

cd ../frontend
npm install
```

## 開発サーバー

```bash
# バックエンド（http://127.0.0.1:8765）
cd backend && uv run aiwm start

# フロントエンド（Vite dev server、/api を 8765 へプロキシ）
cd frontend && npm run dev
```

本番配信と同じ構成で確認する場合は `npm run build` の後に `uv run aiwm start` を実行します（`frontend/dist` を FastAPI が配信）。

## テスト

```bash
cd backend
uv run pytest -q          # 単体・ワークフロー・MCP・復旧テスト
uv run ruff check .       # Lint
uv run ruff format .      # フォーマット

cd frontend
npm run check             # svelte-check
npm run test              # vitest
```

AI ワークフローのテスト（`tests/test_workflow.py`）は `app/llm/fake.py` の `ScriptedChatModel` でツール呼び出しをスクリプト化し、実際の Orchestrator を通して Manager → Worker → Review → 再計画を検証します。MCP テストは `tests/mcp_test_server.py`（stdio / Streamable HTTP）を実際に起動します。

## LLM プロバイダー

`backend/app/llm/providers.py` の `LLMFactory.register_provider(name, factory)` で追加プロバイダーを登録できます。`AIWM_LLM_PROVIDER_OVERRIDE=fake` を設定すると、API キーなしでスクリプト化モデルを使って動作確認できます。

## データベース変更

```bash
cd backend
# モデルを変更したら
AIWM_DATABASE_URL=sqlite:////tmp/empty.db uv run alembic revision --autogenerate -m "describe change"
uv run aiwm migrate
```

マイグレーションは起動時に自動適用されます。`alembic/versions/0001_initial_schema.py` は FTS5 仮想テーブルも作成します。

## ディレクトリ

SPEC 32 の推奨構成に従います。主要な入口:

- `backend/app/main.py` — `build_context()`（Bootstrap）と `create_app()`
- `backend/app/cli.py` — `aiwm` コマンド（start / setup / stop / status / backup / restore / autostart / migrate）
- `backend/app/orchestrator/runner.py` — 実行ループ
- `frontend/src/App.svelte` — SPA エントリ
