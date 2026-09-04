"""Ask WeCom one question: can we read messages without a configured callback?

The callback URL cannot be configured at all -- WeCom requires the domain's ICP
filing entity to match the enterprise, and ours is filed to a Malaysian company
on an overseas VPS. Getting a domain that satisfies it costs a mainland server,
a filing, and three to four weeks.

None of that is owed if sync_msg answers without a callback. The callback only
ever announces that something arrived; sync_msg is a pull, with a cursor, over a
three-day window. So this script walks the three calls the channel would make --
token, account list, sync_msg -- and prints which of them WeCom is willing to
answer for an enterprise that has configured no callback at all.

Run it wherever WECOM_CORPID and WECOM_SECRET are set (the VPS container, or a
local shell). It only reads: no message is sent, no setting is changed.

    python scripts/wecom_probe.py

The secret is never printed, and neither is any customer's message text.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

BASE = "https://qyapi.weixin.qq.com/cgi-bin"
TIMEOUT = 15


def _load_env() -> tuple[str, str]:
    """Environment first, then backend/.env, so this runs in or out of the container."""
    corpid = os.environ.get("WECOM_CORPID", "")
    secret = os.environ.get("WECOM_SECRET", "")

    if not (corpid and secret):
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                if name.strip() == "WECOM_CORPID" and not corpid:
                    corpid = value
                elif name.strip() == "WECOM_SECRET" and not secret:
                    secret = value

    if not corpid or not secret:
        sys.exit(
            "WECOM_CORPID and WECOM_SECRET must be set, in the environment or in "
            "backend/.env. Nothing was sent."
        )
    return corpid, secret


def _show(label: str, payload: dict) -> int:
    """Print a response without its secrets, and hand back the errcode."""
    errcode = payload.get("errcode", -1)
    errmsg = payload.get("errmsg", "")
    status = "OK" if errcode == 0 else "FAILED"
    print(f"  {status}  errcode={errcode}  errmsg={errmsg}")
    return errcode


def main() -> int:
    corpid, secret = _load_env()
    print(f"corpid {corpid[:6]}...{corpid[-4:]}  secret hidden\n")

    with httpx.Client(timeout=TIMEOUT) as client:
        # 1. The credential everything else needs. A self-built app's secret is
        #    issued without any callback, so this one is expected to work.
        print("1. gettoken")
        token_body = client.get(
            f"{BASE}/gettoken", params={"corpid": corpid, "corpsecret": secret}
        ).json()
        if _show("gettoken", token_body) != 0:
            print("\nVERDICT: the credentials are wrong or the app is not authorised.")
            print("Check that the self-built app is selected under 微信客服 ->")
            print("API -> Apps that can call APIs, and that the secret is that app's.")
            return 1
        access_token = token_body["access_token"]

        # 2. Which customer-service accounts this app may act for. Also the only
        #    honest way to learn open_kfid without reading it off a web page.
        print("\n2. kf/account/list")
        accounts_body = client.post(
            f"{BASE}/kf/account/list",
            params={"access_token": access_token},
            json={"offset": 0, "limit": 100},
        ).json()
        if _show("account/list", accounts_body) != 0:
            print("\nVERDICT: the app cannot see any 微信客服 account.")
            print("Authorise it under 微信客服 -> API -> Apps that can call APIs")
            print("-> Setting, and tick the account 未来智能科技客服.")
            return 1

        accounts = accounts_body.get("account_list", [])
        print(f"  {len(accounts)} account(s):")
        for account in accounts:
            print(f"    open_kfid={account.get('open_kfid')}  name={account.get('name')}")
        if not accounts:
            print("\nVERDICT: authorised, but no account is assigned to this app yet.")
            return 1

        # 3. The question this script exists to ask. No `token` argument: that is
        #    the one the callback would have supplied, and not having it is
        #    precisely the situation being tested.
        print("\n3. kf/sync_msg  (no cursor, no callback token -- the cold start)")
        sync_body = client.post(
            f"{BASE}/kf/sync_msg",
            params={"access_token": access_token},
            json={"cursor": "", "limit": 100, "open_kfid": accounts[0]["open_kfid"]},
        ).json()
        errcode = _show("sync_msg", sync_body)

        if errcode == 0:
            msg_list = sync_body.get("msg_list", [])
            print(f"  has_more={sync_body.get('has_more')}  msg_list={len(msg_list)} message(s)")
            print(f"  next_cursor present: {bool(sync_body.get('next_cursor'))}")
            print("\nVERDICT: sync_msg answers with no callback configured.")
            print("Polling can replace the callback. The ICP filing, the mainland")
            print("server and the three to four weeks are all unnecessary.")
            print("\nNote: an empty msg_list here is expected and fine -- nobody has")
            print("messaged the account yet. What matters is errcode 0 and a cursor.")
            return 0

        print("\nVERDICT: sync_msg refused. Send this errcode back before buying")
        print("anything -- it decides whether the callback route is actually forced.")
        print(f"\nfull response: {json.dumps(sync_body, ensure_ascii=False)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
