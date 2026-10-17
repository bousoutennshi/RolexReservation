---
name: rolex-reserve
description: ロレックス事前来店予約サイトへ自動応募する(表参道店/銀座並木通り店/新宿店/大阪店/名古屋店)。Playwrightでフォーム自動入力、reCAPTCHAは手動解決、SMS認証コードはMacのメッセージ(chat.db)から自動入力。「ロレックスの予約」「予約を取って」「rolex reserve」等で起動。引数で店舗(omotesando/ginza/shinjuku/osaka/nagoya/all)とモード(--dry-date/--no-submit)を指定可。
---

# ロレックス予約 自動応募スキル

ロレックス各店の「事前来店予約」を自動応募する。実体は `reserve.py`(店舗ごとに config を切替)。

## プロジェクト
- 作業ディレクトリ: `/Users/myokota/git/RolexReservation`
- 実行は必ずこのディレクトリの venv で: `./venv/bin/python reserve.py [...]`

## 店舗と設定ファイル
(希望枠は 2026-08-12 時点。東京3店は火/水/金に分散、地方店との日付重複は許容する方針。)

| 店舗(別名) | config | 希望枠 | その日の全枠 |
|---|---|---|---|
| 表参道店 (omotesando / 表参道) | `config.toml`(既定) | **水曜 13:00** | 11:00 / 13:00 / 15:00 / 17:00 |
| 銀座並木通り店 (ginza / 銀座 / 並木通り) | `config.ginza.toml` | **火曜 13:00** | 11:00 / 13:00 / 15:00 / 17:00 |
| 新宿店 (shinjuku / 新宿) | `config.shinjuku.toml` | 金曜 17:00 | 11:00 / 14:00 / 17:00 |
| 大阪店 (osaka / 大阪 / 梅田) | `config.osaka.toml` | **金曜 13:15 コスモグラフ デイトナ** | 11:00 / 11:15デイトナ / 13:00 / 13:15デイトナ / 15:00 / 15:15デイトナ / 17:00 |
| 名古屋店 (nagoya / 名古屋 / 栄) | `config.nagoya.toml` | **火曜 12:00** | 11:00 / 12:00 / 14:00 / 15:00 / 16:00 |

## 手順
1. **店舗の判定**: ユーザーの引数/指示から対象店舗を決める。`all` または「全部」なら5店すべて。
   指定が無ければ `AskUserQuestion` で店舗(複数選択可)を確認する。
2. **モードの判定**: 既定は本番(実応募)。引数に応じて切替:
   - `--dry-date` … 空き枠の確認のみ(送信なし・reCAPTCHA不要)
   - `--no-submit` … フォーム入力とreCAPTCHAまで確認し確認ボタン直前で停止(送信なし)
   - 指定なし … 本番(**実際に予約応募・取消不可**)
3. **本番/no-submit の場合は実行前に必ず一言伝える**:
   「Chromeウィンドウが開きます。reCAPTCHA画像認証が出たらビープ音+通知が鳴るので、開いたウィンドウで手動解決してください(自動で続行)。本番では最終送信後に携帯へSMSが届き自動入力されます。完了までウィンドウを閉じないでください。」
4. **実行**(Bash, `timeout` は本番/no-submitで 540000ms 程度、dry-dateは 120000ms):
   - 表参道: `./venv/bin/python reserve.py [MODE]`
   - 銀座並木通り: `./venv/bin/python reserve.py --config config.ginza.toml [MODE]`
   - 新宿:  `./venv/bin/python reserve.py --config config.shinjuku.toml [MODE]`
   - 大阪:  `./venv/bin/python reserve.py --config config.osaka.toml [MODE]`
   - 名古屋: `./venv/bin/python reserve.py --config config.nagoya.toml [MODE]`
   - 複数店舗は1店ずつ順番に実行する(プロファイルを共用するため同時実行不可)。
5. **結果の検証と報告**:
   - 本番は `logs/page_07_done.txt`(URLに `/complete/` を含み、希望日時が正しいか)を確認して報告。
   - no-submit は `logs/page_03c_before_submit.txt` で各入力値とreCAPTCHA通過を確認。
   - 失敗時(「reCAPTCHA未通過」「空き日付なし」「確認ページに進めず」等)はログの該当行を引用し原因を伝える。

## 注意
- **本番は実際の予約応募で取消不可**。ユーザーが明示的に本番を望んだときだけ実行する。迷ったら安全テスト(`--no-submit`)か空き確認(`--dry-date`)を提案する。
- reCAPTCHA は毎回画像認証が出る前提。ユーザーの**在席が必須**。
- SMS自動読取には python へのフルディスクアクセス権限が必要(設定済み)。
- 枠の希望条件は各 config の `preferred_weekdays` / `preferred_times` / `time_priority_keywords` で調整する。**変更したら `--dry-date` で実枠を確認してから本番**。
- **デイトナ枠があるのは大阪店だけ**(2026-08-12 時点)。大阪は `time_priority_keywords = ["13:15"]` で 13:15 デイトナ枠を全日付横断で検出し、`preferred_weekdays = ["Fri"]` で金曜に絞る(2026-09-03 に水曜→金曜へ変更。水曜は空き日に出ない回が続いたため)。他4店はモデル名付き枠が無いため `time_priority_keywords = []`(キーワード優先を無効化)にして `preferred_weekdays` + `preferred_times` で選ぶ。
- **銀座本店(`/ginza/reservation`)は 2026/08/23 ご来店分をもって事前来店予約サービスを終了**。以後は**並木通り店(`/namiki/reservation`)**が対象で、`config.ginza.toml` は移行済み。旧URLを叩くと「リクエスト受け付け停止中」ページになる。
- **lexia系(並木通り/新宿/名古屋)は水曜が空き日に出ない**(水曜定休と思われる)。表参道は木曜が出ない。**大阪も水曜が欠ける回がある**(2026-08-22・2026-09-03 と2回連続で水曜が空き日に無く、月曜へフォールバックした。これを受けて大阪は金曜狙いに変更)。希望曜日が空き日に無いと `preferred_weekdays` は効かず**黙って最先の空き日にフォールバック**するので、曜日設定を変えるときは必ず `--dry-date` でその曜日が出るか確認する。
- **大阪店は受け付け時間帯が限られる**。期間外は「リクエスト受け付け停止中」ページが出て `select#first` が無く、スクリプトは次回受け付け開始日時を含むページ文言をログに出して正常終了する(2026-08-12 10:00 に受け付け開始し、以後は正常取得を確認済み)。失敗ではないので、ユーザーには受け付け開始時刻に再実行するよう伝える。
- 大阪店・名古屋店は並木通り/新宿と同じ予約システム(開始URLが `func_distinction=1` を自動POSTして日時選択ページへ)。大阪はドメインのみ別(`rolexboutique-hiltonplaza-osaka.jp`)。
- 空き日付は実行日の約12〜18日後の範囲で1週間ぶん出る(2026-08-12 実行時は 08/24〜08/30)。
