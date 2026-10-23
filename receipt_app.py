import streamlit as st
import pandas as pd
import json
import os
import shutil
import io
import re
from datetime import datetime, date
from PIL import Image

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ==========================================
# 0. 型安全ヘルパー関数
# ==========================================
def safe_first_str(val, fallback=""):
    if isinstance(val, (list, tuple)):
        return str(val[0]) if len(val) > 0 else fallback
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
# 2. 九門グループ 3社完全共通 網羅勘定科目マスター
# ==========================================
UNIFIED_ALL_CATEGORIES = [
    # --- 売上・入金・回収系 ---
    "売上高",
    "売掛金",
    "雑収入",
    "受取利息",
    "役員借入金（代表立替・借入）",
    
    # --- 原価・仕入・外注系 ---
    "外注費",
    "買掛金",
    "仕入高（10%）",
    "仕入高（8%軽）",
    
    # --- 営業・販売促進・研究系 ---
    "広告宣伝費",
    "調査研究費（AnimaCast等）",
    "旅費交通費",
    "交際費",
    "会議費",
    "消耗品費",
    "新聞図書費",
    "通信費",
    "車両費",
    
    # --- 管理・施設・公課・その他 ---
    "地代家賃",
    "水道光熱費",
    "支払手数料",
    "諸会費",
    "保険料",
    "法定福利費",
    "福利厚生費",
    "租税公課",
    "減価償却費",
    "雑費",
    "開業費"
]

# ==========================================
# 3. 九門グループ 3社合同 高度自動仕訳マッチングルール
# ==========================================
AUTO_MATCH_RULES = [
    # ① Akari cafe 宇品 → 広告宣伝費（toridoriマーケティング）
    (["akari cafe", "akaricafe", "アカリカフェ", "あかりカフェ"], 
     "広告宣伝費", "課対仕入10%", "[販促] toridoriマーケティング（Akari cafe宇品）"),

    # ② リビング・ユー → 交際費
    (["リビング・ユー", "リビングユー", "living you"], 
     "交際費", "課対仕入10%", "[会食交際] リビング・ユー 取引先打合せ"),

    # ③ フレスタ → 仕入高（10%） メモ（アカリカフェ材料費）
    (["フレスタ", "fresta"], 
     "仕入高（10%）", "課対仕入10%", "アカリカフェ材料費"),

    # ④ MITSUINOREPARK / 三井のリパーク → 旅費交通費 メモ（駐車代金）
    (["mitsuinorepark", "mitsuino repark", "三井のリパーク", "リパーク"], 
     "旅費交通費", "課対仕入10%", "[交通費] 駐車代金（三井のリパーク）"),

    # 広告宣伝費
    (["タベログ", "tabelog", "indeed", "インディード", "tjhiroshima", "アドプレックス", "facebook ads", "google ads", "広告"], 
     "広告宣伝費", "課対仕入10%", "[販促] 広告宣伝掲載費"),

    # 調査研究費（AnimaCast Core IP・ゲーム経済・先端API）
    (["スクウェア", "スクエニ", "ｽｸｳｴｱ", "square enix", "ドラクエ", "任天堂", "nintendo", "steam", "プレイステーション", "ps store"], 
     "調査研究費（AnimaCast等）", "課対仕入10%", "[研究日報] AnimaCast：ゲーム内経済モデル・リアルタイム決済検証"),
    (["google play", "app store", "apple"], 
     "調査研究費（AnimaCast等）", "課対仕入10%", "[研究日報] AnimaCast：アプリ課金API・決済UI検証"),
    (["u-next", "netflix", "プライムビデオ"], 
     "調査研究費（AnimaCast等）", "課対仕入10%", "[研究日報] 映像ストリーミング・配信UI/UX検証"),

    # 交際費（接待・取引先会食）
    (["蹄", "hizume", "はき溜め", "はき駄め", "野武士", "nobushi", "エスカイヤ", "esquire", "ふるさと", "西海", "saikai", 
      "かに道楽", "右コン", "とり八", "串カツ田中", "麻ノ葉", "蜂ヤ", "四十", "denuke", "心屋", "すずらん"], 
     "交際費", "課対仕入10%", "[会食交際] 取引先・アライアンス打合せ"),

    # 会議費（打合せ・軽食）
    (["すし辰", "sushitatsu", "くら寿司", "kura sushi", "スシロー", "sushiro", "アンデルセン", "ロイヤルホスト", 
      "royalhost", "ゆず庵", "サイゼリヤ", "スターバックス", "ドトール", "珈琲", "カフェ", "電光石火", "ガスト", "ジョイフル"], 
     "会議費", "課対仕入10%", "[社内・社外会議] 業務打合せ・飲食代"),

    # 通信費（クラウド・IT・通信）
    (["サイボウズ", "cybozu", "adobe", "アドビ", "マイクロソフト", "msft", "microsoft", "ドコモ", "docomo", 
      "楽天モバイル", "rakuten mobile", "チュピコム", "usen music", "ミライ工事", "ソウルウェア", "canva", "オートデスク", "autodesk"], 
     "通信費", "課対仕入10%", ""),

    # 消耗品費（資材・工具・事務用品）
    (["アマゾン", "amazon", "コーナン", "kohnan", "モノタロウ", "monotaro", "建デポ", "kendepo", "西村ジョイ", 
      "セリア", "seria", "ヨドバシ", "エディオン", "edion", "ニトリ", "nitori", "ジュンテンドー", "コメリ", "ナフコ", "ユニットコム"], 
     "消耗品費", "課対仕入10%", ""),

    # 旅費交通費（新幹線・宿泊・タクシー・駐車場）
    (["jr", "西日本旅客鉄道", "東海旅客鉄道", "東日本旅客鉄道", "新幹線", "楽天トラベル", "rakuten travel", 
      "ホテル", "hotel", "タイムズ", "times", "グリーンパーク", "スカイパーク", 
      "タクシー", "taxi", "瀬戸内海汽船", "汽船", "高速情報協同組合"], 
     "旅費交通費", "課対仕入10%", ""),

    # 車両費（燃料・車検・整備）
    (["キユウユダイ", "給油", "eneos", "エネオス", "アポロステーション", "apollostation", "タイヤ館", "スズキ自販", "車検"], 
     "車両費", "課対仕入10%", ""),

    # 食材仕入（シュガー店舗等）
    (["wannaeat", "ワナイート", "a-price", "大黒天物産", "食材"], 
     "仕入高（8%軽）", "課対仕入8%(軽)", ""),

    # 外注費（主要施工・開発パートナーへの振込）
    (["ケーティーエス", "kts", "鳥取通信", "ベッセル", "エルワイコンサル", "アイデン", "ミカモ電気", "アルテック", "awc", "アイ・リンク"], 
     "外注費", "課対仕入10%", ""),

    # 支払手数料（振込手数料・公課）
    (["振込手数料", "手数料", "全厚済"], 
     "支払手数料", "課対仕入10%", ""),

    # 保険料
    (["sompo", "損保ジャパン", "ビジネスセイト", "火災保険"], 
     "保険料", "対象外", "")
]

