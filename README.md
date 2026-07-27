# AI Growth Notes v1.4.0 Cloud Edition

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
