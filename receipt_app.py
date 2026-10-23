import streamlit as st
import pandas as pd
import json
import os
import shutil
import io
import re
from datetime import datetime, date
from PIL import Image

# pypdfの遅延安全インポート
try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ==========================================
# 0. 型安全ヘルパー関数
# ==========================================
def safe_first_str(val, fallback=""):
    if isinstance(val, (list, tuple)):
        return str(val) if len(val) > 0 else fallback
    if val is None:
        return fallback
    return str(val)

# ==========================================
# 1. ユーザー定義
# ==========================================
USERS = {
    "kumon@9gates.info": {"name": "九門（代表）", "companies": ["ナインゲイツ", "シュガー", "SF企画"]},
    "kikaku@9gates.info": {"name": "企画・全体経理", "companies": ["ナインゲイツ", "シュガー", "SF企画"]},
    "h.kumon@9gates.info": {"name": "SF企画 担当経理", "companies": ["ナインゲイツ", "シュガー", "SF企画"]},
    "zeirishi.sugimoto@9gates.info": {"name": "杉本税理士事務所", "companies": ["ナインゲイツ", "シュガー", "SF企画"]}
}

# ==========================================
# 2. 飲食・会食検知用キーワード
# ==========================================
DINING_KEYWORDS = [
    "蹄", "野武士", "エスカイヤ", "すし辰", "くら寿司", "スシロー", "なか一", 
    "アンデルセン", "ふるさと", "焼肉", "寿司", "居酒屋", "バル", "カフェ", 
    "珈琲", "レストラン", "割烹", "料理", "酒場", "スターバックス", "ドトール", 
    "バー", "bar", "はき溜め", "はき駄め", "スタンドクラブ", "餃子家龍"
]

