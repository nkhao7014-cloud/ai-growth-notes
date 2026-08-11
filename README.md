# AI Growth Notes v1.5.0 Cloud Edition

## Ask My Notes

ログイン後に `/assistant` を開くと、自分のNotes、AI Daily、AI Dailyの学習情報を横断して質問できます。回答の下には、実際に根拠として使われた記録だけが表示されます。

Geminiを使う場合は `AI_PROVIDER=gemini` と `GEMINI_API_KEY` を設定します。AI未設定・timeout・Provider障害時も、関連記録の検索結果は利用できます。検索はPostgreSQLの限定Queryで行い、外部Vector DBやWeb検索は使用しません。

詳しい使い方と制限は [Ask My Notes documentation](docs/assistant.md) を参照してください。

FastAPI、Neon PostgreSQL、署名付きCookie認証で動作する単一ユーザー向け学習ノートです。アプリ本体はSQLiteを使用せず、旧 `notes.db` は専用scriptだけがread-onlyで参照します。

## Local setup

```powershell
python -m pip install -r requirements.txt
python scripts/generate_password_hash.py
python scripts/generate_session_secret.py
python -m uvicorn main:app --reload
```

`.env` に `DATABASE_URL`、`APP_USERNAME`、`APP_PASSWORD_HASH`、`SESSION_SECRET`、`ENVIRONMENT=development` を設定します。平文パスワードは保存しません。

```powershell
python scripts/migrate_sqlite_to_postgres.py --sqlite-path notes.db --dry-run
python scripts/migrate_sqlite_to_postgres.py --sqlite-path notes.db
```

Migrationは3表（`notes`、`ai_daily_items`、`ai_daily_editions`）をtransaction内でupsertし、IDとsequenceを維持します。事前バックアップを保持し、移行後は件数と主要機能を確認してください。

詳細は [deployment](docs/deployment.md) と [security](docs/security.md) を参照してください。
