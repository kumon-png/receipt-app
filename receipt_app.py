import streamlit as st
import pandas as pd
import json
import os
import io
import re
from datetime import datetime, date
from PIL import Image

# pypdfの遅延安全インポート（未インストール時のクラッシュ防止）
try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ==========================================
# 1. ユーザー定義（全員全操作可能）
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
    "珈琲", "レストラン", "割烹", "料理", "酒場", "スターバックス", "ドトール"
]

# ==========================================
# 3. 各法人設定・口座マスタ（支店番号-口座番号完全連動）
# ==========================================
COMPANY_CONFIG = {
    "ナインゲイツ": {
        "code": "ninegates",
        "fiscal_start": 4,
        "input_folder_id": "1upG2C-m-An3VcI1ULE7A6BwHipRzIjge",
        "output_folder_id": "1xtj1g42RSwOa_eUATF89qLdS_JiM_yQ8",
        "categories": ["外注費", "仕入高", "仕入高（8%軽）", "旅費交通費", "消耗品費", "車両費", "通信費", "会議費", "交際費", "地代家賃", "水道光熱費", "支払手数料", "法定福利費", "福利厚生費", "雑費"],
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
            (["ケーティーエス", "kts"], "外注費", "", "課対仕入10%"),
            (["鳥取通信工業", "鳥取通信"], "外注費", "", "課対仕入10%"),
            (["ベッセル"], "外注費", "", "課対仕入10%"),
            (["エルワイコンサル"], "外注費", "", "課対仕入10%"),
            (["アイデン"], "外注費", "", "課対仕入10%"),
            (["ミカモ電気"], "外注費", "", "課対仕入10%"),
            (["アルテック"], "外注費", "", "課対仕入10%"),
            (["シュガー", "sugar"], "外注費", "合同会社シュガー", "課対仕入10%"),
            (["サイボウズ", "cybozu"], "通信費", "", "課対仕入10%"),
            (["adobe"], "通信費", "", "課対仕入10%"),
            (["ドコモ", "docomo"], "通信費", "", "課対仕入10%"),
            (["キユウユダイ", "給油", "eneos"], "車両費", "ガソリン代", "課対仕入10%"),
            (["ホウジンetc", "etc", "高速情報協同組合"], "車両費", "高速代", "課対仕入10%"),
            (["jr", "新幹線"], "旅費交通費", "JR", "課対仕入10%"),
            (["楽天トラベル", "ホテル"], "旅費交通費", "ホテル宿泊", "課対仕入10%"),
            (["アマゾン", "amazon"], "消耗品費", "", "課対仕入10%"),
            (["コーナン", "kohnan"], "消耗品費", "", "課対仕入10%")
        ]
    },
    "シュガー": {
        "code": "sugar",
        "fiscal_start": 6,
        "input_folder_id": "1qo5FqrpHDFgY4tzf32YaYbFQB6wCQ9Ih",
        "output_folder_id": "19HhywRqfSRG2tWMVzDkcw6DlmCMGLgSI",
        "categories": ["外注費", "仕入高（8%軽）", "仕入高（10%）", "地代家賃", "旅費交通費", "消耗品費", "支払手数料", "荷造運賃", "リース料", "雑費", "開業費"],
        "payments": [
            "普通預金（呉信用金庫 020-1096139）",
            "普通預金（広島市信用組合 117-0878367）",
            "普通預金（PayPay銀行 005-5332515）",
            "普通預金（PayPay法人 005-5332523）",
            "役員立替（PayPay個人 003-2060281）",
            "役員立替（楽天個人 214-4383608）",
            "クレジットカード（未払金）",
            "現金"
        ],
        "payment_mapping": {
            "普通預金（呉信用金庫 020-1096139）": ("普通預金", "呉信用金庫"),
            "普通預金（広島市信用組合 117-0878367）": ("普通預金", "広島市信用組合"),
            "普通預金（PayPay銀行 005-5332515）": ("普通預金", "PayPay銀行(5332515)"),
            "普通預金（PayPay法人 005-5332523）": ("普通預金", "PayPay法人(5332523)"),
            "役員立替（PayPay個人 003-2060281）": ("短期借入金", "クモンヒサシ(PayPay)"),
            "役員立替（楽天個人 214-4383608）": ("短期借入金", "クモンヒサシ(楽天)"),
            "クレジットカード（未払金）": ("未払金", ""),
            "現金": ("現金", "")
        },
        "keyword_rules": [
            (["ナインゲイツ", "ninegates"], "外注費", "株式会社ナインゲイツ", "課対仕入10%"),
            (["usenテクノサービス", "usen"], "外注費", "", "課対仕入10%"),
            (["wannaeat", "食材"], "仕入高（8%軽）", "", "課対仕入8%(軽)")
        ]
    },
    "SF企画": {
        "code": "sf_kikaku",
        "fiscal_start": 8,
        "input_folder_id": "1BZrjf_kq_kNLsXoOOMfRxUKiJSydC5Qa",
        "output_folder_id": "1VuS4VHIPpNG8HPbARq4xkkDUdE_wN8U6",
        "categories": ["① 旅費交通費・車両維持費", "② 会議費・接待交際費", "③ 通信費・IT・クラウド利用料", "④ 地代家賃・水道光熱費", "⑤ 調査研究費・消耗品費", "⑥ 支払手数料・租税公課", "開業費（繰延資産）"],
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
        },
        "keyword_rules": [
            (["google play", "googleplay", "app store", "apple"], "⑤ 調査研究費・消耗品費", "AnimaCast開発", "課対仕入10%"),
            (["u-next", "unext", "netflix", "アマゾンプライム"], "⑤ 調査研究費・消耗品費", "ストリーミングUI研究", "課対仕入10%"),
            (["square enix", "スクエニ", "ドラクエ", "任天堂", "steam"], "⑤ 調査研究費・消耗品費", "ゲーム内経済モデル研究", "課対仕入10%"),
            (["google", "gcp", "サイボウズ", "クラウド", "ドメイン"], "③ 通信費・IT・クラウド利用料", "", "課対仕入10%"),
            (["jr", "新幹線", "タクシー"], "① 旅費交通費・車両維持費", "", "課対仕入10%"),
            (["特許", "弁理士", "司法書士", "振込手数料"], "⑥ 支払手数料・租税公課", "", "課対仕入10%")
        ]
    }
}

