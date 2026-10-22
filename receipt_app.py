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

# ==========================================
# 1. ユーザー定義（PIN不要・利用者選択のみ・全員全操作可能）
# ==========================================
USERS = {
    "kumon@9gates.info": {
        "name": "九門（代表）",
        "companies": ["ナインゲイツ", "シュガー", "SF企画"]
    },
    "kikaku@9gates.info": {
        "name": "企画・全体経理",
        "companies": ["ナインゲイツ", "シュガー", "SF企画"]
    },
    "h.kumon@9gates.info": {
        "name": "SF企画 担当経理",
        "companies": ["ナインゲイツ", "シュガー", "SF企画"]
    },
    "zeirishi.sugimoto@9gates.info": {
        "name": "杉本税理士事務所",
        "companies": ["ナインゲイツ", "シュガー", "SF企画"]
    }
}

# ==========================================
# 2. 各法人の設定・勘定科目・決済手段
# ==========================================
COMPANY_CONFIG = {
    "ナインゲイツ": {
        "code": "ninegates",
        "fiscal_start": 4,
        "categories": ["外注費", "仕入高", "旅費交通費", "消耗品費", "車両費", "通信費", "会議費", "交際費", "地代家賃", "水道光熱費", "支払手数料", "法定福利費", "福利厚生費", "雑費"],
        "payments": ["クレジットカード（未払金）", "役員立替（役員借入金）", "現金", "普通預金（PayPay銀行）", "普通預金（広島市信用組合）"],
        "payment_mapping": {
            "クレジットカード（未払金）": ("未払金", "カード"),
            "役員立替（役員借入金）": ("役員借入金", "九門久士"),
            "現金": ("現金", ""),
            "普通預金（PayPay銀行）": ("普通預金", "PayPay銀行"),
            "普通預金（広島市信用組合）": ("普通預金", "広島市信用組合"),
        }
    },
    "シュガー": {
        "code": "sugar",
        "fiscal_start": 6,
        "categories": ["外注費", "仕入高（8%軽）", "仕入高（10%）", "地代家賃", "旅費交通費", "消耗品費", "支払手数料", "荷造運賃", "リース料", "雑費", "開業費"],
        "payments": ["普通預金（PayPay銀行）", "役員立替（短期借入金）", "クレジットカード（未払金）", "普通預金（広島市信用組合）", "普通預金（呉信用金庫）"],
        "payment_mapping": {
            "普通預金（PayPay銀行）": ("普通預金", "PayPay銀行"),
            "役員立替（短期借入金）": ("短期借入金", "クモンヒサシ"),
            "クレジットカード（未払金）": ("未払金", ""),
            "普通預金（広島市信用組合）": ("普通預金", "広島市信用組合"),
            "普通預金（呉信用金庫）": ("普通預金", "呉信用金庫"),
        }
    },
    "SF企画": {
        "code": "sf_kikaku",
        "fiscal_start": 8,
        "categories": [
            "① 旅費交通費・車両維持費",
            "② 会議費・接待交際費",
            "③ 通信費・IT・クラウド利用料",
            "④ 地代家賃・水道光熱費",
            "⑤ 調査研究費・消耗品費",
            "⑥ 支払手数料・租税公課",
            "開業費（繰延資産）"
        ],
        "payments": ["役員立替（役員借入金）", "普通預金（PayPay銀行）", "クレジットカード（未払金）"],
        "payment_mapping": {
            "役員立替（役員借入金）": ("役員借入金", "九門久士"),
            "普通預金（PayPay銀行）": ("普通預金", "PayPay銀行"),
            "クレジットカード（未払金）": ("未払金", ""),
        }
    }
}

TAX_RATES = ["10%", "8%（軽減税率）", "対象外"]
BASE_UPLOAD_DIR = "receipt_uploads"
DEFAULT_POOL_DIR = "receipt_pool"
SYNCED_FILE = "drive_synced.json"
DEFAULT_DRIVE_URL = "[https://drive.google.com/drive/u/0/folders/1qe7GekVPbaCabbxASZHBZffK0eqfHgP6](https://drive.google.com/drive/u/0/folders/1qe7GekVPbaCabbxASZHBZffK0eqfHgP6)"
MASTER_FILE = "vendor_master.xlsx"

