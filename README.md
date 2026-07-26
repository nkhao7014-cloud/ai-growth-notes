# AI Growth Notes

FastAPI、SQLite、ブラウザだけで利用できる個人用AI学習ノートです。v1.3.0では公式RSS/Atomを読む「AI Daily」を追加しました。

## 起動

```powershell
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

`http://127.0.0.1:8000/ai-daily` を開き、「更新する」で公式Feedを取得します。通常表示はSQLiteだけを参照し、画面を開くだけでは外部通信しません。記事は既読・お気に入りにでき、「Notesへ保存」で既存Notesへ重複せず保存できます。

## 環境変数

- `AI_PROVIDER=mock`: AI APIを呼びません（既定・推奨フォールバック）。
- `AI_PROVIDER=gemini`: 新規記事の一部をGeminiで短く整理します。
- `GEMINI_API_KEY`: Gemini利用時のみ必要です。値をリポジトリや文書へ記載しないでください。
- `AI_MODEL`: 既存AI機能とAI Dailyが利用するGeminiモデル名です。

Keyがない、AIが失敗する、またはTimeoutになった場合も、Feedの概要・カテゴリ別の重要理由・ルールベースタグで動作します。

## Feedの追加・削除

`services/ai_daily_feed_service.py` の `AI_DAILY_FEEDS` に `name`、`url`、`default_category` を追加します。RSS/Atomの公開Feed、HTTPS、記事全文ではなく短い概要を配信する公式ソースを使い、実取得テストを行ってください。1 Feed最大12件、応答最大2 MB、Timeout 10秒です。

## テスト

```powershell
python -m unittest discover -s tests -v
```

外部Feedは自動テストではMockします。実Feed確認はネットワーク環境で別途行います。

## 既知の制限

- 自動定期取得、通知、複数ユーザー、AI Weekly/Monthlyは未実装です。
- Feed提供元のURLやXML形式変更時は設定・Parser調整が必要です。
- Learning/PracticeはMVPのルールベース生成です。