DEFAULT_POOL_DIR = "receipt_pool"
SYNCED_FILE = "drive_synced.json"
MASTER_FILE = "vendor_master.xlsx"

os.makedirs(DEFAULT_POOL_DIR, exist_ok=True)

# ==========================================
# 4. Google Drive API 関数
# ==========================================
def get_drive_service():
    scopes = ['[suspicious link removed]']
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes)
    elif "GOOGLE_TOKEN" in st.secrets:
        token_info = json.loads(st.secrets["GOOGLE_TOKEN"])
        creds = Credentials.from_authorized_user_info(token_info, scopes)
    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

def get_pooled_files(target_dir):
    if not os.path.exists(target_dir): return []
    valid_exts = [".png", ".jpg", ".jpeg", ".pdf"]
    return sorted([f for f in os.listdir(target_dir) if os.path.splitext(f).lower() in valid_exts])

def sync_from_company_drive(folder_id, pool_dir):
    service = get_drive_service()
    if not service:
        return False, "Google Drive認証情報が見つかりません。"
    if not folder_id:
        return False, "1次フォルダIDが設定されていません。"

    synced_ids = []
    if os.path.exists(SYNCED_FILE):
        try:
            with open(SYNCED_FILE, "r", encoding="utf-8") as f:
                synced_ids = json.load(f)
        except Exception:
            synced_ids = []

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

        with open(SYNCED_FILE, "w", encoding="utf-8") as f:
            json.dump(synced_ids, f)
        return True, f"{count} 件の新規領収書を取り込みました！"
    except Exception as e:
        return False, f"同期エラー: {str(e)}"

def get_or_create_monthly_folder(service, parent_folder_id, target_month):
    query = f"'{parent_folder_id}' in parents and name = '{target_month}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = service.files().list(q=query, fields="files(id, name)", spaces='drive').execute()
    files = res.get('files', [])
    if files:
        return files[0]['id']
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
    if match:
        year, month = match.group(1), match.group(2)
        return f"{year}-{month}"
    mtime = os.path.getmtime(file_path)
    return datetime.fromtimestamp(mtime).strftime("%Y-%m")