# ==========================================
# 4. 法人別 設定マスタ（確定DriveフォルダID同期済）
# ==========================================
COMPANY_CONFIG = {
    "ナインゲイツ": {
        "code": "ninegates",
        "fiscal_start": 4,
        "input_folder_id": "1upG2C-m-An3VcI1ULE7A6BwHipRzIjge",
        "output_folder_id": "1xtj1g42RSwOa_eUATF89qLdS_JiM_yQ8",
        "default_payment": "普通預金（PayPay銀行 005-1744850）",
        "payment_mapping": {
            "普通預金（PayPay銀行 005-1744850）": ("普通預金", "PayPay銀行(1744850)"),
            "普通預金（広島市信用組合 117-0878359-0）": ("普通預金", "広島市信用組合"),
            "普通預金（呉信用金庫 020-1096121）": ("普通預金", "呉信用金庫"),
            "役員立替（PayPay個人 003-2060281）": ("役員借入金", "九門久士(PayPay)"),
            "役員立替（楽天個人 214-4383608）": ("役員借入金", "九門久士(楽天)"),
            "クレジットカード（未払金）": ("未払金", "カード"),
            "現金": ("現金", "")
        }
    },
    "シュガー": {
        "code": "sugar",
        "fiscal_start": 6,
        "input_folder_id": "1qo5FqrpHDFgY4tzf32YaYbFQB6wCQ9Ih",
        "output_folder_id": "19HhywRqfSRG2tWMVzDkcw6DlmCMGLgSI",
        "default_payment": "普通預金（PayPay銀行 005-5332515）",
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
        "default_payment": "普通預金（PayPay銀行 005-2423746）",
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
os.makedirs(DEFAULT_POOL_DIR, exist_ok=True)
os.makedirs(BASE_UPLOAD_DIR, exist_ok=True)

# ==========================================
# 5. Google Drive API 関数（サービスアカウント＆Secrets完全両対応）
# ==========================================
def get_drive_service():
    scopes = ['[suspicious link removed]']
    creds = None
    auth_source = None

    # 1. サービスアカウント認証（最優先・完全自動）
    if "GOOGLE_SERVICE_ACCOUNT" in st.secrets:
        try:
            sa_info = st.secrets["GOOGLE_SERVICE_ACCOUNT"]
            sa_dict = json.loads(sa_info) if isinstance(sa_info, str) else sa_info
            creds = service_account.Credentials.from_service_account_info(sa_dict, scopes=scopes)
            auth_source = "サービスアカウント (gemini-api-sa)"
        except Exception:
            creds = None

    # 2. token.json の自動読込
    if not creds and os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', scopes)
            auth_source = "token.json"
        except Exception:
            creds = None

    # 3. Streamlit Secrets (GOOGLE_TOKEN)
    if not creds and "GOOGLE_TOKEN" in st.secrets:
        try:
            token_val = st.secrets["GOOGLE_TOKEN"]
            token_info = json.loads(token_val) if isinstance(token_val, str) else token_val
            creds = Credentials.from_authorized_user_info(token_info, scopes)
            auth_source = "Streamlit Secrets (OAuth)"
        except Exception:
            creds = None

    # 4. 手動入力セッショントークン
    if not creds and "custom_google_token" in st.session_state and st.session_state.custom_google_token:
        try:
            token_info = json.loads(st.session_state.custom_google_token)
            creds = Credentials.from_authorized_user_info(token_info, scopes)
            auth_source = "セッション手動入力"
        except Exception:
            creds = None

    if creds:
        return build('drive', 'v3', credentials=creds), auth_source
    return None, None

def get_or_create_monthly_folder(service, parent_folder_id, target_month):
    """親フォルダ内に 'YYYY-MM' フォルダを検索・自動作成"""
    try:
        query = f"'{parent_folder_id}' in parents and name = '{target_month}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(
            q=query, 
            fields="files(id, name)", 
            spaces='drive',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']

        folder_metadata = {
            'name': target_month,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        folder = service.files().create(
            body=folder_metadata, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        return folder.get('id')
    except Exception:
        return parent_folder_id

def upload_file_to_drive(service, folder_id, file_name, file_bytes, mime_type):
    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    return service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id, webViewLink',
        supportsAllDrives=True
    ).execute()

def get_pooled_files(target_dir):
    if not os.path.exists(target_dir): return []
    valid_exts = [".png", ".jpg", ".jpeg", ".pdf"]
    return sorted([f for f in os.listdir(target_dir) if os.path.splitext(f)[1].lower() in valid_exts])

def sync_from_company_drive(folder_id, pool_dir):
    service, _ = get_drive_service()
    if not service: return False, "Google Drive API認証情報が見つかりません。"
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

# ==========================================
# 6. 超自動仕訳マッチング判定エンジン
# ==========================================
def match_intelligent_category(summary_text, is_income):
    summary_norm = summary_text.replace("　", " ").strip()
    summary_lower = summary_norm.lower()

    if is_income:
        if "利息" in summary_lower:
            return "受取利息", "非課売上", True, "[決算] 預金利息"
        if any(k in summary_lower for k in ["クモン", "九門", "代表", "立替"]):
            return "役員借入金（代表立替・借入）", "対象外", True, "代表立替・役員借入金戻入"
        return "売上高", "課税売上10%", True, "売上高・売掛金回収入金"

    for keywords, category, tax_type, memo in AUTO_MATCH_RULES:
        for kw in keywords:
            if kw.lower() in summary_lower:
                return category, tax_type, True, memo

    return "雑費", "課対仕入10%", False, ""

def parse_paypay_pdf_intelligent(file_bytes, target_company):
    if not HAS_PYPDF:
        st.error("⚠️ サーバー環境に `pypdf` がインストールされていません。")
        return []

    records = []
    comp_conf = COMPANY_CONFIG[target_company]
    default_pay = comp_conf["default_payment"]

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        raw_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t: raw_text += t + "\n"

        cleaned_text = re.sub(r'(\d+),\s+(\d+)', r'\1,\2', raw_text)
        lines = [l.strip() for l in cleaned_text.split("\n") if l.strip()]

        idx = 0
        date_finder = re.compile(r'(202\d)[/-](\d{1,2})[/-](\d{1,2})')

        for line in lines:
            m = date_finder.search(line)
            if m:
                year, month, day = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
                clean_date = f"{year}-{month}-{day}"
                month_str = f"{year}-{month}"

                sub_line = date_finder.sub('', line).strip()
                tokens = sub_line.split()

                amounts, summary_tokens = [], []
                for t in tokens:
                    num_str = t.replace(",", "").replace("円", "")
                    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', t): continue
                    if re.match(r'^0000\d$', t): continue
                    if num_str.isdigit() and len(num_str) >= 2:
                        amounts.append(int(num_str))
                    else:
                        summary_tokens.append(t)

                if amounts:
                    summary = " ".join(summary_tokens).strip()
                    summary = re.sub(r'^[\|\s]+', '', summary)
                    summary = re.sub(r'[\|\s]+$', '', summary)
                    summary_lower = summary.lower()

                    is_income = False
                    if len(amounts) >= 2 and amounts[0] == amounts[1]:
                        is_income = True
                        amount = amounts[0]
                    elif any(k in summary_lower for k in ["振込", "お利息", "利息", "入金"]):
                        is_income = True
                        amount = amounts[0]
                    else:
                        is_income = False
                        amount = -amounts[0]

                    if not summary:
                        summary = "PayPay銀行入金" if is_income else "PayPay銀行出金"

                    category, tax_type, is_matched, memo = match_intelligent_category(summary, is_income)

                    records.append({
                        "id": f"rec_{idx}",
                        "date": clean_date,
                        "month": month_str,
                        "amount": int(amount),
                        "is_income": is_income,
                        "summary": summary,
                        "category": category,
                        "sub_account": "",
                        "tax_type": tax_type,
                        "payment": default_pay,
                        "is_auto_matched": is_matched,
                        "dining_info": None,
                        "research_memo": memo
                    })
                    idx += 1
        return records
    except Exception as e:
        st.error(f"PayPay銀行PDF明細の解析エラー: {e}")
        return []

def parse_paypay_csv_intelligent(file_bytes, target_company):
    comp_conf = COMPANY_CONFIG[target_company]
    default_pay = comp_conf["default_payment"]

    try:
        try: df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8")
        except Exception: df = pd.read_csv(io.BytesIO(file_bytes), encoding="shift_jis")

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

            out_amt, in_amt = "0", "0"
            for out_col in ["お支払金額", "出金金額(円)", "出金額", "出金"]:
                if out_col in row_dict and row_dict[out_col] != "nan" and row_dict[out_col].strip():
                    out_amt = row_dict[out_col]
                    break
            for in_col in ["お預り金額", "入金金額(円)", "入金額", "入金"]:
                if in_col in row_dict and row_dict[in_col] != "nan" and row_dict[in_col].strip():
                    in_amt = row_dict[in_col]
                    break

            try:
                out_val = float(str(out_amt).replace(",", "").replace("円", "")) if out_amt != "nan" else 0
                in_val = float(str(in_amt).replace(",", "").replace("円", "")) if in_amt != "nan" else 0
            except Exception:
                out_val, in_val = 0, 0

            is_income = in_val > 0
            amount = in_val if is_income else -out_val

            summary = ""
            for c in ["摘要", "お取引内容", "取引内容", "振込人名", "支払先"]:
                if c in row_dict and row_dict[c] != "nan":
                    summary = row_dict[c]
                    break

            if date_val and amount != 0:
                clean_date = date_val[:10]
                category, tax_type, is_matched, memo = match_intelligent_category(summary, is_income)

                records.append({
                    "id": f"csv_rec_{idx}",
                    "date": clean_date,
                    "month": clean_date[:7],
                    "amount": int(amount),
                    "is_income": is_income,
                    "summary": summary,
                    "category": category,
                    "sub_account": "",
                    "tax_type": tax_type,
                    "payment": default_pay,
                    "is_auto_matched": is_matched,
                    "dining_info": None,
                    "research_memo": memo
                })

        return records
    except Exception as e:
        st.error(f"PayPay銀行CSVの解析エラー: {e}")
        return []

def generate_yayoi_csv_for_records(target_records, company_name):
    conf = COMPANY_CONFIG[company_name]
    default_pay = conf["default_payment"]
    lines = []

    for row in target_records:
        raw_pay = row.get("payment", default_pay)
        pay_method = safe_first_str(raw_pay, default_pay)
        bank_subj, bank_sub = conf["payment_mapping"].get(pay_method, ("普通預金", ""))

        target_subj = safe_first_str(row.get("category", "外注費"))
        target_sub = safe_first_str(row.get("sub_account", ""))
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

        if row.get("is_income", False):
            cols = [
                "2000", "", "", date_str, bank_subj, bank_sub, "全社", "対象外", amount, "0",
                target_subj, target_sub, "全社", tax_type, amount, "0", summary_text, "", "", "NO"
            ]
        else:
            cols = [
                "2000", "", "", date_str, target_subj, target_sub, "全社", tax_type, amount, "0",
                bank_subj, bank_sub, "全社", "対象外", amount, "0", summary_text, "", "", "NO"
            ]

        lines.append(",".join([f'"{c}"' for c in cols]))
    return "\r\n".join(lines)

# ==========================================
# 7. Streamlit メイン UI
# ==========================================
st.set_page_config(page_title="九門グループ 統合経理・消込＆証憑管理", layout="wide")

st.markdown("""
<style>
div[data-baseweb="select"] {
    font-size: 16px !important;
}
.stSelectbox label {
    font-size: 15px !important;
    font-weight: bold !important;
}
</style>
""", unsafe_allow_html=True)

service_instance, auth_source_name = get_drive_service()

st.sidebar.title("🏢 経理くん（統括参謀）")
current_user_email = st.sidebar.selectbox("操作者", list(USERS.keys()), format_func=lambda x: USERS[x]["name"])
target_company = st.sidebar.selectbox("🏢 処理対象の会社（会計主体）", USERS[current_user_email]["companies"])

company_conf = COMPANY_CONFIG[target_company]
st.sidebar.markdown(f"**標準口座:** `{company_conf['default_payment']}`")

# 認証ステータス表示
if service_instance:
    st.sidebar.success(f"☁️ Google Drive: **認証完了**\n({auth_source_name})")
else:
    with st.sidebar.expander("🔑 Google Drive API手動設定", expanded=False):
        st.info("Secrets未設定時の手動フォールバック枠です")
        custom_token = st.text_area("GOOGLE_TOKEN (JSON)", value="")
        if custom_token:
            st.session_state.custom_google_token = custom_token
            st.rerun()

st.title(f"🏢 九門グループ 統合経理システム（対象: {target_company}）")
st.caption("【確定Drive自動認証対応】月別フォルダ自動振り分け ＆ 3社共通網羅マスター")

main_tab_receipt, main_tab_bank = st.tabs([
    "📑 ① 未処理領収書の管理・プレビュー・登録",
    "🏦 ② PayPay銀行 口座明細消込 ＆ 弥生仕訳出力"
])

# ------------------------------------------
# タブ 1: 領収書管理
# ------------------------------------------
with main_tab_receipt:
    st.subheader(f"📑 未処理領収書プール（対象法人: {target_company}）")

    with st.expander("☁️ Google ドライブから領収書を同期する", expanded=False):
        folder_id = company_conf["input_folder_id"]
        st.info(f"1次読込フォルダ: [suspicious link removed]{folder_id}")
        if st.button("🔄 Google ドライブから同期を実行", type="primary", key="sync_btn_tab1"):
            with st.spinner("同期中..."):
                ok, msg = sync_from_company_drive(folder_id, DEFAULT_POOL_DIR)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)

    pooled_files = get_pooled_files(DEFAULT_POOL_DIR)
    if not pooled_files:
        st.info("💡 現在未処理プール（receipt_pool）に未処理の領収書はありません。")
    else:
        st.success(f"🎯 未処理の領収書: **残り {len(pooled_files)} 件**")
        target_file = pooled_files[0]
        target_path = os.path.join(DEFAULT_POOL_DIR, target_file)
        ext = os.path.splitext(target_file)[1].lower()

        c_view, c_form = st.columns([1.2, 1])
        with c_view:
            st.caption(f"プレビュー: `{target_file}`")
            if ext in [".png", ".jpg", ".jpeg"]:
                try:
                    img = Image.open(target_path)
                    st.image(img, use_container_width=True)
                except Exception as e:
                    st.error(f"画像読み込みエラー: {e}")
            elif ext == ".pdf":
                st.info("📄 PDF形式の領収書です。")
                with open(target_path, "rb") as f:
                    st.download_button("📥 このPDFを開く／ダウンロード", f.read(), file_name=target_file)

            if st.button("🗑️ この領収書をスキップして破棄", key="del_pooled_file"):
                os.remove(target_path)
                st.warning("ファイルを破棄しました。")
                st.rerun()

        with c_form:
            st.markdown("### 📝 領収書の内容を確認して登録")
            with st.form("manual_receipt_form"):
                rec_date = st.date_input("領収書日付", value=date.today())
                store_name = st.text_input("支払先・店舗名*", value=os.path.splitext(target_file)[0])

                sel_cat = st.selectbox("勘定科目（全社共通マスター）", UNIFIED_ALL_CATEGORIES, index=UNIFIED_ALL_CATEGORIES.index("消耗品費"))
                sel_pay = st.selectbox("決済手段", list(company_conf["payment_mapping"].keys()))

                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    rec_amount = st.number_input("支払金額（税込・円）*", min_value=0, step=100, value=0)
                with col_f2:
                    sel_tax = st.selectbox("税率", ["課対仕入10%", "課対仕入8%(軽)", "対象外"])

                rec_memo = st.text_input("用途・メモ（相手先・目的など）", placeholder="例: [販促] 新規事業広告掲載")

                submit_receipt = st.form_submit_button(f"✅ 【{target_company}】の経費として確定保存", type="primary")
                if submit_receipt:
                    if rec_amount <= 0 or not store_name.strip():
                        st.error("支払先と金額を入力してください！")
                    else:
                        dest_dir = os.path.join(BASE_UPLOAD_DIR, company_conf["code"])
                        os.makedirs(dest_dir, exist_ok=True)
                        dest_file_path = os.path.join(dest_dir, target_file)
                        shutil.move(target_path, dest_file_path)
                        st.success(f"領収書 `{target_file}` を確定保存しました！")
                        st.rerun()

# ------------------------------------------
# タブ 2: PayPay口座明細消込 ＆ 弥生仕訳出力
# ------------------------------------------
with main_tab_bank:
    st.subheader(f"🏦 PayPay銀行 口座明細投入（会計主体: {target_company}）")
    st.caption(f"指定口座: `{company_conf['default_payment']}` の取引明細を3社合同マスターで自動消込します")

    uploaded_statement = st.file_uploader(
        f"{target_company} の取引明細ファイル（PDF または CSV）を選択してください",
        type=["pdf", "csv"],
        key="bank_file_upload"
    )

    if "transactions_single" not in st.session_state or st.session_state.get("last_company") != target_company:
        st.session_state.transactions_single = []
        st.session_state.last_company = target_company

    if uploaded_statement:
        file_bytes = uploaded_statement.read()
        if uploaded_statement.name.lower().endswith(".pdf"):
            parsed_data = parse_paypay_pdf_intelligent(file_bytes, target_company)
        else:
            parsed_data = parse_paypay_csv_intelligent(file_bytes, target_company)

        if parsed_data:
            st.session_state.transactions_single = parsed_data

    # テキスト直接貼り付けフォールバック
    with st.expander("📋 明細テキスト直接貼り付け（フォールバック）"):
        direct_text = st.text_area("PayPay銀行の明細テキストを直接貼り付け", placeholder="2026/10/16 15:46:48 793,800 793,800 振込 ド）シユガ－")
        if st.button("📋 テキストから明細を反映"):
            if direct_text:
                st.session_state.transactions_single = parse_paypay_pdf_intelligent(direct_text.encode("utf-8"), target_company)
                st.rerun()

    if st.session_state.get("transactions_single"):
        records = st.session_state.transactions_single
        st.success(f"📊 明細解析完了: 合計 **{len(records)} 件** ｜ 3社共通マスターで全自動仕分け済")

        # ----------------------------------------------------
        # 2段ワイド表示：全社共通勘定科目マスターによる仕訳調整
        # ----------------------------------------------------
        st.subheader("② 勘定科目・税務メモの確認・調整")
        for r in records:
            abs_amt = abs(r["amount"])
            type_label = "💰【入金/売上】" if r.get("is_income") else "💸【出金/経費】"

            with st.expander(f"{type_label} {r['date']} ｜ {r['summary']} ｜ ¥{abs_amt:,} ｜ 科目: {r['category']}", expanded=not r.get("is_auto_matched", False)):
                cur_cat_idx = UNIFIED_ALL_CATEGORIES.index(r["category"]) if r["category"] in UNIFIED_ALL_CATEGORIES else 0
                r["category"] = st.selectbox(
                    "📌 勘定科目（3社共通網羅マスター）", 
                    UNIFIED_ALL_CATEGORIES, 
                    index=cur_cat_idx, 
                    key=f"cat_{r['id']}",
                    help="広告宣伝費、売掛金、外注費、交際費など全社共通の正式勘定科目です。"
                )

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    r["research_memo"] = st.text_input(
                        "📝 業務・税務メモ（取引先・打合せ目的・研究内容など）", 
                        value=r.get("research_memo", ""), 
                        key=f"memo_{r['id']}",
                        placeholder="例: [販促] TJHiroshima広告掲載 / [会食] USEN山田常務打合せ"
                    )

                with col_m2:
                    st.write("")
                    st.write("")
                    if st.button("確定", key=f"ok_{r['id']}", use_container_width=True):
                        r["is_auto_matched"] = True
                        st.success("確定反映")
                        st.rerun()

        # サマリープレビュー一覧
        st.subheader(f"📋 【{target_company}】仕訳プレビュー一覧")
        preview_rows = []
        for r in records:
            preview_rows.append({
                "区分": "💰 入金" if r.get("is_income") else "💸 出金",
                "日付": r["date"],
                "金額": r["amount"],
                "摘要（取引先等）": r["summary"],
                "勘定科目": r["category"],
                "決済口座": r["payment"],
                "税務メモ": r.get("research_memo", "")
            })
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

        # ----------------------------------------------------
        # 月別フォルダ自動生成 ＆ Drive保管
        # ----------------------------------------------------
        st.markdown("---")
        st.subheader(f"③ 【{target_company}】弥生仕訳CSV出力 ＆ 月別Drive自動保管")

        target_month_str = records[0].get("month", datetime.now().strftime("%Y-%m")) if (records and isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict)) else datetime.now().strftime("%Y-%m")
        st.caption(f"📁 保存先: `{target_company}` 親フォルダID: `{company_conf['output_folder_id']}` ＞ **【 `{target_month_str}` 】サブフォルダ**（自動生成）")

        csv_str = generate_yayoi_csv_for_records(records, target_company)
        try: csv_bytes = csv_str.encode("cp932", errors="replace")
        except Exception: csv_bytes = csv_str.encode("utf-8-sig")

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.download_button(
                label=f"📥 【{target_company}】弥生仕訳CSVをダウンロード ({len(records)}件)",
                data=csv_bytes,
                file_name=f"弥生仕訳_{company_conf['code']}_{target_month_str}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )

        with col_d2:
            if st.button(f"📁 【{target_company}】月別フォルダへ自動保存", use_container_width=True):
                service, _ = get_drive_service()
                if not service:
                    st.warning("⚠️ Google Drive API認証情報が未設定です。")
                else:
                    with st.spinner(f"Google Drive（{target_company} ＞ {target_month_str} フォルダ）へ自動配送中..."):
                        try:
                            parent_fid = company_conf["output_folder_id"]
                            target_sub_folder_id = get_or_create_monthly_folder(service, parent_fid, target_month_str)
                            
                            upload_file_to_drive(
                                service, 
                                target_sub_folder_id, 
                                f"弥生仕訳_{company_conf['code']}_{target_month_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                csv_bytes, 
                                "text/csv"
                            )
                            st.success(f"🎉 **{target_company}** のGoogle Drive親フォルダ内にある **【 `{target_month_str}` 】フォルダ** へ弥生仕訳CSVを安全に自動保管しました！（@9gates.info メンバー全員と自動共有中）")
                        except Exception as e:
                            st.error(f"Drive配送エラー: {str(e)}")
