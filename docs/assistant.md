# Ask My Notes

Ask My Notesは一般的なChatbotではなく、AI Growth Notes内の自分の学習記録を根拠に質問へ答える機能です。

## 使い方

ログイン後、Dashboardの「Ask My Notes」から開きます。Enterで送信、Shift+Enterで改行できます。

## 検索対象

- Notes: 本文、AI要約、要約内のタグ、作成日
- AI Daily: 日本語タイトル・要約・重要性・主要ポイントを優先し、原文、カテゴリ、タグ、公開日も検索
- Learning Edition: 学習Topic、理由、Points、日付

PostgreSQLの `ILIKE`、タグ相当、日付、source条件を使います。Assistant候補は最大10件、AI Contextは最大8件、各本文は最大1,400文字です。

## AI ProviderとFallback

既存の `AI_PROVIDER` / `AI_MODEL` / `GEMINI_API_KEY` を再利用します。Gemini未設定、timeout、失敗時はAI回答を作らず、関連記録だけを表示します。

## References

Contextに `N1` 形式のIDを付け、回答で引用されたIDだけをサーバー側で照合して表示します。Fallback時は検索結果であることを明示します。

## Security

既存Session認証とCSRFを適用します。質問は最大2,000文字、sourceはallowlistです。Notesは命令ではなく区切られたデータとして扱います。UIはユーザー文字列とAI文字列を `textContent` で描画します。

## 既知の制限

- 意味検索ではなく語句の部分一致で、言い換えには弱い場合があります。
- タグはNotesのAI要約内に埋め込まれています。
- 履歴はブラウザlocalStorageの最新20件で、端末間同期されません。

将来は `search_user_knowledge` の実装をFTS rankingやEmbedding/pgvectorへ差し替えられます。

## AI Daily日本語Backfill

既存記事の候補確認:

```powershell
python scripts/backfill_ai_daily_japanese.py --dry-run
```

最大20件の処理:

```powershell
python scripts/backfill_ai_daily_japanese.py --limit 20
```

英語原文と同一の日本語フィールドも未日本語化として扱います。Provider設定は認証済み環境から
`GET /api/ai-daily/translation-status` で確認できます。API Keyそのものは返しません。