# ==========================================
# 5. 明細パース（PDF ＆ CSV 安全両対応）
# ==========================================
def parse_paypay_pdf(file_bytes, company_name):
    """PayPay銀行 公式取引明細PDFから取引行を抽出"""
    if not HAS_PYPDF:
        st.error("⚠️ サーバー環境に `pypdf` がインストールされていません。GitHubの requirements.txt に pypdf を追加してください。")
        return []

    conf = COMPANY_CONFIG[company_name]
    default_pay = conf["payments"][0] if conf["payments"] else "普通預金"
    records = []
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        full_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"
        
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
                    elif not re.match(r'^\d{2}:\d{2}', t) and not date_pattern.match(t):
                        summary_tokens.append(t)
                
                amount = 0
                summary = " ".join(summary_tokens)
                if amounts:
                    amount = -amounts[0]
                
                if clean_date and amount != 0:
                    summary_lower = summary.lower()
                    is_dining = any(k.lower() in summary_lower for k in DINING_KEYWORDS)
                    
                    auto_memo = ""
                    if company_name == "SF企画":
                        if any(k in summary_lower for k in ["google play", "app store", "apple"]):
                            auto_memo = "[研究日報] AnimaCast：課金API・決済UI検証"
                        elif any(k in summary_lower for k in ["u-next", "netflix", "プライム"]):
                            auto_memo = "[研究日報] 映像配信UI/UXストリーミング検証"
                        elif any(k in summary_lower for k in ["ドラクエ", "任天堂", "steam", "square"]):
                            auto_memo = "[研究日報] AnimaCast：ゲーム内経済循環調査"

                    category = conf["categories"][0] if conf["categories"] else "雑費"
                    sub_account = ""
                    tax_type = "課対仕入10%"

                    if is_dining:
                        category = "交際費" if company_name != "SF企画" else "② 会議費・接待交際費"

                    for keywords, cat, sub_acc, t_type in conf.get("keyword_rules", []):
                        for kw in keywords:
                            if kw.lower() in summary_lower:
                                category, sub_account, tax_type = cat, sub_acc, t_type
                                break

                    records.append({
                        "id": f"pdf_rec_{idx}",
                        "date": clean_date,
                        "month": month_str,
                        "amount": int(amount),
                        "summary": summary if summary else "普通預金出入金",
                        "category": category,
                        "sub_account": sub_account,
                        "tax_type": tax_type,
                        "payment": default_pay,
                        "is_dining": is_dining,
                        "dining_info": None,
                        "research_memo": auto_memo
                    })
                    idx += 1
        return records
    except Exception as e:
        st.error(f"PayPay銀行PDF明細の解析エラー: {e}")
        return []

def parse_paypay_csv(file_bytes, company_name):
    conf = COMPANY_CONFIG[company_name]
    default_pay = conf["payments"][0] if conf["payments"] else "普通預金"
    try:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8")
        except Exception:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="shift_jis")
        
        df.columns = [str(c).strip() for c in df.columns]
        
        records = []
        for idx, row in df.iterrows():
            row_dict = {str(k).strip(): str(v).strip() for k, v in row.items()}
            
            date_val = ""
            if "操作日(年)" in row_dict and "操作日(月)" in row_dict and "操作日(日)" in row_dict:
                y = row_dict["操作日(年)"].replace(".0", "").strip()
                m = row_dict["操作日(月)"].replace(".0", "").strip().zfill(2)
                d = row_dict["操作日(日)"].replace(".0", "").strip().zfill(2)
                if y != "nan" and m != "nan" and d != "nan" and len(y) == 4:
                    date_val = f"{y}-{m}-{d}"
            
            if not date_val:
                for c in ["取引日", "日付", "年月日", "取引日時"]:
                    if c in row_dict and row_dict[c] != "nan":
                        date_val = row_dict[c].replace("/", "-")[:10]
                        break
            
            out_amt = "0"
            for out_col in ["お支払金額", "出金金額(円)", "出金額", "出金"]:
                if out_col in row_dict and row_dict[out_col] != "nan" and row_dict[out_col].strip():
                    out_amt = row_dict[out_col]
                    break
                    
            in_amt = "0"
            for in_col in ["お預り金額", "入金金額(円)", "入金額", "入金"]:
                if in_col in row_dict and row_dict[in_col] != "nan" and row_dict[in_col].strip():
                    in_amt = row_dict[in_col]
                    break
            
            try:
                out_val = float(str(out_amt).replace(",", "").replace("円", "")) if out_amt != "nan" else 0
                in_val = float(str(in_amt).replace(",", "").replace("円", "")) if in_amt != "nan" else 0
                amount = in_val if in_val > 0 else -out_val
            except Exception:
                amount = 0
            
            summary = ""
            for c in ["摘要", "お取引内容", "取引内容", "振込人名", "支払先"]:
                if c in row_dict and row_dict[c] != "nan":
                    summary = row_dict[c]
                    break
            
            if date_val and amount != 0:
                summary_lower = summary.lower()
                is_dining = any(k.lower() in summary_lower for k in DINING_KEYWORDS)
                
                auto_memo = ""
                if company_name == "SF企画":
                    if any(k in summary_lower for k in ["google play", "app store", "apple"]):
                        auto_memo = "[研究日報] AnimaCast：課金API・決済UI検証"
                    elif any(k in summary_lower for k in ["u-next", "netflix", "プライム"]):
                        auto_memo = "[研究日報] 映像配信UI/UXストリーミング検証"
                    elif any(k in summary_lower for k in ["ドラクエ", "任天堂", "steam", "square"]):
                        auto_memo = "[研究日報] AnimaCast：ゲーム内経済循環調査"

                category = conf["categories"][0] if conf["categories"] else "雑費"
                sub_account = ""
                tax_type = "課対仕入10%"

                if is_dining:
                    category = "交際費" if company_name != "SF企画" else "② 会議費・接待交際費"

                for keywords, cat, sub_acc, t_type in conf.get("keyword_rules", []):
                    for kw in keywords:
                        if kw.lower() in summary_lower:
                            category, sub_account, tax_type = cat, sub_acc, t_type
                            break

                clean_date = date_val[:10]
                records.append({
                    "id": f"rec_{idx}",
                    "date": clean_date,
                    "month": clean_date[:7],
                    "amount": int(amount),
                    "summary": summary,
                    "category": category,
                    "sub_account": sub_account,
                    "tax_type": tax_type,
                    "payment": default_pay,
                    "is_dining": is_dining,
                    "dining_info": None,
                    "research_memo": auto_memo
                })
        return records
    except Exception as e:
        st.error(f"PayPay銀行CSVの解析エラー: {e}")
        return []

