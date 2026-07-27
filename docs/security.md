# Security

- passwordはArgon2 hashだけを環境変数へ保存します。usernameの存在をlogin errorで区別しません。
- sessionは署名付き、HttpOnly、SameSite=Lax。productionではSecureです。sessionには認証状態、username、login時刻、CSRF tokenだけを保存します。
- 状態変更はsession tokenと `X-CSRF-Token` またはform tokenを定数時間比較します。
- `next` はscheme/host、`//`、backslashを拒否します。API未認証は401、page未認証は303です。
- 5分間5回のmemory型login制限です。複数instance/workerでは共有されず、restartで消える制限があります。
- CSP、nosniff、same-origin referrer、frame denial、認証後no-store、production HSTSを設定します。
- logへpassword/hash/secret/DB URL/cookie/CSRF/note本文/API keyを出さないでください。

残課題は共有rate-limit backend、CSP nonceによるinline script排除、定期的なsecret rotation、Neon監査・backup運用です。