os.makedirs(DEFAULT_POOL_DIR, exist_ok=True)

# ==========================================
# 3. ユーティリティ関数
# ==========================================
def get_company_paths(company_name):
    conf = COMPANY_CONFIG[company_name]
    up_dir = os.path.join(BASE_UPLOAD_DIR, company_name)
    os.makedirs(up_dir, exist_ok=True)
    json_path = f"receipts_{conf['code']}.json"
    inv_json_path = f"invoices_{conf['code']}.json"
    return up_dir, json_path, inv_json_path

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return []
    return []

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def calc_fiscal_year(date_str, start_month):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.year if dt.month >= start_month else dt.year - 1
    except Exception:
        return datetime.now().year

def get_pooled_files(target_dir):
    if not os.path.exists(target_dir): return []
    valid_exts = [".png", ".jpg", ".jpeg", ".pdf"]
    return sorted([f for f in os.listdir(target_dir) if os.path.splitext(f)[1].lower() in valid_exts])

def get_drive_service():
    scopes = ['[https://www.googleapis.com/auth/drive.readonly](https://www.googleapis.com/auth/drive.readonly)']
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes)
    elif "GOOGLE_TOKEN" in st.secrets:
        token_info = json.loads(st.secrets["GOOGLE_TOKEN"])
        creds = Credentials.from_authorized_user_info(token_info, scopes)
    if creds: return build('drive', 'v3', credentials=creds)
    return None

def extract_folder_id(url):
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url)
    if match: return match.group(1)
    if len(url) > 20 and '/' not in url: return url
    return None

def sync_from_drive(folder_url, pool_dir):
    folder_id = extract_folder_id(folder_url)
    if not folder_id: return False, "フォルダIDが無効です。"
    service = get_drive_service()
    if not service: return False, "Google認証情報が見つかりません。"

    synced_ids = []
    if os.path.exists(SYNCED_FILE):
        try:
            with open(SYNCED_FILE, "r") as f: synced_ids = json.load(f)
        except Exception: synced_ids = []

    try:
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(
            q=query, fields="files(id, name, mimeType)",
            pageSize=1000, supportsAllDrives=True, includeItemsFromAllDrives=True
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

def match_vendor_master(store_name, company_name):
    if not os.path.exists(MASTER_FILE): return None
    try:
        df_master = pd.read_excel(MASTER_FILE)
        store_lower = store_name.lower()
        for _, row in df_master.iterrows():
            keywords = [k.strip().lower() for k in str(row.get("キーワード", "")).split(",") if k.strip()]
            for kw in keywords:
                if kw in store_lower:
                    is_shii = str(row.get("区分", "")).strip() == "仕入"
                    cat = row.get("勘定科目", "")
                    
                    if company_name == "SF企画":
                        if "交通" in cat or "車" in cat: cat = "① 旅費交通費・車両維持費"
                        elif "会議" in cat or "交際" in cat: cat = "② 会議費・接待交際費"
                        elif "通信" in cat: cat = "③ 通信費・IT・クラウド利用料"
                        elif "家賃" in cat or "光熱" in cat: cat = "④ 地代家賃・水道光熱費"
                        elif "消耗品" in cat or "仕入" in cat: cat = "⑤ 調査研究費・消耗品費"
                        else: cat = "⑥ 支払手数料・租税公課"

                    conf = COMPANY_CONFIG[company_name]
                    return {
                        "category": cat if cat in conf["categories"] else conf["categories"][0],
                        "payment": conf["payments"][0],
                        "memo": "" if is_shii else str(row.get("定型メモ", "") if pd.notna(row.get("定型メモ")) else "")
                    }
    except Exception: pass
    return None

def analyze_receipt_with_ai(file_path, model_name="gemini-3.8-flash"):
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key: return {"error": "Streamlit Secrets に GEMINI_API_KEY が設定されていません。"}
    try:
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
            
            # モデル名のフォールバック
            actual_model = "gemini-1.5-flash"
            if "argon" in model_name.lower() or "4" in model_name:
                actual_model = "gemini-1.5-pro"
                
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(model=actual_model, contents=[prompt, img])
                text = res.text
            except Exception:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=api_key)
                model = legacy_genai.GenerativeModel(actual_model)
                res = model.generate_content([prompt, img])
                text = res.text

            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group(0))
            return {"error": f"AIの応答形式が不正です: {text[:100]}"}
        else:
            return {"error": f"PDFは手動入力または画像変換が必要です (拡張子: {ext})"}
    except Exception as e:
        return {"error": f"AI読取エラー ({model_name}): {str(e)}"}