def generate_yayoi_csv_for_records(target_records, company_name):
    conf = COMPANY_CONFIG[company_name]
    default_pay = conf["payments"][0] if conf["payments"] else "普通預金"
    lines = []
    for row in target_records:
        pay_method = row.get("payment", default_pay)
        # 文字列であることを保証
        if isinstance(pay_method, list):
            pay_method = pay_method[0] if len(pay_method) > 0 else default_pay
            
        credit_subj, credit_sub = conf["payment_mapping"].get(pay_method, ("普通預金", ""))
        debit_subj = row.get("category", "外注費")
        debit_sub = row.get("sub_account", "")
        tax_type = row.get("tax_type", "課対仕入10%")
        amount = str(abs(row.get("amount", 0)))
        date_str = row.get("date", "").replace("-", "/")
        
        base_summary = row.get('summary', '')
        memo_parts = []
        if row.get('research_memo'):
            memo_parts.append(row['research_memo'])
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
st.set_page_config(page_title="九門グループ 統合経理・消込＆Drive自動保管", layout="wide")

st.sidebar.title("🏢 経理くん")
current_user_email = st.sidebar.selectbox("操作者選択", list(USERS.keys()), format_func=lambda x: USERS[x]["name"])
selected_company = st.sidebar.selectbox("🏢 対象法人", USERS[current_user_email]["companies"])

company_conf = COMPANY_CONFIG[selected_company]
current_input_folder_id = company_conf["input_folder_id"]
current_output_folder_id = company_conf["output_folder_id"]

st.sidebar.markdown(f"**📂 1次読込フォルダID:**\n`{current_input_folder_id}`")
st.sidebar.markdown(f"**📁 出力先親フォルダID:**\n`{current_output_folder_id}`")

st.title("🏢 経理自動仕訳・消込・Drive月別保管")

# ------------------------------------------
# ☁️ Google ドライブから領収書を同期する
# ------------------------------------------
with st.expander("☁️ Google ドライブから領収書を同期する", expanded=True):
    st.markdown(f"**対象法人: `{selected_company}` の1次読込フォルダ**")
    st.info(f"[suspicious link removed]{current_input_folder_id}")

    col_sync1, col_sync2 = st.columns(2)
    with col_sync1:
        pooled_files = get_pooled_files(DEFAULT_POOL_DIR)
        if pooled_files:
            st.success(f"💡 現在 receipt_pool に **{len(pooled_files)} 件** の領収書ファイルが格納されています。")
        else:
            st.warning("💡 現在 receipt_pool に未処理ファイルはありません。「Google ドライブから同期」を実行してください。")
    with col_sync2:
        if st.button("🔄 Google ドライブから同期", type="primary", use_container_width=True):
            with st.spinner(f"{selected_company} の1次フォルダからファイルを取得中..."):
                ok, msg = sync_from_company_drive(current_input_folder_id, DEFAULT_POOL_DIR)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