# ==========================================
# 3. 各法人設定・口座マスタ
# ==========================================
COMPANY_CONFIG = {
    "ナインゲイツ": {
        "code": "ninegates",
        "fiscal_start": 4,
        "input_folder_id": "1upG2C-m-An3VcI1ULE7A6BwHipRzIjge",
        "output_folder_id": "1xtj1g42RSwOa_eUATF89qLdS_JiM_yQ8",
        "categories": [
            "外注費", "仕入高", "仕入高（8%軽）", "旅費交通費", "消耗品費", 
            "車両費", "通信費", "会議費", "交際費", "地代家賃", 
            "水道光熱費", "支払手数料", "法定福利費", "福利厚生費", "雑費"
        ],
        "payments": [
            "普通預金（PayPay銀行 005-1744850）",
            "普通預金（広島市信用組合 117-0878359-0）",
            "普通預金（呉信用金庫 020-1096121）",
            "役員立替（PayPay個人 003-2060281）",
            "役員立替（楽天個人 214-4383608）",
            "クレジットカード（未払金）",
            "現金"
        ],
        "payment_mapping": {
            "普通預金（PayPay銀行 005-1744850）": ("普通預金", "PayPay銀行(1744850)"),
            "普通預金（広島市信用組合 117-0878359-0）": ("普通預金", "広島市信用組合"),
            "普通預金（呉信用金庫 020-1096121）": ("普通預金", "呉信用金庫"),
            "役員立替（PayPay個人 003-2060281）": ("役員借入金", "九門久士(PayPay)"),
            "役員立替（楽天個人 214-4383608）": ("役員借入金", "九門久士(楽天)"),
            "クレジットカード（未払金）": ("未払金", "カード"),
            "現金": ("現金", ""),
        },
        "keyword_rules": [
            (["はき溜め", "はき駄め", "蹄", "エスカイヤ", "野武士", "ふるさと"], "交際費", "", "課対仕入10%"),
            (["ケーティーエス", "kts", "鳥取通信", "ベッセル", "エルワイコンサル", "アイデン", "ミカモ電気", "アルテック"], "外注費", "", "課対仕入10%"),
            (["シュガー", "sugar"], "外注費", "合同会社シュガー", "課対仕入10%"),
            (["サイボウズ", "cybozu", "adobe", "ドコモ", "docomo", "マイクロソフト", "gcp", "google"], "通信費", "", "課対仕入10%"),
            (["キユウユダイ", "給油", "eneos", "ホウジンetc", "etc", "高速情報協同組合"], "車両費", "", "課対仕入10%"),
            (["jr", "新幹線", "タクシー", "楽天トラベル", "ホテル", "リパーク", "タイムズ", "駐車場"], "旅費交通費", "", "課対仕入10%"),
            (["アマゾン", "amazon", "コーナン", "kohnan", "セリア", "ヨドバシ"], "消耗品費", "", "課対仕入10%"),
            (["振込手数料", "手数料", "全厚済"], "支払手数料", "", "課対仕入10%")
        ]
    },
    "シュガー": {
        "code": "sugar",
        "fiscal_start": 6,
        "input_folder_id": "1qo5FqrpHDFgY4tzf32YaYbFQB6wCQ9Ih",
        "output_folder_id": "19HhywRqfSRG2tWMVzDkcw6DlmCMGLgSI",
        "categories": [
            "外注費", "仕入高（8%軽）", "仕入高（10%）", "地代家賃", "旅費交通費", 
            "消耗品費", "支払手数料", "荷造運賃", "リース料", "雑費", "開業費"
        ],
        "payments": [
            "普通預金（PayPay銀行 005-5332515）",
            "普通預金（PayPay法人 005-5332523）",
            "普通預金（呉信用金庫 020-1096139）",
            "普通預金（広島市信用組合 117-0878367）",
            "役員立替（PayPay個人 003-2060281）",
            "役員立替（楽天個人 214-4383608）",
            "クレジットカード（未払金）",
            "現金"
        ],
        "payment_mapping": {
            "普通預金（PayPay銀行 005-5332515）": ("普通預金", "PayPay銀行(5332515)"),
            "普通預金（PayPay法人 005-5332523）": ("普通預金", "PayPay法人(5332523)"),
            "普通預金（呉信用金庫 020-1096139）": ("普通預金", "呉信用金庫"),
            "普通預金（広島市信用組合 117-0878367）": ("普通預金", "広島市信用組合"),
            "役員立替（PayPay個人 003-2060281）": ("短期借入金", "クモンヒサシ(PayPay)"),
            "役員立替（楽天個人 214-4383608）": ("短期借入金", "クモンヒサシ(楽天)"),
            "クレジットカード（未払金）": ("未払金", ""),
            "現金": ("現金", "")
        }
    },
    "SF企画": {
        "code": "sf_kikaku",
        "fiscal_start": 8,
        "input_folder_id": "1BZrjf_kq_kNLsXoOOMfRxUKiJSydC5Qa",
        "output_folder_id": "1VuS4VHIPpNG8HPbARq4xkkDUdE_wN8U6",
        "categories": [
            "⑤ 調査研究費・消耗品費",
            "① 旅費交通費・車両維持費",
            "② 会議費・接待交際費",
            "③ 通信費・IT・クラウド利用料",
            "④ 地代家賃・水道光熱費",
            "⑥ 支払手数料・租税公課",
            "開業費（繰延資産）"
        ],
        "payments": [
            "普通預金（PayPay銀行 005-2423746）",
            "役員立替（PayPay個人 003-2060281）",
            "役員立替（楽天個人 214-4383608）",
            "クレジットカード（未払金）",
            "現金"
        ],
        "payment_mapping": {
            "普通預金（PayPay銀行 005-2423746）": ("普通預金", "PayPay銀行(2423746)"),
            "役員立替（PayPay個人 003-2060281）": ("役員借入金", "九門久士(PayPay)"),
            "役員立替（楽天個人 214-4383608）": ("役員借入金", "九門久士(楽天)"),
            "クレジットカード（未払金）": ("未払金", ""),
            "現金": ("現金", "")
        }
    }
}

BASE_UPLOAD_DIR = "receipt_uploads"
DEFAULT_POOL_DIR = "receipt_pool"
SYNCED_FILE = "drive_synced.json"
MASTER_FILE = "vendor_master.xlsx"

os.makedirs(DEFAULT_POOL_DIR, exist_ok=True)
os.makedirs(BASE_UPLOAD_DIR, exist_ok=True)

# ==========================================
# 4. Google Drive API 関数
# ==========================================
def get_drive_service():
    scopes = ['[suspicious link removed]']
    creds = None
    if os.path.exists('token.json'):
        try: creds = Credentials.from_authorized_user_file('token.json', scopes)
        except Exception: creds = None
    elif "GOOGLE_TOKEN" in st.secrets:
        try:
            token_info = json.loads(st.secrets["GOOGLE_TOKEN"])
            creds = Credentials.from_authorized_user_info(token_info, scopes)
        except Exception: creds = None
    elif "custom_google_token" in st.session_state and st.session_state.custom_google_token:
        try:
            token_info = json.loads(st.session_state.custom_google_token)
            creds = Credentials.from_authorized_user_info(token_info, scopes)
        except Exception: creds = None

    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

