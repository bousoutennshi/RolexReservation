"""
macOS の メッセージ.app データベース(chat.db)から、最近受信したSMSの
認証コードを読み取るモジュール。

前提:
  - iPhoneの「テキストメッセージ転送」を有効化し、SMSがこのMacのメッセージ.appに届くこと。
  - このスクリプトを実行するプロセス(python)に「フルディスクアクセス」権限があること。
    (システム設定 > プライバシーとセキュリティ > フルディスクアクセス)

単体テスト:
  ./venv/bin/python sms_reader.py --since 600        # 直近600秒の受信SMSとコード候補を表示
  ./venv/bin/python sms_reader.py --wait 60          # 今から到着するSMSを最大60秒待って表示
"""
from __future__ import annotations
import os
import re
import sys
import time
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass

CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
# Apple Cocoa epoch (2001-01-01) と Unix epoch の差(秒)
COCOA_EPOCH = 978307200


class FullDiskAccessError(RuntimeError):
    """chat.db を開けない(フルディスクアクセス未許可)場合に送出。"""


@dataclass
class SmsMessage:
    rowid: int
    unixtime: float
    sender: str
    body: str

    def find_code(self, pattern: str) -> str | None:
        m = re.search(pattern, self.body)
        return m.group(1) if m else None


def _copy_db_snapshot() -> str:
    """chat.db と WAL/SHM を一時ディレクトリにコピーし、コピー先パスを返す。
    Messages が書き込み中でもロックを避けて最新状態を読むため。"""
    tmpdir = tempfile.mkdtemp(prefix="rolex_chatdb_")
    dst = os.path.join(tmpdir, "chat.db")
    try:
        shutil.copy2(CHAT_DB, dst)
        for ext in ("-wal", "-shm"):
            src = CHAT_DB + ext
            if os.path.exists(src):
                shutil.copy2(src, dst + ext)
    except PermissionError as e:
        raise FullDiskAccessError(
            "chat.db を読み取れません(フルディスクアクセス未許可)。\n"
            "システム設定 > プライバシーとセキュリティ > フルディスクアクセス で\n"
            "実行プロセス(python3 / ターミナル / launchd)を許可してください。\n"
            f"対象DB: {CHAT_DB}"
        ) from e
    return dst


def _extract_text(text, attributed_body) -> str:
    """text を優先。NULLなら attributedBody(BLOB)から可読文字列を抽出。"""
    if text:
        return text
    if not attributed_body:
        return ""
    # attributedBody は typedstream/NSKeyedArchiver。完全パースはせず
    # 可読UTF-8断片を拾い、その中からSMS本文らしき部分を返す。
    raw = bytes(attributed_body)
    try:
        decoded = raw.decode("utf-8", errors="ignore")
    except Exception:
        decoded = raw.decode("latin-1", errors="ignore")
    # 制御文字を空白へ、連続空白を圧縮
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", decoded)
    return cleaned.strip()


def get_recent_messages(since_unix: float,
                        sender_contains: str = "") -> list[SmsMessage]:
    """since_unix 以降に受信した(is_from_me=0)メッセージを新しい順で返す。"""
    if not os.path.exists(CHAT_DB):
        raise FullDiskAccessError(f"chat.db が見つかりません: {CHAT_DB}")

    snapshot = _copy_db_snapshot()
    try:
        uri = f"file:{snapshot}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError as e:
            raise FullDiskAccessError(f"chat.db を開けません: {e}") from e
        try:
            cur = conn.cursor()
            # date は 2001-01-01 起点のナノ秒(古いmacOSでは秒)。
            # 桁数で判定して unix 秒へ変換する。
            cur.execute(
                """
                SELECT m.ROWID,
                       m.date,
                       m.text,
                       m.attributedBody,
                       COALESCE(h.id, '') AS sender,
                       m.is_from_me
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                ORDER BY m.date DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    finally:
        shutil.rmtree(os.path.dirname(snapshot), ignore_errors=True)

    out: list[SmsMessage] = []
    for rowid, date_raw, text, abody, sender, is_from_me in rows:
        if is_from_me:
            continue
        # ナノ秒(19桁前後) or 秒(10桁前後)を吸収
        if date_raw and date_raw > 1_000_000_000_000:  # ns
            unixtime = date_raw / 1_000_000_000 + COCOA_EPOCH
        else:
            unixtime = (date_raw or 0) + COCOA_EPOCH
        if unixtime < since_unix:
            continue
        if sender_contains and sender_contains.lower() not in sender.lower():
            continue
        body = _extract_text(text, abody)
        out.append(SmsMessage(rowid=rowid, unixtime=unixtime,
                              sender=sender, body=body))
    out.sort(key=lambda m: m.unixtime, reverse=True)
    return out


def wait_for_code(trigger_unix: float,
                  code_regex: str = r"(\d{4,8})",
                  sender_contains: str = "",
                  lookback_seconds: int = 90,
                  poll_seconds: int = 150,
                  poll_interval: float = 3.0) -> str | None:
    """trigger_unix(SMS送信ボタンを押した時刻)以降に届くSMSを待ち、
    最初に見つかった認証コードを返す。タイムアウトで None。"""
    since = trigger_unix - lookback_seconds
    deadline = trigger_unix + poll_seconds
    seen: set[int] = set()
    while time.time() < deadline:
        try:
            msgs = get_recent_messages(since, sender_contains)
        except FullDiskAccessError:
            raise
        for m in msgs:
            if m.rowid in seen:
                continue
            seen.add(m.rowid)
            code = m.find_code(code_regex)
            if code:
                return code
        time.sleep(poll_interval)
    return None


def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, help="直近N秒の受信SMSを表示")
    ap.add_argument("--wait", type=int, help="今からN秒間、到着SMSを待って表示")
    ap.add_argument("--regex", default=r"(\d{4,8})")
    ap.add_argument("--sender", default="")
    args = ap.parse_args()

    try:
        if args.wait is not None:
            now = time.time()
            print(f"[*] {args.wait}秒間、新着SMSを待機します… 携帯にコードを送ってテストしてください")
            code = wait_for_code(now, args.regex, args.sender,
                                 lookback_seconds=5, poll_seconds=args.wait)
            print(f"[=] 抽出コード: {code}")
        else:
            since = time.time() - (args.since or 600)
            msgs = get_recent_messages(since, args.sender)
            if not msgs:
                print("[i] 該当期間に受信SMSはありません(または転送未着)。")
            for m in msgs:
                code = m.find_code(args.regex)
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m.unixtime))
                print(f"[{ts}] from={m.sender!r} code={code!r}\n    body={m.body[:80]!r}")
    except FullDiskAccessError as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _cli()