# ==========================================
# 4. Streamlit アプリ本体（PIN撤廃・利用者プルダウン選定のみ）
# ==========================================
st.set_page_config(page_title="経理DX＆弥生会計一貫ツール", page_icon="🏢", layout="wide")

# サイドバー: 利用者選定
st.sidebar.markdown("## 👤 利用者選定")
user_key = st.sidebar.selectbox(
    "操作者を選択してください",
    list(USERS.keys()),
    format_func=lambda x: f"{USERS[x]['name']} ({x})"
)
current_user = USERS[user_key]

st.sidebar.markdown("---")
st.sidebar.markdown("## 🏢 対象法人の切り替え")
selected_company = st.sidebar.selectbox("法人を選択", current_user["companies"], index=0)
company_conf = COMPANY_CONFIG[selected_company]
upload_dir, data_json_file, inv_json_file = get_company_paths(selected_company)

st.sidebar.markdown("---")
model_choice = st.sidebar.selectbox("AI モデル", ["gemini-3.8-flash", "gemini-4-argon"], index=0)
custom_pool_dir = st.sidebar.text_input("未処理プールフォルダ", value=DEFAULT_POOL_DIR)
pool_dir = os.path.expanduser(custom_pool_dir.strip()) if custom_pool_dir.strip() else DEFAULT_POOL_DIR

# メイン画面ヘッダー
st.title(f"🏢 {selected_company} 経理システム")
st.caption(f"📁 保存先: `{upload_dir}/` ｜ 会計年度: {company_conf['fiscal_start']}月期首 ｜ 操作者: **{current_user['name']}**（全操作可能）")

if f"receipts_{selected_company}" not in st.session_state:
    st.session_state[f"receipts_{selected_company}"] = load_json(data_json_file)
if f"invoices_{selected_company}" not in st.session_state:
    st.session_state[f"invoices_{selected_company}"] = load_json(inv_json_file)

tab_pool, tab_list, tab_invoice = st.tabs([
    "📥 未処理プール（AI自動OCR＆仕訳）",
    "📊 月別経費一覧 ＆ 弥生経費CSV",
    "📄 請求書作成 ＆ 弥生売上CSV"
])