def get_pooled_files(target_dir):
    if not os.path.exists(target_dir): return []
    valid_exts = [".png", ".jpg", ".jpeg", ".pdf"]
    return sorted([f for f in os.listdir(target_dir) if os.path.splitext(f)[4].lower() in valid_exts])

def sync_from_company_drive(folder_id, pool_dir):
    service = get_drive_service()
    if not service: return False, "Google Drive API認証キーが設定されていません。"
    if not folder_id: return False, "フォルダIDが未設定です。"

    synced_ids = []
    if os.path.exists(SYNCED_FILE):
        try:
            with open(SYNCED_FILE, "r", encoding="utf-8") as f: synced_ids = json.load(f)
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
            target_path = os.path.join(pool_dir, item['name'])
            with io.FileIO(target_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = downloader.next_chunk()
            synced_ids.append(item['id'])
            count += 1

        with open(SYNCED_FILE, "w", encoding="utf-8") as f: json.dump(synced_ids, f)
        return True, f"{count} 件の新規領収書を同期しました！"
    except Exception as e:
        return False, f"同期エラー: {str(e)}"

def get_or_create_monthly_folder(service, parent_folder_id, target_month):
    query = f"'{parent_folder_id}' in parents and name = '{target_month}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = service.files().list(q=query, fields="files(id, name)", spaces='drive').execute()
    files = res.get('files', [])
    if files: return files['id']
    folder_metadata = {'name': target_month, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_folder_id]}
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')

def upload_file_to_drive(service, folder_id, file_name, file_bytes, mime_type):
    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    return service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

def extract_month_from_filename_or_mtime(file_path):
    base_name = os.path.basename(file_path)
    match = re.search(r'(202\d)[-_]?(0|1)[-_]?(\d{2})', base_name)
    if match: return f"{match.group(1)}-{match.group(2)}"
    mtime = os.path.getmtime(file_path)
    return datetime.fromtimestamp(mtime).strftime("%Y-%m")

# ==========================================
# 5. PayPay明細パース（ナインゲイツ初期判定基準）
# ==========================================
def parse_paypay_pdf_3companies(file_bytes):
    if not HAS_PYPDF:
        st.error("⚠️ サーバー環境に `pypdf` がインストールされていません。")
        return []

    base_conf = COMPANY_CONFIG["ナインゲイツ"]
    default_pay = safe_first_str(base_conf["payments"], "普通預金")
    records = []
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        full_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t: full_text += t + "\n"
        
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        date_pattern = re.compile(r'^(202\d)[/-](\d{1,2})[/-](\d{1,2})')
        
        idx = 0
        for line in lines:
            m = date_pattern.match(line)
            if m:
                year = m.group(1)
                month = m.group(2).zfill(2)
                day = m.group(3).zfill(2)
                clean_date = f"{year}-{month}-{day}"
                month_str = f"{year}-{month}"
                
                tokens = line.split()
                amounts = []
                summary_tokens = []
                for t in tokens:
                    num_clean = t.replace(",", "").replace("円", "")
                    if num_clean.isdigit() and len(num_clean) >= 2:
                        amounts.append(int(num_clean))
                    elif not re.match(r'^\d{2}:\d{2}', t) and not date_pattern.match(t) and not re.match(r'^\d{5}$', t):
                        summary_tokens.append(t)
                
                amount = 0
                summary = " ".join(summary_tokens).strip()
                if amounts: amount = -amounts
                
                if clean_date and amount != 0:
                    summary_lower = summary.lower()
                    is_dining = any(k.lower() in summary_lower for k in DINING_KEYWORDS)
                    
                    category = "雑費"
                    sub_account = ""
                    tax_type = "課対仕入10%"
                    is_auto_matched = False

                    if is_dining:
                        category = "交際費"
                        is_auto_matched = True

                    for keywords, cat, sub_acc, t_type in base_conf.get("keyword_rules", []):
                        for kw in keywords:
                            if kw.lower() in summary_lower:
                                category = cat
                                sub_account = sub_acc
                                tax_type = t_type
                                is_auto_matched = True
                                break
                        if is_auto_matched: break

                    if not summary: summary = "PayPay銀行普通預金出入金"

                    records.append({
                        "id": f"rec_{idx}",
                        "date": clean_date,
                        "month": month_str,
                        "amount": int(amount),
                        "summary": summary,
                        "company": "ナインゲイツ",
                        "category": category,
                        "sub_account": sub_account,
                        "tax_type": tax_type,
                        "payment": default_pay,
                        "is_dining": is_dining,
                        "is_auto_matched": is_auto_matched,
                        "dining_info": None,
                        "research_memo": ""
                    })
                    idx += 1
        return records
    except Exception as e:
        st.error(f"PayPay銀行PDF明細の解析エラー: {e}")
        return []

