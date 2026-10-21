import streamlit as st
import pandas as pd
import json
import os
import shutil
import io
import re
from datetime import datetime, date
from PIL import Image
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google.generativeai as genai

DATA_FILE = "receipts.json"
UPLOAD_DIR = "receipt_uploads"
DEFAULT_POOL_DIR = "receipt_pool"
SYNCED_FILE = "drive_synced.json"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/u/0/folders/1qe7GekVPbaCabbxASZHBZffK0eqfHgP6"
MASTER_FILE = "vendor_master.xlsx"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DEFAULT_POOL_DIR, exist_ok=True)

CATEGORIES = ["消耗品費", "旅費交通費", "通信費", "会議費", "交際費", "新聞図書費", "水道光熱費", "仕入高", "雑費", "その他"]
PAYMENT_METHODS = ["現金", "クレジットカード", "立替払（役員借入等）", "普通預金"]
TAX_RATES = ["10%", "8%（軽減税率）", "対象外"]

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_pooled_files(target_dir):
    if not os.path.exists(target_dir):
        return []
    valid_exts = [".png", ".jpg", ".jpeg", ".pdf"]
    return sorted([f for f in os.listdir(target_dir) if os.path.splitext(f)[1].lower() in valid_exts])

def get_drive_service():
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes)
    elif "GOOGLE_TOKEN" in st.secrets:
        token_info = json.loads(st.secrets["GOOGLE_TOKEN"])
        creds = Credentials.from_authorized_user_info(token_info, scopes)
    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

def extract_folder_id(url):
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url)
    if match: return match.group(1)
    if len(url) > 20 and '/' not in url: return url
    return None

def sync_from_drive(folder_url, pool_dir):
    folder_id = extract_folder_id(folder_url)
    if not folder_id:
        return False, "フォルダIDが無効です。"
    service = get_drive_service()
    if not service:
        return False, "認証情報が見つかりません。"

    synced_ids = []
    if os.path.exists(SYNCED_FILE):
        try:
            with open(SYNCED_FILE, "r") as f: synced_ids = json.load(f)
        except Exception: synced_ids = []

    try:
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType)",
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        items = results.get('files', [])

        count = 0
        for item in items:
            if item['name'] == MASTER_FILE:
                req = service.files().get_media(fileId=item['id'], supportsAllDrives=True)
                with io.FileIO(MASTER_FILE, 'wb') as fh:
                    downloader = MediaIoBaseDownload(fh, req)
                    done = False
                    while not done: _, done = downloader.next_chunk()
                continue

            if item['mimeType'] == 'application/vnd.google-apps.folder': continue
            if item['id'] in synced_ids: continue
            
            req = service.files().get_media(fileId=item['id'], supportsAllDrives=True)
            with io.FileIO(os.path.join(pool_dir, item['name']), 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = downloader.next_chunk()
            synced_ids.append(item['id'])
            count += 1

        with open(SYNCED_FILE, "w") as f: json.dump(synced_ids, f)
        return True, f"{count} 件の新規ファイルを取り込みました！"
    except Exception as e:
        return False, f"同期エラー: {str(e)}"

def match_vendor_master(store_name):
    if not os.path.exists(MASTER_FILE):
        return None
    try:
        df_master = pd.read_excel(MASTER_FILE)
        store_lower = store_name.lower()
        for _, row in df_master.iterrows():
            keywords = [k.strip().lower() for k in str(row.get("キーワード", "")).split(",") if k.strip()]
            for kw in keywords:
                if kw in store_lower:
                    is_shii = str(row.get("区分", "")).strip() == "仕入"
                    return {
                        "category": row.get("勘定科目", "消耗品費"),
                        "payment": row.get("決済手段", "クレジットカード"),
                        "memo": "" if is_shii else str(row.get("定型メモ", "") if pd.notna(row.get("定型メモ")) else "")
                    }
    except Exception:
        pass
    return None

def analyze_receipt_with_ai(file_path):
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"error": "Streamlit Secrets に GEMINI_API_KEY が設定されていません。"}
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".png", ".jpg", ".jpeg"]:
            img = Image.open(file_path)
            prompt = """
            領収書・レシート画像から次の情報を抽出し、必ず以下のJSON形式のみで回答してください。余計な解説は不要です。
            ```json
            {
              "date": "YYYY-MM-DD",
              "store": "店名・支払先",
              "amount": 1000,
              "tax_rate": "10%"
            }
            ```
            日付が特定できない場合は本日の日付、金額が不明な場合は 0 としてください。
            """
            res = model.generate_content([prompt, img])
            text = res.text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {"error": f"AIの応答形式が不正です: {text[:100]}"}
        else:
            return {"error": f"PDFは現在画像変換または手動入力が必要です (拡張子: {ext})"}
    except Exception as e:
        return {"error": f"AI読取エラー: {str(e)}"}