st.markdown("---")

# ------------------------------------------
# メイン処理：PayPay銀行 明細アップロード（PDF / CSV 両対応）
# ------------------------------------------
st.subheader("① PayPay銀行 口座明細をアップロード（PDFまたはCSV・複数月混在可）")
uploaded_statement = st.file_uploader(
    "PayPay銀行の取引明細ファイル（PDF または CSV）を選択してください", 
    type=["pdf", "csv"]
)

if "transactions" not in st.session_state or st.session_state.get("last_company") != selected_company:
    st.session_state.transactions = []
    st.session_state.last_company = selected_company

if uploaded_statement:
    file_bytes = uploaded_statement.read()
    if uploaded_statement.name.lower().endswith(".pdf"):
        st.session_state.transactions = parse_paypay_pdf(file_bytes, selected_company)
    else:
        st.session_state.transactions = parse_paypay_csv(file_bytes, selected_company)

if st.session_state.get("transactions"):
    records = st.session_state.transactions
    
    monthly_groups = {}
    for r in records:
        m = r["month"]
        if m not in monthly_groups:
            monthly_groups[m] = []
        monthly_groups[m].append(r)
    
    detected_months = sorted(list(monthly_groups.keys()))
    st.info(f"📊 明細解析完了: 合計 **{len(records)} 件** ｜ 検出月: **{', '.join(detected_months)}** ({len(detected_months)}ヶ月分を自動判別)")

    # ----------------------------------------------------
    # 🍽️ 飲食・会食検知行の自動表示（10,000円判定）
    # ----------------------------------------------------
    dining_candidates = [r for r in records if r["is_dining"]]
    if dining_candidates:
        st.warning(f"🍽️ **会食・飲食の可能性がある取引が {len(dining_candidates)} 件 検出されました！**\n1人あたり10,000円基準で「会議費」か「交際費」かを自動判定します。税務署監査対策のためメモを入力してください。")
        
        for r in dining_candidates:
            abs_amount = abs(r["amount"])
            with st.expander(f"📝 【要入力】 [{r['month']}] {r['date']} | {r['summary']} | ¥{abs_amount:,}", expanded=(r["dining_info"] is None)):
                c_d1, c_d2 = st.columns(2)
                with c_d1:
                    people = st.number_input(f"参加人数 (合計)", min_value=1, value=2, step=1, key=f"p_{r['id']}")
                    unit_p = int(abs_amount / people)
                    if unit_p <= 10000:
                        judged = "会議費"
                        st.success(f"判定: **会議費（全額損金）**\n単価: ¥{unit_p:,} ≦ ¥10,000")
                    else:
                        judged = "交際費"
                        st.warning(f"判定: **接待交際費**\n単価: ¥{unit_p:,} > ¥10,000")
                
                with c_d2:
                    partner = st.text_input("相手先企業・氏名（例: USEN 山田常務）", key=f"part_{r['id']}")
                    purpose = st.text_input("飲食の目的（例: ライセンス打合せ）", key=f"purp_{r['id']}")
                    if st.button("💾 この内容で税務メモを確定", key=f"btn_{r['id']}"):
                        if not partner.strip() or not purpose.strip():
                            st.error("税務署対策のため相手先と目的は必須です！")
                        else:
                            r["dining_info"] = {
                                "judged_cat": judged,
                                "people": people,
                                "unit_price": unit_p,
                                "partner": partner,
                                "purpose": purpose
                            }
                            if selected_company == "SF企画":
                                r["category"] = "② 会議費・接待交際費"
                            else:
                                r["category"] = judged
                            st.success("✅ 税務メモを反映しました！")
                            st.rerun()

    st.subheader("📋 月別自動仕訳プレビュー")
    preview_data = []
    for r in records:
        memo_str = r.get("research_memo", "")
        if r.get("dining_info"):
            d = r["dining_info"]
            memo_str = f"[{d['judged_cat']}] {d['partner']} ({d['people']}名/単価¥{d['unit_price']:,})"
        preview_data.append({
            "対象月": r["month"],
            "日付": r["date"],
            "金額": r["amount"],
            "摘要": r["summary"],
            "勘定科目": r["category"],
            "決済口座": r["payment"],
            "税務メモ": memo_str
        })
    st.dataframe(pd.DataFrame(preview_data), use_container_width=True)

    st.markdown("---")
    st.subheader(f"📥 複数月一括：弥生仕訳CSV出力 ＆ ④ 各月Driveフォルダ自動配送")

    dl_tabs = st.tabs([f"📥 {m} 弥生CSV" for m in detected_months])
    for idx, m in enumerate(detected_months):
        with dl_tabs[idx]:
            m_records = monthly_groups[m]
            m_csv_str = generate_yayoi_csv_for_records(m_records, selected_company)
            try:
                m_csv_bytes = m_csv_str.encode("cp932", errors="replace")
            except Exception:
                m_csv_bytes = m_csv_str.encode("utf-8-sig")
            st.download_button(
                label=f"📥 【{m}分】弥生仕訳CSVをダウンロード ({len(m_records)}件)",
                data=m_csv_bytes,
                file_name=f"弥生仕訳_{company_conf['code']}_{m}.csv",
                mime="text/csv",
                key=f"dl_{m}"
            )

    if st.button("📁 ④ 複数月のGoogle Driveフォルダへ一括自動配送・保存を実行", type="primary", use_container_width=True):
        service = get_drive_service()
        parent_id = current_output_folder_id

        if not service:
            st.error("Google Drive API認証情報が見つかりません。")
        else:
            with st.spinner(f"Google Drive（{selected_company}経理くんデータ）へ各月ごとに自動配送中..."):
                try:
                    summary_msg = []
                    for m in detected_months:
                        m_records = monthly_groups[m]
                        m_folder_id = get_or_create_monthly_folder(service, parent_id, m)
                        m_csv_str = generate_yayoi_csv_for_records(m_records, selected_company)
                        try:
                            m_csv_bytes = m_csv_str.encode("cp932", errors="replace")
                        except Exception:
                            m_csv_bytes = m_csv_str.encode("utf-8-sig")
                        
                        upload_file_to_drive(service, m_folder_id, f"弥生仕訳_{company_conf['code']}_{m}.csv", m_csv_bytes, "text/csv")
                        
                        log_text = (
                            f"【九門グループ経理消込・保管実行ログ】\n"
                            f"対象会社: {selected_company}\n対象月: {m}\n"
                            f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"処理仕訳件数: {len(m_records)} 件\n"
                        )
                        upload_file_to_drive(service, m_folder_id, f"消込実行ログ_{m}.txt", log_text.encode("utf-8"), "text/plain")
                        summary_msg.append(f"📁 **{m}** フォルダ: 仕訳CSV ({len(m_records)}件) 格納")

                    pooled_files = get_pooled_files(DEFAULT_POOL_DIR)
                    receipt_dist_count = {m: 0 for m in detected_months}
                    unclassified_count = 0

                    m_folder_ids = {m: get_or_create_monthly_folder(service, parent_id, m) for m in detected_months}

                    for fname in pooled_files:
                        fpath = os.path.join(DEFAULT_POOL_DIR, fname)
                        if os.path.isfile(fpath):
                            f_month = extract_month_from_filename_or_mtime(fpath)
                            target_m = f_month if f_month in m_folder_ids else detected_months[-1]
                            target_fid = m_folder_ids[target_m]
                            
                            mime = "application/pdf" if fname.lower().endswith(".pdf") else "image/jpeg"
                            with open(fpath, "rb") as rf:
                                upload_file_to_drive(service, target_fid, fname, rf.read(), mime)
                            os.remove(fpath)
                            
                            if f_month in receipt_dist_count:
                                receipt_dist_count[f_month] += 1
                            else:
                                unclassified_count += 1

                    for m, cnt in receipt_dist_count.items():
                        if cnt > 0:
                            summary_msg.append(f"📎 **{m}** フォルダ: 領収書 {cnt} 件 移動完了")
                    if unclassified_count > 0:
                        summary_msg.append(f"📎 最新月フォルダへ保管された証憑: {unclassified_count} 件")

                    st.success("🎉 全処理完了！複数月の仕訳CSVおよび領収書を各Drive月別フォルダへ自動仕分け・移動しました！\n\n" + "\n".join(summary_msg))
                    st.session_state.transactions = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Google Drive一括保存エラー: {str(e)}")