def generate_yayoi_csv_for_records(target_records, company_name):
    conf = COMPANY_CONFIG[company_name]
    default_pay = safe_first_str(conf["payments"], "普通預金")
    lines = []
    for row in target_records:
        raw_pay = row.get("payment", default_pay)
        pay_method = safe_first_str(raw_pay, default_pay)
        credit_subj, credit_sub = conf["payment_mapping"].get(pay_method, ("普通預金", ""))
        
        raw_cat = row.get("category", "外注費")
        debit_subj = safe_first_str(raw_cat, "外注費")
        debit_sub = safe_first_str(row.get("sub_account", ""))
        tax_type = safe_first_str(row.get("tax_type", "課対仕入10%"))
        amount = str(abs(row.get("amount", 0)))
        date_str = str(row.get("date", "")).replace("-", "/")
        
        base_summary = safe_first_str(row.get('summary', ''))
        memo_parts = []
        if row.get('research_memo'): memo_parts.append(str(row['research_memo']))
        if row.get('dining_info'):
            d = row['dining_info']
            memo_parts.append(f"[{d['judged_cat']}] {d['partner']} ({d['people']}名/単価¥{d['unit_price']:,}) 目的:{d['purpose']}")
            
        summary_text = f"{base_summary} {' '.join(memo_parts)}".strip()
        cols = [
            "2000", "", "", date_str, debit_subj, debit_sub, "全社", tax_type, amount, "0",
            credit_subj, credit_sub, "全社", "対象外", amount, "0", summary_text, "", "", "NO"
        ]
        lines.append(",".join([f'"{c}"' for c in cols]))
    return "\r\n".join(lines)

# ==========================================
# 6. Streamlit メイン UI
# ==========================================
st.set_page_config(page_title="九門グループ 統合経理・消込＆証憑管理", layout="wide")

st.sidebar.title("🏢 経理くん（統括参謀）")
current_user_email = st.sidebar.selectbox("操作者", list(USERS.keys()), format_func=lambda x: USERS[x]["name"])
selected_company = st.sidebar.selectbox("🏢 領収書登録先 法人", USERS[current_user_email]["companies"])

with st.sidebar.expander("🔑 Google Drive API連携キー設定"):
    custom_token = st.text_area("GOOGLE_TOKEN (JSON文字列)", value="", help="token.jsonの内容を貼り付けるとDrive同期・自動保管が有効化されます。")
    if custom_token:
        st.session_state.custom_google_token = custom_token
        st.success("APIキーを受領しました")

st.title("🏢 九門グループ 統合経理・証憑管理＆3社合同消込システム")

# 2大主要機能のタブ構成
main_tab_receipt, main_tab_bank = st.tabs([
    "📑 ① 未処理領収書の管理・プレビュー・登録",
    "🏦 ② PayPay銀行口座明細消込 ＆ 3社合同仕訳"
])