st.set_page_config(page_title="領収書整理 & 弥生会計ツール", page_icon="🧾", layout="wide")

st.sidebar.header("⚙️ フォルダ設定")
custom_pool_dir = st.sidebar.text_input("一時フォルダのパス", value=DEFAULT_POOL_DIR)
pool_dir = os.path.expanduser(custom_pool_dir.strip()) if custom_pool_dir.strip() else DEFAULT_POOL_DIR
os.makedirs(pool_dir, exist_ok=True)

st.title("🧾 領収書整理ツール（AI自動読取 ＆ マスタ自動仕訳）")

if "receipts" not in st.session_state:
    st.session_state.receipts = load_data()

tab_pool, tab_list = st.tabs(["📥 未処理プール（一括取り込み）", "📊 月別一覧 & 弥生会計出力"])

with tab_pool:
    with st.expander("☁️ Google ドライブから直接同期する", expanded=True):
        drive_url = st.text_input("Google ドライブのフォルダ URL", value=DEFAULT_DRIVE_URL)
        if st.button("🔄 ドライブから同期を実行", type="primary"):
            with st.spinner("Google ドライブと同期中..."):
                ok, msg = sync_from_drive(drive_url, pool_dir)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    pooled_files = get_pooled_files(pool_dir)
    if not pooled_files:
        st.info(f"💡 現在 `{pool_dir}` に未処理ファイルはありません。「🔄 ドライブから同期を実行」を押してください。")
    else:
        st.markdown(f"### 🎯 未処理の領収書: **残り {len(pooled_files)} 件**")
        target_file = pooled_files[0]
        target_path = os.path.join(pool_dir, target_file)
        ext = os.path.splitext(target_file)[1].lower()

        if "current_ai_result" not in st.session_state or st.session_state.get("current_file") != target_file:
            with st.spinner("🤖 AIが領収書を自動読取中..."):
                ai_res = analyze_receipt_with_ai(target_path)
            st.session_state.current_ai_result = ai_res
            st.session_state.current_file = target_file

        ai_data = st.session_state.current_ai_result or {}

        def_date = date.today()
        if ai_data.get("date"):
            try: def_date = datetime.strptime(ai_data["date"], "%Y-%m-%d").date()
            except Exception: pass

        def_store = ai_data.get("store", "")
        def_amount = int(ai_data.get("amount", 0))
        def_tax = ai_data.get("tax_rate", "10%")
        if def_tax not in TAX_RATES: def_tax = "10%"

        matched = match_vendor_master(def_store) if def_store else None
        def_category = matched["category"] if matched else "消耗品費"
        def_payment = matched["payment"] if matched else "クレジットカード"
        def_memo = matched["memo"] if matched else ""

        c_view, c_form = st.columns([1, 1])
        with c_view:
            st.caption(f"ファイル: `{target_file}`")
            if ext in [".png", ".jpg", ".jpeg"]:
                st.image(target_path, width="stretch")
            elif ext == ".pdf":
                st.info("📄 PDFファイルです。")
                with open(target_path, "rb") as f:
                    st.download_button("PDFを開く/ダウンロード", f.read(), file_name=target_file)
            if st.button("このファイルをスキップして削除", key="discard_btn"):
                os.remove(target_path)
                st.session_state.pop("current_ai_result", None)
                st.rerun()

        with c_form:
            if "error" in ai_data:
                st.warning(f"⚠️ {ai_data['error']}")
            elif ai_data.get("store"):
                st.success("🤖 AIによる自動読み取りが完了しました。内容を確認して「登録」を押してください。")
            with st.form("process_form", clear_on_submit=False):
                st.subheader("内容を確認して登録")
                rec_date = st.date_input("日付", value=def_date)
                store = st.text_input("支払先 / 店舗名*", value=def_store)
                f1, f2 = st.columns(2)
                with f1:
                    category = st.selectbox("勘定科目", CATEGORIES, index=CATEGORIES.index(def_category) if def_category in CATEGORIES else 0)
                    payment = st.selectbox("決済手段", PAYMENT_METHODS, index=PAYMENT_METHODS.index(def_payment) if def_payment in PAYMENT_METHODS else 1)
                with f2:
                    amount = st.number_input("金額 (税込・円)*", min_value=0, step=100, value=def_amount)
                    tax_rate = st.selectbox("税率", TAX_RATES, index=TAX_RATES.index(def_tax) if def_tax in TAX_RATES else 0)
                memo = st.text_input("用途・メモ", value=def_memo)
                submit = st.form_submit_button("✅ 登録して次へ（ワンクリック）", type="primary")

                if submit:
                    if not store.strip() or amount <= 0:
                        st.error("支払先と金額を入力してください。")
                    else:
                        ts = datetime.now().strftime("%Y%m%d%H%M%S")
                        saved_name = f"{ts}_{target_file}"
                        shutil.move(target_path, os.path.join(UPLOAD_DIR, saved_name))
                        st.session_state.receipts.append({
                            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                            "date": rec_date.strftime("%Y-%m-%d"),
                            "month": rec_date.strftime("%Y-%m"),
                            "store": store.strip(),
                            "category": category,
                            "amount": int(amount),
                            "payment": payment,
                            "tax_rate": tax_rate,
                            "memo": memo.strip(),
                            "file": saved_name
                        })
                        save_data(st.session_state.receipts)
                        st.session_state.pop("current_ai_result", None)
                        st.rerun()

