---
name: rolex-reserve
description: ロレックス事前来店予約サイトへ自動応募する(表参道店/銀座店/新宿店)。Playwrightでフォーム自動入力、reCAPTCHAは手動解決、SMS認証コードはMacのメッセージ(chat.db)から自動入力。「ロレックスの予約」「予約を取って」「rolex reserve」等で起動。引数で店舗(omotesando/ginza/shinjuku/all)とモード(--dry-date/--no-submit)を指定可。
---

# ロレックス予約 自動応募スキル

ロレックス各店の「事前来店予約」を自動応募する。実体は `reserve.py`(店舗ごとに config を切替)。

## プロジェクト
- 作業ディレクトリ: `/Users/myokota/git/RolexReservation`
- 実行は必ずこのディレクトリの venv で: `./venv/bin/python reserve.py [...]`

## 店舗と設定ファイル
| 店舗(別名) | config | 希望枠 |
|---|---|---|
| 表参道店 (omotesando / 表参道) | `config.toml`(既定) | 火曜のデイトナ枠 |
| 銀座店 (ginza / 銀座) | `config.ginza.toml` | 水曜のデイトナ枠 |
| 新宿店 (shinjuku / 新宿) | `config.shinjuku.toml` | 金曜 17:00 |

## 手順
1. **店舗の判定**: ユーザーの引数/指示から対象店舗を決める。`all` または「全部」なら3店すべて。
   指定が無ければ `AskUserQuestion` で店舗(複数選択可)を確認する。
2. **モードの判定**: 既定は本番(実応募)。引数に応じて切替:
   - `--dry-date` … 空き枠の確認のみ(送信なし・reCAPTCHA不要)
   - `--no-submit` … フォーム入力とreCAPTCHAまで確認し確認ボタン直前で停止(送信なし)
   - 指定なし … 本番(**実際に予約応募・取消不可**)
3. **本番/no-submit の場合は実行前に必ず一言伝える**:
   「Chromeウィンドウが開きます。reCAPTCHA画像認証が出たらビープ音+通知が鳴るので、開いたウィンドウで手動解決してください(自動で続行)。本番では最終送信後に携帯へSMSが届き自動入力されます。完了までウィンドウを閉じないでください。」
4. **実行**(Bash, `timeout` は本番/no-submitで 540000ms 程度、dry-dateは 120000ms):
   - 表参道: `./venv/bin/python reserve.py [MODE]`
   - 銀座:  `./venv/bin/python reserve.py --config config.ginza.toml [MODE]`
   - 新宿:  `./venv/bin/python reserve.py --config config.shinjuku.toml [MODE]`
   - 複数店舗は1店ずつ順番に実行する。
5. **結果の検証と報告**:
   - 本番は `logs/page_07_done.txt`(URLに `/complete/` を含み、希望日時が正しいか)を確認して報告。
   - no-submit は `logs/page_03c_before_submit.txt` で各入力値とreCAPTCHA通過を確認。
   - 失敗時(「reCAPTCHA未通過」「空き日付なし」「確認ページに進めず」等)はログの該当行を引用し原因を伝える。

## 注意
- **本番は実際の予約応募で取消不可**。ユーザーが明示的に本番を望んだときだけ実行する。迷ったら安全テスト(`--no-submit`)か空き確認(`--dry-date`)を提案する。
- reCAPTCHA は毎回画像認証が出る前提。ユーザーの**在席が必須**。
- SMS自動読取には python へのフルディスクアクセス権限が必要(設定済み)。
- 枠の希望条件は各 config の `preferred_weekdays` / `preferred_times` / `time_priority_keywords` で調整する。