# =========================================================================
# タブ 1: 領収書管理・プレビュー・仕訳登録（完全復元）
# =========================================================================
with main_tab_receipt:
    st.subheader(f"📑 未処理領収書プール（対象法人: {selected_company}）")
    
    with st.expander("☁️ Google ドライブから領収書を同期する", expanded=False):
        st.markdown(f"**対象法人: `{selected_company}` の1次読込フォルダ**")
        folder_id = COMPANY_CONFIG[selected_company]["input_folder_id"]
        st.info(f"[suspicious link removed]{folder_id}")
        if st.button("🔄 Google ドライブから同期を実行", type="primary", key="sync_btn_tab1"):
            with st.spinner("同期中..."):
                ok, msg = sync_from_company_drive(folder_id, DEFAULT_POOL_DIR)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)

    pooled_files = get_pooled_files(DEFAULT_POOL_DIR)
    if not pooled_files:
        st.info("💡 現在未処理プール（receipt_pool）に未処理の領収書はありません。「Google ドライブから同期」を実行するか、ファイルを配置してください。")
    else:
        st.success(f"🎯 未処理の領収書: **残り {len(pooled_files)} 件**")
        target_file = pooled_files
        target_path = os.path.join(DEFAULT_POOL_DIR, target_file)
        ext = os.path.splitext(target_file)[4].lower()

        c_view, c_form = st.columns([4])
        with c_view:
            st.caption(f"プレビュー表示中: `{target_file}`")
            if ext in [".png", ".jpg", ".jpeg"]:
                try:
                    img = Image.open(target_path)
                    st.image(img, use_container_width=True)
                except Exception as e:
                    st.error(f"画像読み込みエラー: {e}")
            elif ext == ".pdf":
                st.info("📄 PDF形式の領収書・証憑です。")
                with open(target_path, "rb") as f:
                    st.download_button("📥 このPDFを開く／ダウンロード", f.read(), file_name=target_file)
            
            if st.button("🗑️ この領収書をスキップして破棄", key="del_pooled_file"):
                os.remove(target_path)
                st.warning("ファイルを破棄しました。")
                st.rerun()

        with c_form:
            st.markdown("### 📝 領収書の内容を確認して登録")
            comp_conf = COMPANY_CONFIG[selected_company]
            with st.form("manual_receipt_form"):
                rec_date = st.date_input("領収書日付", value=date.today())
                store_name = st.text_input("支払先・店舗名*", value=os.path.splitext(target_file))
                
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    sel_cat = st.selectbox("勘定科目", comp_conf["categories"])
                    sel_pay = st.selectbox("決済手段", comp_conf["payments"])
                with col_f2:
                    rec_amount = st.number_input("支払金額（税込・円）*", min_value=0, step=100, value=0)
                    sel_tax = st.selectbox("税率", ["課対仕入10%", "課対仕入8%(軽)", "対象外"])
                
                rec_memo = st.text_input("用途・メモ（相手先・目的など）", placeholder="例: USEN 山田常務 ライセンス打合せ")
                
                submit_receipt = st.form_submit_button(f"✅ 【{selected_company}】の経費として確定保存", type="primary")
                if submit_receipt:
                    if rec_amount <= 0 or not store_name.strip():
                        st.error("支払先と金額を入力してください！")
                    else:
                        dest_dir = os.path.join(BASE_UPLOAD_DIR, comp_conf["code"])
                        os.makedirs(dest_dir, exist_ok=True)
                        dest_file_path = os.path.join(dest_dir, target_file)
                        shutil.move(target_path, dest_file_path)
                        st.success(f"領収書 `{target_file}` を確定保存しました！")
                        st.rerun()

