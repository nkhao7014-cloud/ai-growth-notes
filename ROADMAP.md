# Roadmap

## v1.5 完了

- Ask My Notes MVP
- PostgreSQLベースのRetrieval Interface
- Notes / AI Daily / Learning Edition横断検索
- Grounded answer、References、AIなしFallback、軽量ローカル履歴

## v1.6候補

- PostgreSQL Full Text Search rankingの強化
- Retrieval評価データセットと引用精度メトリクス
- pgvector / Embeddingを同じRetrieval Interfaceの実装として選択追加
- 会話履歴の任意サーバー保存と期間・source UI filter

## v1.4 完了

- Neon PostgreSQL、Render、単一ユーザー認証、CSRF、SQLite migration

## 今後

- 共有rate limit backend、CSP nonce、定期backup自動化、監視強化

## v1.3

- AI Daily（公式Feed、学習、実践、Notes連携）

## v1.4候補

- 管理画面からのFeed有効化・追加
- 日次Editionの履歴ナビゲーション
- AI要約キューと利用回数・失敗状況の可視化
- ETag / Last-Modifiedを使った条件付き取得
- AI Weeklyへ再利用できる記事選定サービス

対象外: 自動定期実行、通知、ログイン、記事全文保存、有料News API。
