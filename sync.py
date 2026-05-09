import time
import requests
import urllib3
import json
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
NODE_API_URL = "http://localhost:3000/api"

def sync_data():
    print("\n[*] Starting API Sync...")
    
    try:
        db_res = requests.get(f"{NODE_API_URL}/sync-data", timeout=10)
        db = db_res.json()
    except Exception as e:
        return print(f"[-] Cannot connect to Node.js Server: {e}")

    configs = db.get("admin_config", {}).get("server_api", {})
    if not configs: return print("[-] Server Configs missing!")

    outline_url = configs.get("outline_url")
    xui_url, xui_user, xui_pass = configs.get("xui_url"), configs.get("xui_user"), configs.get("xui_pass")
    today = datetime.now().date()

    outline_keys_map = {}
    outline_usage = {}
    if outline_url:
        try:
            res_usage = requests.get(f"{outline_url}/metrics/transfer", verify=False, timeout=10)
            outline_usage = res_usage.json().get('bytesTransferredByUserId', {})
            res_keys = requests.get(f"{outline_url}/access-keys", verify=False, timeout=10)
            for k in res_keys.json().get('accessKeys', []):
                outline_keys_map[k['accessUrl']] = k
        except: pass

    xui_clients_map = {}
    xui_session = requests.Session()
    if xui_url and xui_user:
        try:
            xui_session.post(f"{xui_url}/login", data={'username': xui_user, 'password': xui_pass}, timeout=10)
            res_inb = xui_session.get(f"{xui_url}/panel/api/inbounds", timeout=10)
            for inbound in res_inb.json().get('obj', []):
                inb_id = inbound['id']
                settings = json.loads(inbound.get('settings', '{}'))
                for c in settings.get('clients', []):
                    xui_clients_map[c['email']] = (inb_id, c)
        except: pass

    users = db.get("users", {})
    update_fields = {}

    for user_id, user_data in users.items():
        user_updates = {}

        # Outline
        out_key_url = user_data.get('outlineKey', '')
        if out_key_url in outline_keys_map:
            out_client = outline_keys_map[out_key_url]
            out_id = out_client['id']
            used_bytes = outline_usage.get(out_id, 0)
            user_updates['outlineUsedGB'] = round(used_bytes / (1024**3), 3)

            target_limit_gb = float(user_data.get('outlineTotalGB', 0))
            is_expired = False
            if user_data.get('outlineExpireDate'):
                try:
                    exp_date = datetime.strptime(user_data.get('outlineExpireDate'), "%Y-%m-%d").date()
                    if today > exp_date: is_expired = True
                except: pass

            target_limit_bytes = int(target_limit_gb * (1024**3))
            current_limit_bytes = out_client.get('dataLimit', {}).get('bytes')

            if is_expired or (target_limit_gb > 0 and used_bytes >= target_limit_bytes):
                if current_limit_bytes != 0:
                    requests.put(f"{outline_url}/access-keys/{out_id}/data-limit", json={"limit": {"bytes": 0}}, verify=False)
                    print(f"   [🚫] Outline {user_id} Auto-Suspended.")
            else:
                if target_limit_gb > 0 and current_limit_bytes != target_limit_bytes:
                    requests.put(f"{outline_url}/access-keys/{out_id}/data-limit", json={"limit": {"bytes": target_limit_bytes}}, verify=False)
                elif target_limit_gb == 0 and current_limit_bytes is not None:
                    requests.delete(f"{outline_url}/access-keys/{out_id}/data-limit", verify=False)

        # Vless
        if user_id in xui_clients_map:
            inb_id, c_dict = xui_clients_map[user_id]
            changed = False
            try:
                res_stats = xui_session.get(f"{xui_url}/panel/api/inbounds/getClientTraffics/{c_dict['email']}")
                stats = res_stats.json().get('obj', {})
                vless_used = (stats.get('up', 0) + stats.get('down', 0)) / (1024**3)
                user_updates['vlessUsedGB'] = round(vless_used, 3)
            except: pass

            target_vless_gb = int(float(user_data.get('vlessTotalGB', 0)) * (1024**3))
            if c_dict.get('totalGB') != target_vless_gb:
                c_dict['totalGB'] = target_vless_gb
                changed = True

            target_vless_exp = 0
            if user_data.get('vlessExpireDate'):
                exp_date = datetime.strptime(user_data.get('vlessExpireDate'), "%Y-%m-%d")
                target_vless_exp = int(exp_date.timestamp() * 1000)

            if c_dict.get('expiryTime') != target_vless_exp:
                c_dict['expiryTime'] = target_vless_exp
                changed = True

            if changed:
                payload = {"id": inb_id, "settings": json.dumps({"clients": [c_dict]})}
                xui_session.post(f"{xui_url}/panel/api/inbounds/updateClient/{c_dict['id']}", data=payload)
                print(f"   [✅] VLESS API Updated for {user_id}")

        if user_updates:
            update_fields[user_id] = user_updates

    if update_fields:
        requests.post(f"{NODE_API_URL}/sync-update", json={"update_fields": update_fields})

    print("[*] Sync Complete.")

if __name__ == "__main__":
    while True:
        sync_data()
        time.sleep(30)