# =========================================================================
# タブ 2: PayPay銀行口座明細消込 ＆ 3社合同仕訳
# =========================================================================
with main_tab_bank:
    st.subheader("🏦 PayPay銀行 取引明細PDFの投入 ＆ 3社合同仕訳消込")
    st.caption("【初期基準】ナインゲイツの標準勘定科目で自動分類し、各行でシュガー・SF企画へ自由振替可能")
    
    uploaded_statement = st.file_uploader("PayPay銀行の取引明細PDFを選択してください", type=["pdf"], key="pdf_bank_upload")

    if "transactions_3comp" not in st.session_state:
        st.session_state.transactions_3comp = []

    if uploaded_statement:
        file_bytes = uploaded_statement.read()
        if not st.session_state.transactions_3comp:
            st.session_state.transactions_3comp = parse_paypay_pdf_3companies(file_bytes)

    if st.session_state.get("transactions_3comp"):
        records = st.session_state.transactions_3comp
        st.info(f"📊 明細解析完了: 合計 **{len(records)} 件** ｜ ナインゲイツ標準ルールで初期分類済")

        st.subheader("② 【3社合同仕訳テーブル】会社選択 ＆ 勘定科目調整")
        for r in records:
            abs_amt = abs(r["amount"])
            with st.expander(f"[{r['company']}] {r['date']} ｜ {r['summary']} ｜ ¥{abs_amt:,} ｜ 科目: {r['category']}", expanded=not r.get("is_auto_matched", False)):
                col1, col2, col3, col4 = st.columns([1.5, 2, 2.5, 1])
                with col1:
                    comp_list = ["ナインゲイツ", "シュガー", "SF企画"]
                    cur_comp_idx = comp_list.index(r["company"]) if r["company"] in comp_list else 0
                    new_comp = st.selectbox("🏢 帰属会社", comp_list, index=cur_comp_idx, key=f"c_sel_{r['id']}")
                    if new_comp != r["company"]:
                        r["company"] = new_comp
                        r["category"] = COMPANY_CONFIG[new_comp]["categories"]
                        r["payment"] = COMPANY_CONFIG[new_comp]["payments"]
                        st.rerun()

                with col2:
                    cat_options = COMPANY_CONFIG[r["company"]]["categories"]
                    cur_cat_idx = cat_options.index(r["category"]) if r["category"] in cat_options else 0
                    r["category"] = st.selectbox("勘定科目", cat_options, index=cur_cat_idx, key=f"cat_{r['id']}")

                with col3:
                    r["research_memo"] = st.text_input("業務・税務メモ", value=r.get("research_memo", ""), key=f"memo_{r['id']}")

                with col4:
                    st.write("")
                    st.write("")
                    if st.button("確定", key=f"ok_{r['id']}", use_container_width=True):
                        r["is_auto_matched"] = True
                        st.success("反映完了")
                        st.rerun()

        # サマリープレビュー
        st.subheader("📋 3社合同プレビュー一覧")
        preview_rows = []
        for r in records:
            preview_rows.append({
                "日付": r["date"],
                "金額": r["amount"],
                "摘要": r["summary"],
                "🏢 帰属会社": r["company"],
                "勘定科目": r["category"],
                "決済口座": r["payment"],
                "税務メモ": r.get("research_memo", "")
            })
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

        # 3社個別：弥生仕訳CSV出力タブ
        st.markdown("---")
        st.subheader("③ 【会社別】弥生仕訳CSVダウンロード")

        comp_groups = {"ナインゲイツ": [], "シュガー": [], "SF企画": []}
        for r in records:
            comp_groups[r["company"]].append(r)

        tab_ng, tab_sg, tab_sf = st.tabs([
            f"🏢 ナインゲイツ ({len(comp_groups['ナインゲイツ'])}件)",
            f"🏢 シュガー ({len(comp_groups['シュガー'])}件)",
            f"🏢 SF企画 ({len(comp_groups['SF企画'])}件)"
        ])

        for tab, c_name in [(tab_ng, "ナインゲイツ"), (tab_sg, "シュガー"), (tab_sf, "SF企画")]:
            with tab:
                c_recs = comp_groups[c_name]
                if c_recs:
                    csv_str = generate_yayoi_csv_for_records(c_recs, c_name)
                    try: csv_bytes = csv_str.encode("cp932", errors="replace")
                    except Exception: csv_bytes = csv_str.encode("utf-8-sig")
                    st.download_button(
                        label=f"📥 【{c_name}】弥生仕訳CSVをダウンロード ({len(c_recs)}件)",
                        data=csv_bytes,
                        file_name=f"弥生仕訳_{COMPANY_CONFIG[c_name]['code']}.csv",
                        mime="text/csv",
                        key=f"dl_btn_{c_name}"
                    )
                else:
                    st.caption(f"{c_name} に割り振られた取引はありません。")

        # Google Drive 3社自動配送
        if st.button("📁 ④ 3社のGoogle Drive親フォルダへ仕訳CSVを一括自動配送", type="primary", use_container_width=True):
            service = get_drive_service()
            if not service:
                st.warning("⚠️ Google Drive API認証キーが未設定です。上のタブから各社CSVを直接ダウンロードしてください。")
            else:
                with st.spinner("3社のGoogle Drive親フォルダへ自動振り分け配送中..."):
                    try:
                        res_msgs = []
                        for c_name, c_recs in comp_groups.items():
                            if c_recs:
                                parent_fid = COMPANY_CONFIG[c_name]["output_folder_id"]
                                c_csv = generate_yayoi_csv_for_records(c_recs, c_name)
                                try: c_bytes = c_csv.encode("cp932", errors="replace")
                                except Exception: c_bytes = c_csv.encode("utf-8-sig")
                                upload_file_to_drive(service, parent_fid, f"弥生仕訳_{COMPANY_CONFIG[c_name]['code']}.csv", c_bytes, "text/csv")
                                res_msgs.append(f"✅ **{c_name}**: {len(c_recs)} 件の仕訳CSVを保管完了")
                        st.success("🎉 3社一括配送が完了しました！\n\n" + "\n".join(res_msgs))
                    except Exception as e:
                        st.error(f"Drive配送エラー: {str(e)}")
