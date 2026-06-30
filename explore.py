"""
サイト構造の探索専用スクリプト。
個人情報の送信・SMS送信は一切行わず、各ステップのページ構造(操作可能な要素)を
ダンプして標準出力に出す。セレクタ設計のための調査用。

使い方:
  ./venv/bin/python explore.py            # 初期ページのみダンプ
  ./venv/bin/python explore.py --start    # 予約タイプ選択して1歩進む
"""
import sys
from playwright.sync_api import sync_playwright

START_URL = "https://reservation.rolexboutique-omotesando-tokyo.jp/omotesando/reservation/distinction/select"

DUMP_JS = r"""
() => {
  const out = [];
  const els = document.querySelectorAll('input, select, textarea, button, a, [role=button], h1, h2, h3, label, legend');
  els.forEach(el => {
    const rect = el.getBoundingClientRect();
    const visible = rect.width > 0 && rect.height > 0 &&
                    getComputedStyle(el).visibility !== 'hidden' &&
                    getComputedStyle(el).display !== 'none';
    if (!visible) return;
    const info = {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      name: el.getAttribute('name') || '',
      id: el.id || '',
      cls: (el.getAttribute('class')||'').slice(0,50),
      placeholder: el.getAttribute('placeholder') || '',
      text: (el.innerText||el.value||'').replace(/\s+/g,' ').trim().slice(0,70),
      href: el.getAttribute('href') || '',
    };
    if (el.tagName.toLowerCase() === 'select') {
      info.options = Array.from(el.options).map(o => ({v:o.value, t:o.text.trim()}));
    }
    out.push(info);
  });
  return {url: location.href, title: document.title, elements: out};
}
"""

def dump(page, label):
    data = page.evaluate(DUMP_JS)
    print(f"\n===== [{label}] URL={data['url']}  TITLE={data['title']} =====")
    for e in data["elements"]:
        line = f"  <{e['tag']}"
        for k in ("type", "name", "id", "placeholder"):
            if e[k]:
                line += f" {k}={e[k]!r}"
        if e["cls"]:
            line += f" class={e['cls']!r}"
        if e["text"]:
            line += f"  TEXT={e['text']!r}"
        if e["href"]:
            line += f"  href={e['href']!r}"
        print(line)
        if e.get("options"):
            for o in e["options"]:
                print(f"        option value={o['v']!r} text={o['t']!r}")
    page.screenshot(path=f"logs/explore_{label}.png", full_page=True)
    with open(f"logs/explore_{label}.html", "w") as f:
        f.write(page.content())

def main():
    advance = "--start" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="ja-JP",
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 1600},
        )
        page = ctx.new_page()
        page.goto(START_URL, wait_until="networkidle", timeout=60000)
        dump(page, "01_start")

        if advance:
            try:
                page.select_option("select#first", "1")  # 事前来店予約
                page.click("button[name='register']")
                page.wait_for_load_state("networkidle", timeout=60000)
                dump(page, "02_after_start")

                # 日付を選ぶ -> 時間selectがAJAXでpopulateされるのを待つ
                date_opts = page.eval_on_selector(
                    "select#first",
                    "el => Array.from(el.options).map(o=>o.value).filter(v=>v)")
                print(f"\n[info] date options: {date_opts}")
                if date_opts:
                    chosen = date_opts[0]
                    print(f"[info] choosing date: {chosen}")
                    page.select_option("select#first", chosen)
                    # #second の option が増えるのを待つ
                    try:
                        page.wait_for_function(
                            "document.querySelector('select#second').options.length > 1",
                            timeout=15000)
                    except Exception:
                        print("[warn] time select did not populate")
                    time_opts = page.eval_on_selector(
                        "select#second",
                        "el => Array.from(el.options).map(o=>({v:o.value,t:o.text})).filter(o=>o.v)")
                    print(f"[info] time options: {time_opts}")
                    if time_opts:
                        page.select_option("select#second", time_opts[0]["v"])
                        page.click("button[name='register']")  # 同意する
                        page.wait_for_load_state("networkidle", timeout=60000)
                        dump(page, "03_after_agree")

                        if "--form" in sys.argv:
                            # ダミーデータで確認ページまで進む(SMSは送らない=最終送信しない)
                            page.fill("#last_name", "予約")
                            page.fill("#first_name", "太郎")
                            page.fill("#last_kananame", "ヨヤク")
                            page.fill("#first_kananame", "タロウ")
                            page.fill("#birthday", "1990-01-01")
                            page.fill("#phone_number", "09000000000")  # ダミー番号
                            page.fill("#email01", "dummy@example.com")
                            page.fill("#email02", "dummy@example.com")
                            page.check("#check01")
                            # check02は任意の可能性。両方試す
                            try:
                                page.check("#check02")
                            except Exception:
                                pass
                            page.click("button[name='confirm']")
                            page.wait_for_load_state("networkidle", timeout=60000)
                            dump(page, "04_confirm_page")
            except Exception as ex:
                print(f"[warn] could not advance: {ex}")

        browser.close()

if __name__ == "__main__":
    main()
