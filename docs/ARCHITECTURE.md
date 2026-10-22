# アーキテクチャ

Autonomous AI Work Manager は、1 つの Python プロセス（FastAPI + AI Orchestrator）と、ビルド済み静的ファイルとして配信される Svelte 5 フロントエンドで構成されます。

```text
Web Browser ── Svelte 5 SPA (frontend/dist)
      │  Fetch API / Server-Sent Events
      ▼
FastAPI Backend (backend/app)
  ├── api/            REST ルーター（SPEC 25）、SSE、ローカル API 保護
  ├── services/       Task / Chat / Memory / Artifact / Notification / Settings / Execution / Approval
  ├── agents/         Manager AI / Worker AI / Review AI / Chat（LangGraph）
  ├── orchestrator/   runner（実行ループ）、scheduler、event_queue、recovery
  ├── llm/            LLMFactory（OpenAI / Anthropic / Gemini / 追加プロバイダー / fake）
  ├── integrations/   MCP クライアント・認証・レジストリ・Adapter、ローカルファイル、権限
  ├── platform/       macOS / Windows / Linux / WSL Adapter
  └── infrastructure/ SQLite + Alembic、Secret Provider、バックアップ、ログ、単一インスタンス
```

## プロセスモデル

- `aiwm start`（`scripts/start.sh` / `start.ps1`）が uvicorn で FastAPI を起動します。
- FastAPI の lifespan で `Orchestrator` が起動し、同一プロセス内の asyncio タスクとして AI 実行ループを回します。
- データディレクトリの `aiwm.lock` を flock/msvcrt でロックし、多重起動（同一 DB への複数 Orchestrator）を防ぎます。
- ブラウザを閉じてもプロセスは動き続け、SSE で再接続時に状態を復元します。

## データ

- SQLite（WAL、外部キー ON）に構造化データを保存し、Markdown 成果物はファイルとして `artifacts/task-xxxx/` に保存します。
- スキーマは `backend/app/models/` の SQLAlchemy モデルと `backend/alembic/versions/` のマイグレーションで管理します（起動時に自動で `upgrade head`）。
- `memories_fts` / `chat_messages_fts` は FTS5（trigram トークナイザー）で、日本語・英語混在の検索に対応します。
- 主要テーブルは SPEC 23.2 の ER 図のとおりです。補助テーブル: `audit_events`, `notifications`, `app_events`（Orchestrator のイベントキュー）, `artifact_versions`, `artifact_task_links`, `artifact_sources`, `mcp_connections`, `mcp_tool_permissions`, `approval_requests`, `app_settings`。

## AI 実行フロー（SPEC 8.2）

```text
trigger (起動 / タスク作成・更新 / ユーザー指示 / 承認 / スケジュール時刻)
   ↓ app_events に永続化 → Orchestrator が drain
built-in checks（期限・確認待ちリマインダー、自動バックアップ）
   ↓
active な Execution Plan を実行（Worker を依存順に順次実行 → Review）
   ↓
Manager AI（LangGraph ツール呼び出し）: タスク選択 → Execution Plan + Work Item 作成
   ↓
Plan 実行 → Review
   ├── passed  → タスク review_pending / 成果物 review_pending / 通知
   ├── failed  → Manager AI 再計画（parent_plan_id で追跡、上限 max_replanning_attempts）
   └── blocked → タスク blocked + task_contexts に確認事項 + 通知
   ↓
進捗があれば "reevaluate" を再投入（Fresh Manager Execution、上限 max_consecutive_no_progress）
```

各 Agent Run は `agent_runs` に保存され、実行ごとに SQLite から必要なコンテキストを組み立てます（会話状態を跨いで保持しません）。

### エージェントとツール

| Agent | 主なツール（SPEC 26） |
|---|---|
| Manager | list_tasks, get_task, create_task, update_task, get_task_decisions, get_relevant_memories, get_user_state, list_execution_plans, get_execution_plan, create_execution_plan, create_work_items, get_review_results, schedule_action, create_notification, record_decision（ワンショット指示時のみ）, save_memory |
| Worker | get_work_item, get_execution_context, search_local_files, read_local_file, search_slack, search_google_drive, search_confluence, search_jira, search_memory, read_artifact, create_markdown_artifact, update_markdown_artifact, report_work_result, + MCP 由来の動的ツール |
| Review | get_execution_plan, get_work_item_results, read_artifact, get_source_references, submit_review |

ツールはサービス層のルールを強制します（例: `completed` への遷移はユーザー承認のみ、`user` 担当タスクは計画対象外、進行中の計画があるタスクは再計画しない、循環依存の拒否、external_write ツールはユーザー承認待ち）。

## 復旧（SPEC 8.4）

起動時に `orchestrator/recovery.py` が以下を行います。

- `running` のままの agent_runs → failed（interrupted by restart）
- `running` の work_items → pending（成功済みの結果は再利用）
- `reviewing` の plan → running（Review を再実行）
- `running` のスケジュール → pending、未処理の app_events はそのまま drain

## セキュリティ（SPEC 27）

- API は `127.0.0.1` にバインド。`Host` 検証、`Origin` 検証、変更系リクエストに `X-Requested-With: AIWM` ヘッダーを要求（CSRF 対策）。FastAPI の strict content-type も有効。
- API キーは Secret Provider からメモリ上で注入し、ログは `SecretRedactingFilter` でマスク、フロントエンドには設定済みフラグのみ返します。
- ローカルファイルアクセスは設定したディレクトリと拡張子に限定。成果物パスはディレクトリ外参照を拒否。
- 外部データ（MCP 結果・ファイル内容）は「外部データ」マーカー付きで LLM に渡し、含まれる指示には従わないようプロンプトで指示します。権限はツールごとの設定のみで変更できます。
