import time
import requests
import urllib3
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# SSL Warning ပိတ်ထားရန်
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# Firebase ချိတ်ဆက်ခြင်း
# ==========================================
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("[+] Firebase connected successfully.")
except Exception as e:
    print(f"[-] Firebase Connection Error: {e}")
    exit(1)

def get_server_configs():
    doc = db.collection("admin_config").document("server_api").get()
    return doc.to_dict() if doc.exists else None

def sync_data():
    print("\n[*] Starting Real-time API Sync & Check...")
    configs = get_server_configs()
    if not configs: return print("[-] Server Configs missing!")

    outline_url = configs.get("outline_url")
    xui_url, xui_user, xui_pass = configs.get("xui_url"), configs.get("xui_user"), configs.get("xui_pass")
    today = datetime.now().date()

    # 1. OUTLINE API ကနေ Data တွေ ယူမယ်
    outline_keys_map = {}
    outline_usage = {}
    if outline_url:
        try:
            # Get Usage
            res_usage = requests.get(f"{outline_url}/metrics/transfer", verify=False, timeout=10)
            outline_usage = res_usage.json().get('bytesTransferredByUserId', {})
            # Get Keys info to map AccessURL to Outline ID
            res_keys = requests.get(f"{outline_url}/access-keys", verify=False, timeout=10)
            for k in res_keys.json().get('accessKeys', []):
                outline_keys_map[k['accessUrl']] = k
        except Exception as e:
            print(f"[-] Outline API Error: {e}")

    # 2. VLESS (X-UI) API ကနေ Data တွေ ယူမယ်
    xui_clients_map = {} # email -> (inbound_id, client_dict)
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
        except Exception as e:
            print(f"[-] X-UI API Error: {e}")

    # 3. Firebase ထဲက User တွေကို စစ်ပြီး Server နဲ့ အပြန်အလှန် Sync လုပ်မယ်
    users_ref = db.collection('users')
    for doc in users_ref.stream():
        user_id = doc.id 
        user_data = doc.to_dict()
        update_fields = {}

        # ==========================================
        # [A] OUTLINE 2-WAY SYNC
        # ==========================================
        out_key_url = user_data.get('outlineKey', '')
        if out_key_url in outline_keys_map:
            out_client = outline_keys_map[out_key_url]
            out_id = out_client['id']
            
            # Fetch Usage
            used_bytes = outline_usage.get(out_id, 0)
            update_fields['outlineUsedGB'] = round(used_bytes / (1024**3), 3)

            # Check Total Limit & Expiry
            target_limit_gb = float(user_data.get('outlineTotalGB', 0))
            is_expired = False
            if user_data.get('outlineExpireDate'):
                try:
                    exp_date = datetime.strptime(user_data.get('outlineExpireDate'), "%Y-%m-%d").date()
                    if today > exp_date: is_expired = True
                except: pass

            # Update Outline API limits directly if changed from Admin Panel
            target_limit_bytes = int(target_limit_gb * (1024**3))
            current_limit_bytes = out_client.get('dataLimit', {}).get('bytes')

            if is_expired or (target_limit_gb > 0 and used_bytes >= target_limit_bytes):
                # Auto Suspend by setting limit to 0
                if current_limit_bytes != 0:
                    requests.put(f"{outline_url}/access-keys/{out_id}/data-limit", json={"limit": {"bytes": 0}}, verify=False)
                    print(f"   [🚫] Outline User {user_id} Auto-Suspended.")
            else:
                if target_limit_gb > 0 and current_limit_bytes != target_limit_bytes:
                    # Sync new Limit to Outline Server
                    requests.put(f"{outline_url}/access-keys/{out_id}/data-limit", json={"limit": {"bytes": target_limit_bytes}}, verify=False)
                    print(f"   [✅] Outline API Updated (Limit: {target_limit_gb}GB) for {user_id}")
                elif target_limit_gb == 0 and current_limit_bytes is not None:
                    # 0 means Unlimited, remove limit
                    requests.delete(f"{outline_url}/access-keys/{out_id}/data-limit", verify=False)
                    print(f"   [✅] Outline API Updated (Unlimited) for {user_id}")

        # ==========================================
        # [B] VLESS (X-UI) 2-WAY SYNC
        # ==========================================
        if user_id in xui_clients_map:
            inb_id, c_dict = xui_clients_map[user_id]
            changed = False
            
            # Update Usage to Firebase (Total up + down)
            try:
                # Get specific stats for usage calculation
                res_stats = xui_session.get(f"{xui_url}/panel/api/inbounds/getClientTraffics/{c_dict['email']}")
                stats = res_stats.json().get('obj', {})
                vless_used = (stats.get('up', 0) + stats.get('down', 0)) / (1024**3)
                update_fields['vlessUsedGB'] = round(vless_used, 3)
            except: pass

            # Check Limits & Expiry
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

            # If Admin updated Firebase, PUSH to X-UI Server natively!
            if changed:
                payload = {"id": inb_id, "settings": json.dumps({"clients": [c_dict]})}
                xui_session.post(f"{xui_url}/panel/api/inbounds/updateClient/{c_dict['id']}", data=payload)
                print(f"   [✅] VLESS API Updated (GB/Expiry Sync) for {user_id}")

        # Save latest usage back to Firebase
        if update_fields:
            users_ref.document(user_id).update(update_fields)

    print("[*] Sync cycle complete.")

if __name__ == "__main__":
    print("🚀 Auto-Sync & Real-Time API Configurator Started!")
    while True:
        sync_data()
        time.sleep(30) # စက္ကန့် ၃၀ တစ်ခါ Server နဲ့ အပြန်အလှန် Sync လုပ်ပါမည်
