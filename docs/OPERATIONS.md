# 運用ガイド

## 起動・停止

| OS | 起動 | 停止 |
|---|---|---|
| macOS / WSL / Linux | `./scripts/start.sh`（`--open` でブラウザ起動、`--foreground` で前面実行） | `./scripts/stop.sh` |
| Windows 11 | `scripts\start.ps1`（`-Open` / `-Foreground`） | `scripts\stop.ps1` |

UI: `http://127.0.0.1:8765`（`.env` の `APP_HOST` / `APP_PORT` で変更可能）。

## データディレクトリ

| OS | 既定 |
|---|---|
| macOS / WSL | `~/.ai-work-manager/` |
| Windows | `%LOCALAPPDATA%\AIWorkManager\` |

`AIWM_DATA_DIR` で変更できます。構成は `data/app.db`, `artifacts/`, `backups/`, `logs/`, `exports/`, `config/` です。WSL では Linux ファイルシステム内（`/home/...`）を使用してください（`/mnt/c` 配下は SQLite の性能・ロック面で非推奨）。

## API キー

- **macOS**: `SECRET_BACKEND=auto`（Keychain）。初回起動時または `uv run aiwm setup` で入力し、Keychain（service: `ai-work-manager`）に保存します。`.env` の API キー欄は空のままで構いません。設定画面の「API キー」からも登録できます。
- **Windows / WSL**: `SECRET_BACKEND=dotenv`。`.env` の `OPENAI_API_KEY=` などに記入するか、設定画面から登録（`.env` に書き込み、権限 600）。
- キーはログに出力されず、フロントエンドにも返されません。

## 自動起動

設定画面の「自動起動」または CLI:

```bash
cd backend && uv run aiwm autostart install|remove|status
```

| OS | 方式 |
|---|---|
| macOS | `~/Library/LaunchAgents/com.aiworkmanager.backend.plist`（launchd） |
| Windows | タスクスケジューラ（ログオン時） |
| WSL / Linux | systemd user service（利用可能な場合）。systemd が無い WSL では `~/.profile` に起動ブロックを追加 |

WSL で systemd を使う場合は `/etc/wsl.conf` に `[boot]\nsystemd=true` を設定し、`wsl --shutdown` 後に再起動してください。

## 通知

- アプリ内通知は常に保存されます。デスクトップ通知は設定で ON/OFF、通知レベル（low/normal/high）、通知停止時間帯、最小間隔を設定できます。
- macOS: 通知センター、Windows: トースト、WSL: Windows ホストへ PowerShell 経由でトースト（失敗時は notify-send / アプリ内通知）。

## バックアップと復元

```bash
cd backend
uv run aiwm backup [--directory DIR] [--label NAME]
uv run aiwm restore <archive.zip> [--yes]   # 停止中に実行。復元前に現在のデータを自動バックアップ
```

設定画面からも実行できます（復元は確認ダイアログあり、復元後は画面を再読み込み）。自動バックアップは「バックアップ」設定で間隔を指定します。アーカイブには SQLite（オンラインバックアップ API でスナップショット）、Markdown 成果物、`config/` が含まれます。

## ログ

`<data dir>/logs/app.log`（ローテーション）と `start.log`。API キーはマスクされます。監査ログは UI（AI マネージャー画面）または `GET /api/audit` で確認できます。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `Another instance already holds aiwm.lock` | 既に起動中。`scripts/stop.sh` で停止、または stale な `aiwm.lock` / `aiwm.pid` を削除 |
| 「API キーが未設定です」通知 | 設定画面の API キーで登録、または `.env` / Keychain に設定 |
| Manager が動かない | AI マネージャー画面で一時停止状態を確認、`今すぐ実行` を押す。`logs/app.log` を確認 |
| WSL からブラウザが開かない | Windows 側ブラウザで `http://localhost:8765` を直接開く（WSL2 は localhost を転送） |
| MCP 接続テスト失敗 | 設定画面の `last_error` を確認。stdio の場合はコマンドのパス（`npx`, `uvx`）が通っているか確認 |