# ------------------------------------------
# タブ 1: 未処理プール
# ------------------------------------------
with tab_pool:
    with st.expander("☁️ Google ドライブから領収書を同期する", expanded=False):
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
        st.info(f"💡 現在 `{pool_dir}` に未処理ファイルはありません。「Google ドライブから同期」を実行してください。")
    else:
        st.markdown(f"### 🎯 未処理の領収書: **残り {len(pooled_files)} 件**")
        target_file = pooled_files[0]
        target_path = os.path.join(pool_dir, target_file)
        ext = os.path.splitext(target_file)[1].lower()

        if ("current_ai_result" not in st.session_state or 
            st.session_state.get("current_file") != target_file or 
            st.session_state.get("current_model") != model_choice or
            st.session_state.get("current_comp") != selected_company):
            with st.spinner(f"🤖 AI ({model_choice}) が【{selected_company}】の勘定体系で解析中..."):
                ai_res = analyze_receipt_with_ai(target_path, model_name=model_choice)
            st.session_state.current_ai_result = ai_res
            st.session_state.current_file = target_file
            st.session_state.current_model = model_choice
            st.session_state.current_comp = selected_company

        ai_data = st.session_state.current_ai_result or {}

        def_date = date.today()
        if ai_data.get("date"):
            try: def_date = datetime.strptime(ai_data["date"], "%Y-%m-%d").date()
            except Exception: pass

        def_store = ai_data.get("store", "")
        def_amount = int(ai_data.get("amount", 0))
        def_tax = ai_data.get("tax_rate", "10%")
        if def_tax not in TAX_RATES: def_tax = "10%"

        matched = match_vendor_master(def_store, selected_company) if def_store else None
        def_category = matched["category"] if matched else company_conf["categories"][0]
        def_payment = matched["payment"] if matched else company_conf["payments"][0]
        def_memo = matched["memo"] if matched else ""

        c_view, c_form = st.columns([1, 1])
        with c_view:
            st.caption(f"解析中ファイル: `{target_file}`")
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
                st.success(f"🤖 【{selected_company}】向けに最適化読取が完了しました")
            with st.form("process_form", clear_on_submit=False):
                st.subheader("内容を確認して登録")
                rec_date = st.date_input("日付", value=def_date)
                store = st.text_input("支払先 / 店舗名*", value=def_store)
                f1, f2 = st.columns(2)
                with f1:
                    category = st.selectbox(
                        "勘定科目（借方）",
                        company_conf["categories"],
                        index=company_conf["categories"].index(def_category) if def_category in company_conf["categories"] else 0
                    )
                    payment = st.selectbox(
                        "決済手段（貸方）",
                        company_conf["payments"],
                        index=company_conf["payments"].index(def_payment) if def_payment in company_conf["payments"] else 0
                    )
                with f2:
                    amount = st.number_input("金額 (税込・円)*", min_value=0, step=100, value=def_amount)
                    tax_rate = st.selectbox("税率", TAX_RATES, index=TAX_RATES.index(def_tax) if def_tax in TAX_RATES else 0)
                memo = st.text_input("用途・メモ", value=def_memo)
                submit = st.form_submit_button(f"✅ 【{selected_company}】の経費として登録", type="primary")

                if submit:
                    if not store.strip() or amount <= 0:
                        st.error("支払先と金額を入力してください。")
                    else:
                        ts = datetime.now().strftime("%Y%m%d%H%M%S")
                        saved_name = f"{ts}_{target_file}"
                        dest_file_path = os.path.join(upload_dir, saved_name)
                        shutil.move(target_path, dest_file_path)

                        current_records = st.session_state[f"receipts_{selected_company}"]
                        current_records.append({
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
                        save_json(data_json_file, current_records)
                        st.session_state.pop("current_ai_result", None)
                        st.success(f"`{upload_dir}/` に領収書を振り分け保存しました！")
                        st.rerun()

# ------------------------------------------
# タブ 2: 月別経費一覧 ＆ 弥生経費CSV出力
# ------------------------------------------
with tab_list:
    current_receipts = st.session_state[f"receipts_{selected_company}"]
    if not current_receipts:
        st.info(f"【{selected_company}】の登録済み経費データはありません。")
    else:
        df_all = pd.DataFrame(current_receipts)
        months = sorted(list(df_all["month"].unique()), reverse=True)
        c_m, c_q = st.columns([1, 2])
        with c_m: selected_month = st.selectbox("対象月を選択", months, key="exp_month")
        with c_q: query = st.text_input("🔍 検索 (店舗・メモ)", key="exp_query")

        df_m = df_all[df_all["month"] == selected_month]
        if query:
            df_m = df_m[df_m["store"].str.contains(query, na=False) | df_m["memo"].str.contains(query, na=False)]
        df_m = df_m.sort_values("date", ascending=False)

        k1, k2, k3 = st.columns(3)
        k1.metric("対象月", selected_month)
        k2.metric("経費合計金額", f"¥{df_m['amount'].sum():,}")
        k3.metric("件数", f"{len(df_m)} 件")

        rows = []
        p_map = company_conf["payment_mapping"]
        for _, r in df_m.iterrows():
            t_str = "課対仕入10%" if r.get("tax_rate") == "10%" else ("課対仕入8%(軽)" if "8%" in r.get("tax_rate", "") else "対象外")
            credit_info = p_map.get(r.get("payment"), ("未払金", ""))
            credit_cat, credit_sub = credit_info[0], credit_info[1]

            # 弥生25列フォーマット
            rows.append([
                "2000", "", "", r["date"].replace("-", "/"),
                r["category"], "", "", t_str, r["amount"], "0",
                credit_cat, credit_sub, "", "対象外", r["amount"], "0",
                f"{r['store']} {r['memo']}".strip(),
                "", "", "", "", "", "", "", ""
            ])

        fiscal_year = calc_fiscal_year(f"{selected_month}-01", company_conf["fiscal_start"])
        csv_filename = f"弥生仕訳_{selected_company}_{fiscal_year}年度_{selected_month}度.csv"

        csv_data = pd.DataFrame(rows).to_csv(index=False, header=False, encoding="shift_jis", errors="replace")
        st.download_button(
            f"📥 弥生会計形式CSVダウンロード（{csv_filename}）",
            csv_data,
            csv_filename,
            "text/csv",
            type="primary"
        )
        st.divider()

        for _, r in df_m.iterrows():
            c1, c2, c3, c4, c5, c_del = st.columns([1.5, 2.5, 1.5, 1.5, 2.5, 0.5])
            c1.write(r["date"])
            c2.write(f"**{r['store']}**")
            c3.write(r["category"])
            c4.write(f"¥{r['amount']:,}")
            c5.caption(f"{r.get('payment')} / {r.get('tax_rate')}")
            if c_del.button("🗑️", key=f"del_exp_{r['id']}"):
                st.session_state[f"receipts_{selected_company}"] = [x for x in current_receipts if x["id"] != r["id"]]
                save_json(data_json_file, st.session_state[f"receipts_{selected_company}"])
                st.rerun()

            file_saved_path = os.path.join(upload_dir, r.get("file", ""))
            if r.get("file") and os.path.exists(file_saved_path):
                with st.expander(f"📎 添付プレビュー ({r['file']})"):
                    if r['file'].lower().endswith(('png', 'jpg', 'jpeg')):
                        st.image(file_saved_path, width=350)
                    else:
                        st.write("📄 PDFファイル")
            st.divider()

# ------------------------------------------
# タブ 3: 請求書作成 ＆ 弥生売上CSV
# ------------------------------------------
with tab_invoice:
    st.markdown(f"### 📄 請求書作成（発行元：{selected_company}）")
    with st.form("invoice_form"):
        i1, i2 = st.columns(2)
        with i1:
            inv_date = st.date_input("請求日", value=date.today())
            inv_client = st.text_input("請求先（取引先会社名）*", value="合同会社シュガー" if selected_company == "ナインゲイツ" else ("株式会社USENテクノサービス" if selected_company == "シュガー" else "合同会社シュガー"))
            inv_no = st.text_input("請求書番号", value=f"INV-{datetime.now().strftime('%Y%m')}-001")
        with i2:
            due_date = st.date_input("お支払期日", value=date.today())
            inv_title = st.text_input("請求件名*", value="通信事業委託業務 費用" if selected_company != "SF企画" else "700MHz・EV充電器関連業務委託費")
            inv_tax_rate = st.selectbox("消費税率", ["10%", "8%（軽減税率）"], index=0)

        st.markdown("#### 請求明細")
        m1, m2, m3 = st.columns([3, 1, 1])
        with m1: item_name = st.text_input("品名・役務内容*", value="業務委託費一式")
        with m2: item_qty = st.number_input("数量", min_value=1, value=1)
        with m3: item_price = st.number_input("単価（税抜・円）*", min_value=0, step=10000, value=100000)

        tax_mult = 0.10 if inv_tax_rate == "10%" else 0.08
        subtotal = item_qty * item_price
        tax_amount = int(subtotal * tax_mult)
        total_amount = subtotal + tax_amount

        st.info(f"💰 **税抜計:** ¥{subtotal:,} ｜ **消費税:** ¥{tax_amount:,} ｜ **税込合計:** ¥{total_amount:,}")
        submit_inv = st.form_submit_button("✅ 請求データを保存して売上仕訳を作成", type="primary")

        if submit_inv:
            if not inv_client.strip() or total_amount <= 0:
                st.error("請求先と金額を正しく入力してください。")
            else:
                inv_records = st.session_state[f"invoices_{selected_company}"]
                inv_records.append({
                    "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                    "inv_no": inv_no,
                    "date": inv_date.strftime("%Y-%m-%d"),
                    "month": inv_date.strftime("%Y-%m"),
                    "due_date": due_date.strftime("%Y-%m-%d"),
                    "client": inv_client.strip(),
                    "title": inv_title.strip(),
                    "item_name": item_name.strip(),
                    "qty": item_qty,
                    "unit_price": item_price,
                    "tax_rate": inv_tax_rate,
                    "subtotal": subtotal,
                    "tax_amount": tax_amount,
                    "total": total_amount
                })
                save_json(inv_json_file, inv_records)
                st.success(f"請求番号 `{inv_no}` を登録しました！")
                st.rerun()

    st.markdown("---")
    st.markdown(f"### 📊 【{selected_company}】発行済み請求一覧 ＆ 弥生売上仕訳")
    current_invoices = st.session_state[f"invoices_{selected_company}"]
    if not current_invoices:
        st.info(f"【{selected_company}】で発行した請求書データはありません。")
    else:
        df_inv = pd.DataFrame(current_invoices)
        inv_months = sorted(list(df_inv["month"].unique()), reverse=True)
        sel_inv_month = st.selectbox("対象月（売上計上月）", inv_months, key="inv_m_select")
        df_inv_m = df_inv[df_inv["month"] == sel_inv_month]

        inv_rows = []
        for _, r in df_inv_m.iterrows():
            t_str = "課税売上10%" if r.get("tax_rate") == "10%" else "課税売上8%(軽)"
            inv_rows.append([
                "2000", "", "", r["date"].replace("-", "/"),
                "売掛金", r["client"], "", "対象外", r["total"], "0",
                "売上高", "", "", t_str, r["total"], "0",
                f"{r['inv_no']} {r['title']}".strip(),
                "", "", "", "", "", "", "", ""
            ])

        fiscal_year = calc_fiscal_year(f"{sel_inv_month}-01", company_conf["fiscal_start"])
        inv_csv_name = f"弥生売上仕訳_{selected_company}_{fiscal_year}年度_{sel_inv_month}度.csv"
        inv_csv_data = pd.DataFrame(inv_rows).to_csv(index=False, header=False, encoding="shift_jis", errors="replace")

        st.download_button(
            f"📥 弥生売上仕訳CSVダウンロード（{inv_csv_name}）",
            inv_csv_data,
            inv_csv_name,
            "text/csv",
            type="primary"
        )

        for _, r in df_inv_m.iterrows():
            st.markdown(f"**【{r['inv_no']}】 {r['client']} 御中** ｜ 請求日: {r['date']} ｜ **税込: ¥{r['total']:,}** ({r['title']})")
            with st.expander(f"🖨️ 請求書詳細プレビュー・印刷表示 ({r['inv_no']})"):
                st.markdown(f"""
                <div style="border:1px solid #ccc; padding:20px; border-radius:5px; background-color:#fff; color:#333;">
                    <h2 style="text-align:center;">御 請 求 書</h2>
                    <p style="text-align:right;">請求番号: {r['inv_no']}<br>請求日: {r['date']}<br>お支払期日: {r['due_date']}</p>
                    <h3>{r['client']} 御中</h3>
                    <p style="text-align:right;"><b>発行元：{selected_company}</b></p>
                    <hr>
                    <h3 style="text-align:center; background-color:#f0f0f0; padding:10px;">ご請求金額： ¥{r['total']:,} （税込）</h3>
                    <table style="width:100%; border-collapse:collapse; margin-top:15px;" border="1">
                        <tr style="background-color:#fafafa;"><th>品名・役務内容</th><th>数量</th><th>単価（税抜）</th><th>金額（税抜）</th></tr>
                        <tr><td>{r['item_name']}</td><td style="text-align:center;">{r['qty']}</td><td style="text-align:right;">¥{r['unit_price']:,}</td><td style="text-align:right;">¥{r['subtotal']:,}</td></tr>
                    </table>
                    <p style="text-align:right; margin-top:10px;">税抜金額: ¥{r['subtotal']:,} ｜ 消費税({r['tax_rate']}): ¥{r['tax_amount']:,}</p>
                </div>
                """, unsafe_allow_html=True)
            if st.button("🗑️ この請求データを削除", key=f"del_inv_{r['id']}"):
                st.session_state[f"invoices_{selected_company}"] = [x for x in current_invoices if x["id"] != r["id"]]
                save_json(inv_json_file, st.session_state[f"invoices_{selected_company}"])
                st.rerun()
            st.divider()
