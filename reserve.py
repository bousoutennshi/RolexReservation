#!/usr/bin/env python3
"""
ロレックス表参道ブティック 事前来店予約 自動応募スクリプト。

フロー:
  ① 予約タイプ選択 → ② 来店日/時間選択 → ③ 顧客情報入力(+reCAPTCHA)
  → ④ 入力内容確認 → ⑤ 最終送信(SMS送信) → ⑥ SMSコード入力 → 完了

実行モード:
  ./venv/bin/python reserve.py --setup-profile  # 初回: ブラウザを開きGoogleログイン等で
                                                #       プロファイルの信頼を育てる(reCAPTCHA対策)
  ./venv/bin/python reserve.py --no-submit      # ③の確認ボタン直前で停止(安全テスト。送信なし)
  ./venv/bin/python reserve.py                  # 本番(最後まで自動。既定 config.toml=表参道店)
  ./venv/bin/python reserve.py --dry-date       # 空き日付/時間だけ表示して終了

店舗の切替(設定ファイル):
  ./venv/bin/python reserve.py --config config.ginza.toml             # 銀座店で本番
  ./venv/bin/python reserve.py --config config.ginza.toml --dry-date  # 銀座店の空き確認
"""
from __future__ import annotations
import os
import re
import sys
import time
import argparse
import datetime
import subprocess
import traceback

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import sms_reader

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, "logs")
# 既定の開始URL(表参道店)。config の [site].start_url で店舗ごとに上書き可能。
DEFAULT_START_URL = ("https://reservation.rolexboutique-omotesando-tokyo.jp/"
                     "omotesando/reservation/distinction/select")
WEEKDAY = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

