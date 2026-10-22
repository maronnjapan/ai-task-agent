# Autonomous AI Work Manager — フロントエンド

Svelte 5 (runes) + TypeScript + Vite で構築した軽量 SPA です。ビルド成果物 (`dist/`) は FastAPI バックエンドが静的ファイルとして配信します。

## 開発

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (/api は http://127.0.0.1:8765 にプロキシ)
```

バックエンドを先に起動しておいてください (`backend/` を参照)。

## ビルド・検証

```bash
npm run build      # dist/ に出力。バックエンドが / で配信します
npm run check      # svelte-check (型・テンプレート検査)
npm run test       # vitest (diff ユーティリティ / API クライアント)
```

## 構成

```
src/
  main.ts              エントリ
  App.svelte           シェル (トップバー・ルーティング・トースト)
  api/client.ts        型付き fetch ラッパーとエンドポイント定義 (X-Requested-With: AIWM を自動付与)
  api/types.ts         OpenAPI スキーマに対応する型
  lib/router.svelte.ts ハッシュルーター (#/, #/tasks/:id, #/artifacts/:id, #/manager, #/settings)
  lib/diff.ts          行差分 (変更履歴用)
  lib/markdown.ts      marked + DOMPurify
  lib/format.ts        日時整形・日本語ラベル
  stores/*.svelte.ts   runes ベースのストア (tasks, notifications, manager, events=SSE, toasts)
  pages/               画面 (動的 import で遅延読み込み)
  components/          共通コンポーネント / タスク詳細タブ / 設定セクション
  styles/global.css    CSS 変数 (ライト・ダーク対応) と基本スタイル
```

## 備考

- 通信は同一オリジンのみ。GET 以外のリクエストには CSRF 対策ヘッダー `X-Requested-With: AIWM` を付与します。
- `GET /api/system/events` の Server-Sent Events を受信し、各ストアを更新します (再取得はデバウンス)。
- タイムスタンプは API から ISO-8601 (UTC) で受け取り、ブラウザのローカルタイムゾーンで表示します。
