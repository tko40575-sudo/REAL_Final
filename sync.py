import time
import requests
import urllib3
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("[+] Firebase connected successfully.")
except Exception as e:
    print(f"[-] Firebase Connection Error: {e}")
    exit(1)

def get_server_configs():
    try:
        # Admin Panel မှ ပြောင်းလဲထားသော API Settings များကို ချက်ချင်းယူပါမည်
        doc = db.collection("admin_config").document("server_api").get()
        if doc.exists: return doc.to_dict()
    except Exception as e:
        print(f"[-] Error fetching configs: {e}")
    return None

def get_outline_usage(api_url):
    if not api_url: return {}
    try:
        res = requests.get(f"{api_url}/metrics/transfer", verify=False, timeout=10)
        return res.json().get('bytesTransferredByUserId', {})
    except Exception as e: return {}

def suspend_outline_user(api_url, outline_id):
    try:
        url = f"{api_url}/access-keys/{outline_id}/data-limit"
        requests.put(url, json={"limit": {"bytes": 0}}, verify=False, timeout=10)
        print(f"   [🚫] Outline User {outline_id} Suspended Successfully.")
    except Exception as e:
        print(f"   [-] Outline Suspend Error: {e}")

def suspend_xui_user(xui_url, session, email):
    try:
        res = session.get(f"{xui_url}/panel/api/inbounds", timeout=10)
        inbounds = res.json().get('obj', [])
        
        for inbound in inbounds:
            inbound_id = inbound.get('id')
            settings = json.loads(inbound.get('settings', '{}'))
            clients = settings.get('clients', [])
            
            for client in clients:
                if client.get('email') == email and client.get('enable', True) == True:
                    client_uuid = client.get('id')
                    suspend_url = f"{xui_url}/panel/api/inbounds/updateClient/{client_uuid}"
                    client['enable'] = False 
                    
                    payload = {
                        "id": inbound_id,
                        "settings": json.dumps({"clients": [client]})
                    }
                    update_res = session.post(suspend_url, data=payload, timeout=10)
                    if update_res.status_code == 200:
                        print(f"   [🚫] VLESS User {email} Suspended Successfully.")
                    return
    except Exception as e:
        print(f"   [-] X-UI Suspend Error: {e}")

def get_xui_usage_and_session(configs):
    xui_url, xui_user, xui_pass = configs.get("xui_url"), configs.get("xui_user"), configs.get("xui_pass")
    if not xui_url or not xui_user: return {}, None
    try:
        session = requests.Session()
        session.post(f"{xui_url}/login", data={'username': xui_user, 'password': xui_pass}, timeout=10)
        
        res = session.get(f"{xui_url}/panel/api/inbounds", timeout=10)
        inbounds = res.json().get('obj', [])
        
        xui_usage = {}
        for inbound in inbounds:
            client_stats = inbound.get('clientStats', [])
            for client in client_stats:
                email = client.get('email', '')
                xui_usage[email] = client.get('up', 0) + client.get('down', 0)
        return xui_usage, session
    except Exception as e:
        return {}, None

def sync_data():
    print("\n[*] Starting sync & security check...")
    configs = get_server_configs()
    if not configs: return print("[-] Server Configs missing!")

    outline_data = get_outline_usage(configs.get("outline_url"))
    xui_data, xui_session = get_xui_usage_and_session(configs)
    
    users_ref = db.collection('users')
    docs = users_ref.stream()

    today = datetime.now().date()

    for doc in docs:
        user_id = doc.id 
        user_data = doc.to_dict()
        update_fields = {}
        
        # 1. OUTLINE SYNC
        outline_id = user_data.get('outlineId', user_id)
        out_used_gb = user_data.get('outlineUsedGB', 0)
        out_total_gb = float(user_data.get('outlineTotalGB', 0))
        out_expire = user_data.get('outlineExpireDate', '')
        out_status = user_data.get('outlineStatus', 'Active')

        if outline_id in outline_data:
            out_used_gb = outline_data[outline_id] / (1024 ** 3)
            update_fields['outlineUsedGB'] = round(out_used_gb, 3)

        out_is_expired = False
        if out_expire:
            try:
                exp_date = datetime.strptime(out_expire, "%Y-%m-%d").date()
                if today > exp_date: out_is_expired = True
            except: pass

        if out_status != 'Suspended':
            if (out_total_gb > 0 and out_used_gb >= out_total_gb) or out_is_expired:
                print(f"[!] Outline Auto-Suspend Triggered for {user_id}")
                suspend_outline_user(configs.get("outline_url"), outline_id)
                update_fields['outlineStatus'] = 'Suspended'

        # 2. VLESS SYNC
        vless_used_gb = user_data.get('vlessUsedGB', 0)
        vless_total_gb = float(user_data.get('vlessTotalGB', 0))
        vless_expire = user_data.get('vlessExpireDate', '')
        vless_status = user_data.get('vlessStatus', 'Active')

        if user_id in xui_data:
            vless_used_gb = xui_data[user_id] / (1024 ** 3)
            update_fields['vlessUsedGB'] = round(vless_used_gb, 3)

        vless_is_expired = False
        if vless_expire:
            try:
                exp_date = datetime.strptime(vless_expire, "%Y-%m-%d").date()
                if today > exp_date: vless_is_expired = True
            except: pass

        if vless_status != 'Suspended' and xui_session:
            if (vless_total_gb > 0 and vless_used_gb >= vless_total_gb) or vless_is_expired:
                print(f"[!] VLESS Auto-Suspend Triggered for {user_id}")
                suspend_xui_user(configs.get("xui_url"), xui_session, user_id)
                update_fields['vlessStatus'] = 'Suspended'

        if update_fields:
            users_ref.document(user_id).update(update_fields)
            print(f"[+] Synced User {user_id}")

    print("[*] Sync cycle complete.")

if __name__ == "__main__":
    print("🚀 Private Secure Auto-Sync & AI Suspend Bot Started!")
    while True:
        sync_data()
        time.sleep(60)