DUMP_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('input,select,textarea,button,a,[role=button],h1,h2,h3,label,legend,.alert,.error,.invalid-feedback').forEach(el=>{
    const r = el.getBoundingClientRect();
    if (!(r.width>0 && r.height>0)) return;
    const cs = getComputedStyle(el);
    if (cs.visibility==='hidden' || cs.display==='none') return;
    const o = {tag:el.tagName.toLowerCase(), type:el.getAttribute('type')||'',
      name:el.getAttribute('name')||'', id:el.id||'',
      cls:(el.getAttribute('class')||'').slice(0,40),
      ph:el.getAttribute('placeholder')||'',
      text:(el.innerText||el.value||'').replace(/\s+/g,' ').trim().slice(0,70)};
    if (el.tagName.toLowerCase()==='select')
      o.options = Array.from(el.options).map(x=>({v:x.value,t:x.text.trim()}));
    out.push(o);
  });
  return {url:location.href, title:document.title, elements:out};
}
"""

# --------------------------------------------------------------------------- #
# ユーティリティ
# --------------------------------------------------------------------------- #
_LOGFILE = None


def log(msg: str):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if _LOGFILE:
        with open(_LOGFILE, "a") as f:
            f.write(line + "\n")


def notify(title: str, message: str, cfg: dict):
    if not cfg.get("notify", {}).get("macos_notification", True):
        return
    safe = message.replace('"', "'")
    t = title.replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe}" with title "{t}" sound name "Glass"'],
            check=False, capture_output=True)
    except Exception:
        pass


def beep():
    try:
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"],
                       check=False, capture_output=True, timeout=5)
    except Exception:
        pass


def load_config(filename: str = "config.toml") -> dict:
    path = filename if os.path.isabs(filename) else os.path.join(HERE, filename)
    if not os.path.exists(path):
        print(f"{filename} がありません。config.example.toml をコピーして記入してください:\n"
              f"  cp config.example.toml {filename}", file=sys.stderr)
        sys.exit(1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def dump_page(page, label: str):
    try:
        data = page.evaluate(DUMP_JS)
    except Exception as e:
        log(f"[dump] evaluate失敗 {label}: {e}")
        data = {"url": page.url, "title": "", "elements": []}
    txt = [f"===== [{label}] URL={data['url']} TITLE={data['title']} ====="]
    for e in data["elements"]:
        line = f"  <{e['tag']}"
        for k in ("type", "name", "id", "ph"):
            if e.get(k):
                line += f" {k}={e[k]!r}"
        if e.get("cls"):
            line += f" class={e['cls']!r}"
        if e.get("text"):
            line += f"  TEXT={e['text']!r}"
        txt.append(line)
        for op in e.get("options", []):
            txt.append(f"        option {op['v']!r} -> {op['t']!r}")
    body = "\n".join(txt)
    with open(os.path.join(LOGDIR, f"page_{label}.txt"), "w") as f:
        f.write(body + "\n")
    try:
        page.screenshot(path=os.path.join(LOGDIR, f"page_{label}.png"), full_page=True)
        with open(os.path.join(LOGDIR, f"page_{label}.html"), "w") as f:
            f.write(page.content())
    except Exception:
        pass
    log(f"[dump] {label} -> logs/page_{label}.*")
    return data


# --------------------------------------------------------------------------- #
# 選択ロジック
# --------------------------------------------------------------------------- #
def on_datetime_page(page) -> bool:
    """select#first の実オプションが日付なら(=既に来店日選択ページ)True を返す。
    銀座店のように開始URLが予約タイプ選択を飛ばして直接日時ページに来る場合の判定。"""
    try:
        vals = page.eval_on_selector_all(
            "select#first option", "els=>els.map(o=>o.value).filter(v=>v)")
    except Exception:
        return False
    if not vals:
        return False
    try:
        datetime.date.fromisoformat((vals[0] or "")[:10])
        return True
    except ValueError:
        return False


def choose_date(options: list[dict], cfg: dict) -> str | None:
    avail = []
    for o in options:
        ds = (o["v"] or "")[:10]
        try:
            d = datetime.date.fromisoformat(ds)
        except ValueError:
            continue
        avail.append((d, o["v"], o["t"]))
    if not avail:
        return None
    avail.sort()
    res = cfg.get("reservation", {})
    for pd in res.get("preferred_dates", []) or []:
        for d, v, t in avail:
            if d.isoformat() == pd:
                return v
    for wd in res.get("preferred_weekdays", []) or []:
        for d, v, t in avail:
            if WEEKDAY[d.weekday()] == wd:
                return v
    return avail[0][1]


def choose_time(options: list[dict], cfg: dict) -> str | None:
    if not options:
        return None
    for pt in cfg.get("reservation", {}).get("preferred_times", []) or []:
        for o in options:
            if pt in o["t"]:
                return o["v"]
    return options[0]["v"]


def _date_of(v: str):
    try:
        return datetime.date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def load_times(page, dval: str) -> list[dict]:
    """日付を選択し、AJAXで時間枠が populate されるのを待って一覧を返す。"""
    page.select_option("select#first", dval)
    try:
        page.wait_for_function(
            "document.querySelector('select#second').options.length>1",
            timeout=15000)
    except PWTimeout:
        return []
    return page.eval_on_selector_all(
        "select#second option",
        "els=>els.map(o=>({v:o.value,t:o.text.trim()})).filter(o=>o.v)")


def _rank_hits(hits: list[tuple], res: dict) -> tuple:
    """キーワード一致枠の中から、日付優先(日付→曜日→最先)で1件選ぶ。"""
    for pd in res.get("preferred_dates", []) or []:
        for h in hits:
            if h[0] and h[0].isoformat() == pd:
                return h
    for wd in res.get("preferred_weekdays", []) or []:
        for h in sorted(hits, key=lambda x: x[0] or datetime.date.max):
            if h[0] and WEEKDAY[h[0].weekday()] == wd:
                return h
    return sorted(hits, key=lambda x: x[0] or datetime.date.max)[0]


def pick_slot(page, date_opts: list[dict], cfg: dict,
              scan_keywords: list[str]) -> tuple:
    """(dval, dtext, tval, ttext) を返す。
    scan_keywords(例: デイトナ)を全日付横断で最優先検索し、無ければ通常の優先順。"""
    res = cfg.get("reservation", {})
    if scan_keywords:
        hits = []  # (date, dval, dtext, tval, ttext)
        for o in date_opts:
            for t in load_times(page, o["v"]):
                if any(kw in t["t"] for kw in scan_keywords):
                    hits.append((_date_of(o["v"]), o["v"], o["t"], t["v"], t["t"]))
        if hits:
            log(f"優先キーワード一致枠: {[(h[2], h[4]) for h in hits]}")
            h = _rank_hits(hits, res)
            return h[1], h[2], h[3], h[4]
        log(f"優先キーワード({scan_keywords})の枠なし。通常選択にフォールバック。")
    dval = choose_date(date_opts, cfg)
    dtext = next((o["t"] for o in date_opts if o["v"] == dval), dval)
    times = load_times(page, dval)
    if not times:
        return dval, dtext, None, None
    tval = choose_time(times, cfg)
    ttext = next((t["t"] for t in times if t["v"] == tval), tval)
    return dval, dtext, tval, ttext


# --------------------------------------------------------------------------- #
# reCAPTCHA
# --------------------------------------------------------------------------- #
def recaptcha_token(page) -> bool:
    try:
        v = page.eval_on_selector("#g-recaptcha-response", "el => el.value")
        return bool(v)
    except Exception:
        return False


def challenge_visible(page) -> bool:
    try:
        return page.evaluate(
            """() => {
              const f = [...document.querySelectorAll('iframe')]
                .find(f => /recaptcha/.test(f.src) && /bframe/.test(f.src));
              if (!f) return false;
              const r = f.getBoundingClientRect();
              const cs = getComputedStyle(f);
              return r.width>10 && r.height>10 && cs.visibility!=='hidden' && cs.opacity!=='0';
            }""")
    except Exception:
        return False


def solve_recaptcha(page, cfg: dict) -> bool:
    if recaptcha_token(page):
        log("reCAPTCHA: 既にトークンあり")
        return True
    try:
        fl = page.frame_locator("iframe[src*='recaptcha'][src*='anchor']")
        box = fl.locator("#recaptcha-anchor")
        box.wait_for(state="visible", timeout=15000)
        box.click()
        log("reCAPTCHA: チェックボックスをクリック")
    except Exception as e:
        log(f"reCAPTCHA: チェックボックス操作失敗: {e}")

    # 即時通過 or チャレンジ出現を待つ
    deadline = time.time() + 8
    while time.time() < deadline:
        if recaptcha_token(page):
            log("reCAPTCHA: 即時通過(トークン取得)")
            return True
        if challenge_visible(page):
            break
        time.sleep(0.5)
    if recaptcha_token(page):
        return True

    secs = int(cfg.get("recaptcha", {}).get("human_fallback_seconds", 0) or 0)
    if challenge_visible(page) and secs > 0:
        log(f"reCAPTCHA: 画像チャレンジ検出。人手解決を最大{secs}秒待機します")
        notify("reCAPTCHA 要対応", "画像認証を解いてください(自動で続行します)", cfg)
        beep()
        dl = time.time() + secs
        while time.time() < dl:
            if recaptcha_token(page):
                log("reCAPTCHA: 人手で解決→トークン取得")
                return True
            time.sleep(1.5)
        log("reCAPTCHA: 人手解決の待機がタイムアウト")
    elif secs <= 0:
        log("reCAPTCHA: 自動通過できず、human_fallback_seconds=0 のため中止")
    return recaptcha_token(page)


# --------------------------------------------------------------------------- #
# SMSコード入力欄の探索
# --------------------------------------------------------------------------- #
def fill_sms_code(page, code: str) -> bool:
    candidates = [
        "input[name*='code' i]", "input[id*='code' i]",
        "input[name*='auth' i]", "input[name*='sms' i]",
        "input[name*='pin' i]", "input[name*='otp' i]",
        "input[name*='verify' i]", "input[name*='token' i]",
        "input[type='tel']", "input[type='number']", "input[type='text']",
    ]
    for sel in candidates:
        loc = page.locator(sel)
        n = loc.count()
        for i in range(n):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    el.fill(code)
                    log(f"SMSコード入力: selector={sel} に {code} を入力")
                    return True
            except Exception:
                continue
    return False


def click_submit_like(page, names=("register", "confirm", "send", "submit")) -> bool:
    for nm in names:
        loc = page.locator(f"button[name='{nm}']")
        if loc.count() and loc.first.is_visible():
            loc.first.click()
            log(f"送信ボタンclick: name={nm}")
            return True
    loc = page.locator("button[type='submit'], input[type='submit']")
    if loc.count() and loc.first.is_visible():
        loc.first.click()
        log("送信ボタンclick: 先頭のsubmit")
        return True
    return False


# --------------------------------------------------------------------------- #
# メインフロー
# --------------------------------------------------------------------------- #
def run(cfg: dict, args):
    b = cfg.get("browser", {})
    profile_dir = os.path.expanduser(b.get("profile_dir", "~/.rolex_reservation_profile"))
    os.makedirs(profile_dir, exist_ok=True)
    channel = b.get("channel", "chrome")
    headless = bool(b.get("headless", False)) and not args.setup_profile
    slow_mo = int(b.get("slow_mo_ms", 60))

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=profile_dir,
            headless=headless,
            slow_mo=slow_mo,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        if channel:
            launch_kwargs["channel"] = channel
        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        # navigator.webdriver を隠す
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30000)

        try:
            if args.setup_profile:
                log("プロファイル準備モード: Googleにログインし、数分間ブラウジングして信頼を育ててください。")
                page.goto("https://accounts.google.com/", wait_until="domcontentloaded")
                input("準備が終わったらこのターミナルでEnterを押してください...")
                return

            # ---- ① 予約タイプ ----
            site = cfg.get("site", {})
            site_name = site.get("name", "")
            start_url = site.get("start_url") or DEFAULT_START_URL
            log(f"開始: {(site_name + ' ') if site_name else ''}{start_url}")
            page.goto(start_url, wait_until="networkidle")
            dump_page(page, "01_start")
            # 開始URLが既に日時選択ページ(銀座店等)なら予約タイプ選択はスキップ
            if on_datetime_page(page):
                log("開始URLが日時選択ページのため、予約タイプ選択をスキップします")
            else:
                page.select_option("select#first", cfg["reservation"]["distinction"])
                page.click("button[name='register']")
                page.wait_for_load_state("networkidle")
                log("予約タイプを選択しました")

            # ---- ② 来店日/時間(デイトナ等を全日付横断で最優先) ----
            dump_page(page, "02_datetime")
            date_opts = page.eval_on_selector_all(
                "select#first option",
                "els=>els.map(o=>({v:o.value,t:o.text.trim()})).filter(o=>o.v)")
            if not date_opts:
                log("空き日付がありません。抽選枠が未公開の可能性。終了します。")
                notify("ロレックス予約", "空き日付なし(枠未公開?)", cfg)
                return
            log(f"空き日付: {[o['t'] for o in date_opts]}")
            scan_keywords = cfg.get("reservation", {}).get(
                "time_priority_keywords", ["デイトナ", "Daytona"])

            if args.dry_date:
                for o in date_opts:
                    times = load_times(page, o["v"])
                    star = " ★優先一致" if any(
                        any(kw in t["t"] for kw in scan_keywords) for t in times) else ""
                    log(f"{o['t']}{star}: {[t['t'] for t in times]}")
                return

            dval, dtext, tval, ttext = pick_slot(page, date_opts, cfg, scan_keywords)
            if not tval:
                log("時間枠が取得できませんでした。終了します。")
                notify("ロレックス予約", "時間枠なし", cfg)
                return
            log(f"選択する枠: 日付={dtext} 時間={ttext}")
            # scan後はselectが別日付の可能性があるため、確実に選び直す
            page.select_option("select#first", dval)
            page.wait_for_function(
                "v => Array.from(document.querySelectorAll('select#second option'))"
                ".some(o=>o.value===v)",
                arg=tval, timeout=15000)
            page.select_option("select#second", tval)
            page.click("button[name='register']")  # 同意する
            page.wait_for_load_state("networkidle")

            # ---- ③ 顧客情報入力 ----
            dump_page(page, "03_form")
            per = cfg["personal"]
            page.fill("#last_name", per["last_name"])
            page.fill("#first_name", per["first_name"])
            page.fill("#last_kananame", per["last_kananame"])
            page.fill("#first_kananame", per["first_kananame"])
            page.fill("#birthday", per["birthday"])
            page.fill("#phone_number", per["phone_number"])
            page.fill("#email01", per["email"])
            page.fill("#email02", per["email"])
            if not page.is_checked("#check01"):
                page.check("#check01")
            if cfg["reservation"].get("agree_marketing"):
                try:
                    page.check("#check02")
                except Exception:
                    pass
            log("顧客情報を入力しました")

            # reCAPTCHA
            if not solve_recaptcha(page, cfg):
                dump_page(page, "03b_recaptcha_failed")
                log("reCAPTCHAを通過できませんでした。中止します。")
                notify("ロレックス予約 失敗", "reCAPTCHA未通過", cfg)
                return

            if args.no_submit:
                dump_page(page, "03c_before_submit")
                log("--no-submit: 確認ボタン直前で停止しました(送信なし)。")
                return

            page.click("button[name='confirm']")  # 入力内容確認
            page.wait_for_load_state("networkidle")

            # ---- ④ 入力内容確認ページ ----
            confirm = dump_page(page, "04_confirm")
            # バリデーション差し戻し検知(入力ページに留まっていないか)
            if "/register/" in page.url:
                log("確認に進めず入力ページに留まりました。入力/電話/reCAPTCHAを確認してください。")
                notify("ロレックス予約 失敗", "確認ページに進めず", cfg)
                return

            # ---- ⑤ 最終送信(ここでSMSが飛ぶ想定) ----
            trigger_unix = time.time()
            if not click_submit_like(page, names=("register", "confirm", "send", "submit")):
                log("最終送信ボタンが見つかりません。logs/page_04_confirm.* を確認してください。")
                notify("ロレックス予約 失敗", "最終送信ボタン不明", cfg)
                return
            page.wait_for_load_state("networkidle")
            dump_page(page, "05_after_final_submit")

            # ---- ⑥ SMSコード入力 ----
            sms = cfg.get("sms", {})
            log("SMS到着を待機します…")
            code = sms_reader.wait_for_code(
                trigger_unix,
                code_regex=sms.get("code_regex", r"(\d{4,8})"),
                sender_contains=sms.get("sender_contains", ""),
                lookback_seconds=int(sms.get("lookback_seconds", 90)),
                poll_seconds=int(sms.get("poll_seconds", 150)),
            )
            if not code:
                log("SMSコードを取得できませんでした(到着遅延/抽出失敗)。")
                notify("ロレックス予約 失敗", "SMSコード取得失敗", cfg)
                dump_page(page, "06_sms_page_nocode")
                return
            log(f"SMSコード取得: {code}")
            if not fill_sms_code(page, code):
                log("SMSコード入力欄が見つかりません。logs/page_06_*.* を確認してください。")
                dump_page(page, "06_sms_page_noinput")
                notify("ロレックス予約 失敗", "SMS入力欄不明", cfg)
                return
            dump_page(page, "06_sms_filled")
            if not click_submit_like(page, names=("register", "confirm", "verify", "send", "submit")):
                log("SMS送信ボタンが見つかりません。")
                notify("ロレックス予約 失敗", "SMS送信ボタン不明", cfg)
                return
            page.wait_for_load_state("networkidle")

            # ---- 完了判定 ----
            final = dump_page(page, "07_done")
            body_text = page.inner_text("body")[:2000]
            ok_words = ("完了", "受付", "ありがとう", "complete", "thank", "受け付け")
            if any(w in body_text for w in ok_words):
                log(f"予約応募が完了したようです 🎉 {site_name}".rstrip())
                suffix = f"({site_name})" if site_name else ""
                notify(f"ロレックス予約 完了{suffix}", f"{dtext} {ttext} で応募完了", cfg)
            else:
                log("完了文言を検出できませんでした。logs/page_07_done.* を確認してください。")
                notify("ロレックス予約 要確認", "完了判定できず", cfg)

        except Exception as e:
            log("例外発生:\n" + traceback.format_exc())
            try:
                dump_page(page, "99_error")
            except Exception:
                pass
            notify("ロレックス予約 エラー", str(e)[:120], cfg)
        finally:
            if not args.keep_open:
                ctx.close()
            else:
                log("--keep-open: ブラウザを開いたままにします。Enterで閉じます。")
                input()
                ctx.close()


def main():
    global _LOGFILE
    os.makedirs(LOGDIR, exist_ok=True)
    _LOGFILE = os.path.join(LOGDIR, f"run_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml",
                    help="使用する設定ファイル(店舗ごとに切替: 例 config.ginza.toml)")
    ap.add_argument("--setup-profile", action="store_true",
                    help="ブラウザを開きGoogleログイン等でプロファイルを育てる")
    ap.add_argument("--no-submit", action="store_true",
                    help="確認ボタン直前で停止(送信・SMSなしの安全テスト)")
    ap.add_argument("--dry-date", action="store_true",
                    help="空き日付/時間を表示するだけで終了")
    ap.add_argument("--keep-open", action="store_true",
                    help="終了後もブラウザを開いたままにする(デバッグ用)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    log(f"ログ: {_LOGFILE}(config={args.config})")
    run(cfg, args)


if __name__ == "__main__":
    main()