with tab_list:
    if not st.session_state.receipts:
        st.info("登録済みのデータはありません。")
    else:
        df_all = pd.DataFrame(st.session_state.receipts)
        months = sorted(list(df_all["month"].unique()), reverse=True)
        c_m, c_q = st.columns([1, 2])
        with c_m: selected_month = st.selectbox("対象月", months)
        with c_q: query = st.text_input("🔍 検索 (店舗・メモ)")

        df_m = df_all[df_all["month"] == selected_month]
        if query:
            df_m = df_m[df_m["store"].str.contains(query, na=False) | df_m["memo"].str.contains(query, na=False)]
        df_m = df_m.sort_values("date", ascending=False)

        k1, k2, k3 = st.columns(3)
        k1.metric("対象月", selected_month)
        k2.metric("合計金額", f"¥{df_m['amount'].sum():,}")
        k3.metric("件数", f"{len(df_m)} 件")

        c_map = {"現金": "現金", "クレジットカード": "未払金", "立替払（役員借入等）": "役員借入金", "普通預金": "普通預金"}
        rows = []
        for _, r in df_m.iterrows():
            t_str = "課対仕入10%" if r.get("tax_rate") == "10%" else ("課対仕入8%(軽)" if "8%" in r.get("tax_rate", "") else "対象外")
            rows.append(["2000", "", "", r["date"].replace("-", "/"), r["category"], "", "", t_str, r["amount"], "0", c_map.get(r.get("payment"), "現金"), "", "", "対象外", r["amount"], "0", f"{r['store']} {r['memo']}".strip()])
            
        st.download_button("📥 弥生会計形式CSVダウンロード", pd.DataFrame(rows).to_csv(index=False, header=False, encoding="shift_jis", errors="replace"), f"yayoi_{selected_month}.csv", "text/csv", type="primary")
        st.divider()
        for _, r in df_m.iterrows():
            c1, c2, c3, c4, c5, c_del = st.columns([1.5, 2.5, 1.5, 1.5, 2.5, 0.5])
            c1.write(r["date"])
            c2.write(f"**{r['store']}**")
            c3.write(r["category"])
            c4.write(f"¥{r['amount']:,}")
            c5.caption(f"{r.get('payment')} / {r.get('tax_rate')}")
            if c_del.button("🗑️", key=f"del_{r['id']}"):
                st.session_state.receipts = [x for x in st.session_state.receipts if x["id"] != r["id"]]
                save_data(st.session_state.receipts)
                st.rerun()
            if r.get("file") and os.path.exists(os.path.join(UPLOAD_DIR, r["file"])):
                with st.expander(f"📎 添付プレビュー ({r['file']})"):
                    st.image(os.path.join(UPLOAD_DIR, r["file"]), width=350) if r['file'].lower().endswith(('png', 'jpg', 'jpeg')) else st.write("PDFファイル")
            st.divider()
