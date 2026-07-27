# Neon / Render deployment

1. Neonでproject/databaseを作り、SSL付きconnection stringを取得します。
2. `python scripts/generate_password_hash.py` と `python scripts/generate_session_secret.py` をローカル実行します。
3. Render Web Serviceへrepositoryを接続し、Buildを `pip install -r requirements.txt`、Startを `uvicorn main:app --host 0.0.0.0 --port $PORT`、Health pathを `/health` にします。
4. Render Dashboardへ `DATABASE_URL`、`APP_USERNAME`、`APP_PASSWORD_HASH`、`SESSION_SECRET`、`APP_ENV=production`、任意の `SESSION_MAX_AGE=604800` を設定します。秘密値はBlueprintへ直書きしません。
5. 初回deploy後にloginし、note作成、favorite、検索、AI Daily保存、logoutを確認します。スマートフォンの4G/5GからRenderのHTTPS URLを開いて確認します。

## Migration and persistence

最初に `--dry-run`、次に本実行します。本実行はupsert方式で再実行可能です。移行後にRenderを再deployし、件数が維持されることを確認します。Render filesystemではなくNeonへ保存されるため再deployでデータは消えません。

## Backup / rollback

Neonのbranchまたはbackupを取得し、旧SQLite 2ファイルも変更せず保管します。rollbackは旧v1.3をローカルで旧DBに接続するか、Neonの復元point/branchへ接続先を戻します。Migration中の失敗はtransaction rollbackされます。

Free planにはsleep、resource、接続数、保持期間等の制約があります。最新条件はNeon/RenderのDashboardと公式文書で確認してください。
