# RolexReservation

ロレックス表参道ブティック「事前来店予約」を**毎週自動応募**するスクリプト。
Playwright(実Chrome)でフォームを自動入力し、reCAPTCHA はプロファイル信頼で
自動通過(画像認証時のみ手動フォールバック)、**SMS認証コードは Mac のメッセージ.app
(`chat.db`)から自動読み取り**して入力します。

> ⚠️ **注意**
> - 予約サイトの利用規約は自動化(bot)を禁止している場合があります。自己責任でご利用ください。
> - reCAPTCHA は Google の判定次第で画像認証が出ることがあり、**完全自動は100%保証できません**。
> - SMS自動読取には **フルディスクアクセス権限** が必須です(下記)。

---

## 構成

| ファイル | 役割 |
|---|---|
| `reserve.py` | メイン。予約フロー全体を自動実行 |
| `sms_reader.py` | `chat.db` から認証コードを読み取る |
| `explore.py` | サイト構造の調査用(通常は使わない) |
| `config.example.toml` | 設定テンプレート(→ `config.toml` にコピーして記入) |
| `config.ginza.toml` | 銀座店用の設定(`--config` で切替) |
| `config.shinjuku.toml` | 新宿店用の設定(金曜17:00) |
| `run.sh` | launchd/手動実行のラッパー |
| `com.user.rolexreservation.plist` | 週次スケジュール(LaunchAgent) |

`config*.toml`(`config.example.toml` を除く)と `logs/`、`venv/` は `.gitignore` 済み
(個人情報・成果物はコミットされません)。

### 複数店舗(表参道店 / 銀座店 / 新宿店)
設定ファイルを店舗ごとに分け、`--config` で切り替えます。`[site].start_url` で開始URLを指定。
lexia系(銀座・新宿)は開始URLが直接「来店日選択」ページのため、予約タイプ選択は自動でスキップされます。
枠の選び方は設定で変えられます(例: デイトナ枠優先 or 時間優先)。

| 店舗 | 設定ファイル | 希望条件 |
|---|---|---|
| 表参道店 | `config.toml`(既定) | 火曜のデイトナ枠 |
| 銀座店 | `config.ginza.toml` | 水曜のデイトナ枠 |
| 新宿店 | `config.shinjuku.toml` | 金曜 17:00(デイトナ枠なし=時間優先) |

```bash
./venv/bin/python reserve.py                             # 表参道店(火曜デイトナ)本番
./venv/bin/python reserve.py --config config.ginza.toml     # 銀座店(水曜デイトナ)本番
./venv/bin/python reserve.py --config config.shinjuku.toml  # 新宿店(金曜17:00)本番
# 各店とも --dry-date(空き確認・送信なし)/ --no-submit(安全テスト)を付与可能
```

> 時間優先(新宿店)にしたい場合は `time_priority_keywords = []`(デイトナ優先を無効化)に加え、
> `preferred_weekdays` と `preferred_times` で曜日・時間を指定します。

---

## セットアップ

### 0) 依存(クローン直後のみ)
```bash
cd /Users/myokota/git/RolexReservation
python3 -m venv venv
./venv/bin/python -m pip install -U pip playwright
./venv/bin/python -m playwright install chromium
```

### 1) 設定ファイル
```bash
cp config.example.toml config.toml
```
`config.toml` を開き、氏名・カナ・生年月日・**実在する自分の携帯番号**(SMSが届く番号)・
メール・希望日時を記入。

### 2) フルディスクアクセス(SMS読取の必須権限)
システム設定 →「プライバシーとセキュリティ」→「フルディスクアクセス」で次を追加・ON:

- **手動実行に使うターミナル.app(または iTerm)**
- **launchd 用に python 本体**:`+` → `⌘⇧G` で下記を貼り付けて追加
  ```
  /opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/bin/python3.14
  ```
  ※ `brew upgrade` で python のパスが変わったら再登録が必要です。

確認:
```bash
./venv/bin/python sms_reader.py --since 600   # エラーが出なければOK
# 携帯にSMSを送って↓で到着→コード抽出をテスト
./venv/bin/python sms_reader.py --wait 60
```

### 3) ブラウザプロファイルを育てる(reCAPTCHA対策)
```bash
./venv/bin/python reserve.py --setup-profile
```
開いた Chrome で **Google にログイン**し、数分間ふつうに閲覧してから Enter。
これで「私はロボットではありません」がクリックだけで通過しやすくなります。

### 4) 安全テスト(送信なし)
```bash
./venv/bin/python reserve.py --no-submit
```
①予約タイプ →②日時選択 →③入力 →reCAPTCHA まで進み、**確認ボタン直前で停止**。
`logs/page_03c_before_submit.png` で入力内容と reCAPTCHA 通過(緑チェック)を確認。

### 5) 本番テスト(実際に1件応募)
```bash
./venv/bin/python reserve.py
```
最後まで自動実行(SMS自動入力含む)。`logs/page_07_done.png` で完了を確認。

### 6) 週次スケジュール(完全自動運用)
`com.user.rolexreservation.plist` の `Weekday/Hour/Minute` を希望の曜日・時刻に編集
(画像認証が出ても対応できる、在席しやすい時間帯を推奨)。
```bash
cp com.user.rolexreservation.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rolexreservation.plist
# 即時テスト:
launchctl kickstart -k gui/$(id -u)/com.user.rolexreservation
# 解除:
# launchctl bootout gui/$(id -u)/com.user.rolexreservation
```

> Mac はスケジュール時刻に**起動・ログイン状態**である必要があります(スリープ不可)。
> 必要なら「システム設定 > エネルギー/バッテリー」で指定時刻に自動起動を設定してください。

---

## ログ / トラブルシュート

- 実行ログ: `logs/run_YYYYMMDD_HHMMSS.log`、launchd: `logs/launchd.*`
- 各ステップのスクショ/HTML: `logs/page_*.png` / `logs/page_*.html`
- **空き日付なし**: 抽選枠が未公開の時間帯。スケジュール時刻を調整。
- **確認ページに進めない**: 電話番号が無効、または reCAPTCHA 未通過。`logs/page_03*` を確認。
- **SMSコード取得失敗**: フルディスクアクセス未許可、または転送未着。
  `sms_reader.py --since 600` で受信が見えるか確認。`config.toml` の `sms.sender_contains`
  や `code_regex` を調整。
- **reCAPTCHA画像認証が毎回出る**: `--setup-profile` でGoogleログイン/閲覧を増やす。
  `config.toml` の `recaptcha.human_fallback_seconds` を長めに。

## 設定の要点(config.toml)
- `reservation.preferred_dates` / `preferred_weekdays` / `preferred_times` で希望枠の優先順を指定。
- `browser.headless=false` 推奨(reCAPTCHA対策)。
- `recaptcha.human_fallback_seconds` 画像認証時に手動対応を待つ秒数(0で待たない)。
- `sms.poll_seconds` / `lookback_seconds` / `code_regex` / `sender_contains` でSMS取得を調整。
