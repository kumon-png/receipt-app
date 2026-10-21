import streamlit as st
import pandas as pd
import json
import os
import shutil
import io
import re
from datetime import datetime, date
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DATA_FILE = "receipts.json"
UPLOAD_DIR = "receipt_uploads"
DEFAULT_POOL_DIR = "receipt_pool"
SYNCED_FILE = "drive_synced.json"
DEFAULT_DRIVE_URL = "https://drive.google.com/drive/u/0/folders/1qe7GekVPbaCabbxASZHBZffK0eqfHgP6"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DEFAULT_POOL_DIR, exist_ok=True)

CATEGORIES = ["消耗品費", "旅費交通費", "通信費", "会議費", "交際費", "新聞図書費", "水道光熱費", "雑費", "その他"]
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
        return False, "フォルダIDを抽出できません。URLを確認してください。"
    service = get_drive_service()
    if not service:
        return False, "認証情報が見つかりません。設定を確認してください。"

    synced_ids = []
    if os.path.exists(SYNCED_FILE):
        try:
            with open(SYNCED_FILE, "r") as f:
                synced_ids = json.load(f)
        except Exception:
            synced_ids = []

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
            if item['mimeType'] == 'application/vnd.google-apps.folder': continue
            if item['id'] in synced_ids: continue
            
            request = service.files().get_media(fileId=item['id'], supportsAllDrives=True)
            file_path = os.path.join(pool_dir, item['name'])
            with io.FileIO(file_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            synced_ids.append(item['id'])
            count += 1

        with open(SYNCED_FILE, "w") as f:
            json.dump(synced_ids, f)
        return True, f"{count} 件の新しいファイルを取得しました！"
    except Exception as e:
        return False, f"同期エラー: {str(e)}"

st.set_page_config(page_title="領収書整理 & 弥生会計ツール", page_icon="🧾", layout="wide")

st.sidebar.header("⚙️ フォルダ設定")
custom_pool_dir = st.sidebar.text_input("一時フォルダのパス", value=DEFAULT_POOL_DIR)
pool_dir = os.path.expanduser(custom_pool_dir.strip()) if custom_pool_dir.strip() else DEFAULT_POOL_DIR
os.makedirs(pool_dir, exist_ok=True)
st.sidebar.caption(f"現在の対象パス:\n`{pool_dir}`")

st.title("🧾 領収書整理ツール（クラウド同期対応）")

if "receipts" not in st.session_state:
    st.session_state.receipts = load_data()

tab_pool, tab_list = st.tabs(["📥 未処理プール（一括取り込み）", "📊 月別一覧 & 弥生会計出力"])

with tab_pool:
    with st.expander("☁️ Google ドライブから直接同期する", expanded=True):
        st.write("設定フォルダから未処理ファイルをダウンロードします。")
        drive_url = st.text_input("Google ドライブのフォルダ URL", value=DEFAULT_DRIVE_URL)
        if st.button("🔄 ドライブから同期を実行", type="primary"):
            if not drive_url:
                st.warning("URLを入力してください。")
            else:
                with st.spinner("Google ドライブから取得中..."):
                    success, msg = sync_from_drive(drive_url, pool_dir)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with st.expander("📁 ローカルから手動追加", expanded=False):
        uploaded_files = st.file_uploader("まとめてドロップ可能", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True)
        if st.button("プールに手動保存") and uploaded_files:
            for uf in uploaded_files:
                with open(os.path.join(pool_dir, uf.name), "wb") as f:
                    f.write(uf.getbuffer())
            st.success(f"{len(uploaded_files)} 件保存しました！")
            st.rerun()

    pooled_files = get_pooled_files(pool_dir)
    if not pooled_files:
        st.info(f"💡 現在 `{pool_dir}` に未処理ファイルはありません。「🔄 ドライブから同期を実行」を押してください。")
    else:
        st.markdown(f"### 🎯 未処理の領収書: **残り {len(pooled_files)} 件**")
        target_file = pooled_files[0]
        target_path = os.path.join(pool_dir, target_file)
        ext = os.path.splitext(target_file)[1].lower()

        c_view, c_form = st.columns([1, 1])
        with c_view:
            st.caption(f"ファイル: `{target_file}`")
            if ext in [".png", ".jpg", ".jpeg"]:
                st.image(target_path, use_container_width=True)
            elif ext == ".pdf":
                st.info("📄 PDFファイルです。")
                with open(target_path, "rb") as f:
                    st.download_button("PDFを開く/ダウンロード", f.read(), file_name=target_file)
            if st.button("このファイルをスキップして削除", key="discard_btn"):
                os.remove(target_path)
                st.rerun()

        with c_form:
            with st.form("process_form", clear_on_submit=False):
                st.subheader("内容を入力して登録")
                rec_date = st.date_input("日付", value=date.today())
                store = st.text_input("支払先 / 店舗名*", placeholder="例: セブンイレブン")
                f1, f2 = st.columns(2)
                with f1:
                    category = st.selectbox("勘定科目", CATEGORIES)
                    payment = st.selectbox("決済手段", PAYMENT_METHODS)
                with f2:
                    amount = st.number_input("金額 (税込・円)*", min_value=0, step=100, value=0)
                    tax_rate = st.selectbox("税率", TAX_RATES)
                memo = st.text_input("用途・メモ", placeholder="例: 事務用品購入")
                submit = st.form_submit_button("✅ 登録して次へ", type="primary")

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
