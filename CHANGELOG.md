# Changelog

## 1.5.0 - 2026-08-11

- Notes、AI Daily、学習Editionを検索するAsk My Notesを追加
- 引用IDに基づくReferences、Suggested Questions、最新20件のローカル履歴を追加
- Gemini未設定・timeout・エラー時のretrieval-only fallbackを追加
- Prompt Injectionをデータとして隔離し、Context件数と文字数を制限
- Desktop、Tablet、Mobile対応の専用UIとDashboard導線を追加

## 1.3.0 - 2026-07-26

- 公式RSS/Atom 5件の取得、正規化、SQLite保存、重複排除を追加
- AI Daily API、日次Highlights、Learning、Practice、Reading Listを追加
- 既読、お気に入り、既存Notesへの冪等保存を追加
- Loading、Empty、Error、Refresh、成功通知とモバイル表示を追加
- 任意のGemini補強とAIなしのルールベースフォールバックを追加
- Feed/API/DB/Notes連携の自動テストを追加
# v1.4.0

- Neon PostgreSQL専用Database LayerとSQLite read-only migrationを追加
- 単一ユーザーArgon2認証、署名付きsession、CSRF、login rate limitを追加
- Render Blueprint、health check、security headers、絶対path配信を追加
