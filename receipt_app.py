import streamlit as st
import pandas as pd
import json
import os
import io
import re
from datetime import datetime, date
from PIL import Image
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
# 2. 各法人設定・1次読込フォルダ・出力先フォルダ・勘定科目辞書
# ==========================================
COMPANY_CONFIG = {
    "ナインゲイツ": {
        "code": "ninegates",
        "fiscal_start": 4,
        "input_folder_id": "1upG2C-m-An3VcI1ULE7A6BwHipRzIjge",
        "output_folder_id": "1xtj1g42RSwOa_eUATF89qLdS_JiM_yQ8",
        "categories": ["外注費", "仕入高", "仕入高（8%軽）", "旅費交通費", "消耗品費", "車両費", "通信費", "会議費", "交際費", "地代家賃", "水道光熱費", "支払手数料", "法定福利費", "福利厚生費", "雑費"],
        "payments": ["普通預金（PayPay銀行）", "クレジットカード（未払金）", "役員立替（役員借入金）", "現金", "普通預金（広島市信用組合）"],
        "payment_mapping": {
            "普通預金（PayPay銀行）": ("普通預金", "PayPay銀行"),
            "クレジットカード（未払金）": ("未払金", "カード"),
            "役員立替（役員借入金）": ("役員借入金", "九門久士"),
            "現金": ("現金", ""),
            "普通預金（広島市信用組合）": ("普通預金", "広島市信用組合"),
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
        "payments": ["普通預金（PayPay銀行）", "役員立替（短期借入金）", "クレジットカード（未払金）", "普通預金（広島市信用組合）", "普通預金（呉信用金庫）"],
        "payment_mapping": {
            "普通預金（PayPay銀行）": ("普通預金", "PayPay銀行"),
            "役員立替（短期借入金）": ("短期借入金", "クモンヒサシ"),
            "クレジットカード（未払金）": ("未払金", ""),
            "普通預金（広島市信用組合）": ("普通預金", "広島市信用組合"),
            "普通預金（呉信用金庫）": ("普通預金", "呉信用金庫"),
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
        "payments": ["普通預金（PayPay銀行）", "役員立替（役員借入金）", "クレジットカード（未払金）"],
        "payment_mapping": {
            "普通預金（PayPay銀行）": ("普通預金", "PayPay銀行"),
            "役員立替（役員借入金）": ("役員借入金", "九門久士"),
            "クレジットカード（未払金）": ("未払金", ""),
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
# 3. Google Drive API ＆ 同期・月別フォルダ動的生成関数
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
        return files['id']
    folder_metadata = {'name': target_month, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_folder_id]}
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')

def upload_file_to_drive(service, folder_id, file_name, file_bytes, mime_type):
    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    return service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

# ==========================================
# 4. PayPay明細パース ＆ 自動仕訳エンジン
# ==========================================
def auto_classify_transaction(company_name, summary_text):
    conf = COMPANY_CONFIG[company_name]
    summary_lower = summary_text.lower()
    auto_memo = ""
    if company_name == "SF企画":
        if any(k in summary_lower for k in ["google play", "app store", "apple"]):
            auto_memo = "[研究日報] AnimaCast：課金API・トークン決済UI検証"
        elif any(k in summary_lower for k in ["u-next", "netflix", "プライム"]):
            auto_memo = "[研究日報] 映像配信UI/UXストリーミング検証"
        elif any(k in summary_lower for k in ["ドラクエ", "任天堂", "steam", "square"]):
            auto_memo = "[研究日報] AnimaCast：ゲーム内経済トークン循環調査"

    for keywords, category, sub_account, tax_type in conf.get("keyword_rules", []):
        for kw in keywords:
            if kw.lower() in summary_lower:
                return category, sub_account, tax_type, auto_memo
    default_cat = conf["categories"] if conf["categories"] else "雑費"
    return default_cat, "", "課対仕入10%", auto_memo

def parse_paypay_csv(file_bytes, company_name):
    try:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8")
        except Exception:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="shift_jis")
        
        records = []
        for _, row in df.iterrows():
            row_dict = {str(k).strip(): str(v).strip() for k, v in row.items()}
            date_val = ""
            for c in ["取引日", "日付", "年月日", "取引日時"]:
                if c in row_dict and row_dict[c] != "nan":
                    date_val = row_dict[c].replace("/", "-")
                    break
            
            out_amt = row_dict.get("出金金額(円)", row_dict.get("出金額", "0"))
            in_amt = row_dict.get("入金金額(円)", row_dict.get("入金額", "0"))
            try:
                out_val = float(str(out_amt).replace(",", "").replace("円", "")) if out_amt != "nan" else 0
                in_val = float(str(in_amt).replace(",", "").replace("円", "")) if in_amt != "nan" else 0
                amount = in_val if in_val > 0 else -out_val
            except Exception:
                amount = 0
            
            summary = ""
            for c in ["お取引内容", "摘要", "取引内容", "振込人名", "支払先"]:
                if c in row_dict and row_dict[c] != "nan":
                    summary = row_dict[c]
                    break
            
            if date_val and amount != 0:
                cat, sub_acc, tax_t, memo = auto_classify_transaction(company_name, summary)
                records.append({
                    "date": date_val[:10],
                    "amount": int(amount),
                    "summary": summary,
                    "category": cat,
                    "sub_account": sub_acc,
                    "tax_type": tax_t,
                    "research_memo": memo
                })
        return records
    except Exception as e:
        st.error(f"PayPay銀行CSVの解析エラー: {e}")
        return []

def generate_yayoi_csv(target_records, company_name):
    conf = COMPANY_CONFIG[company_name]
    lines = []
    for row in target_records:
        pay_method = row.get("payment", "普通預金（PayPay銀行）")
        credit_subj, credit_sub = conf["payment_mapping"].get(pay_method, ("普通預金", "PayPay銀行"))
        debit_subj = row.get("category", "外注費")
        debit_sub = row.get("sub_account", "")
        tax_type = row.get("tax_type", "課対仕入10%")
        amount = str(abs(row.get("amount", 0)))
        date_str = row.get("date", "").replace("-", "/")
        base_summary = row.get('paypay_summary', row.get('summary', ''))
        memo = row.get('research_memo', '') or row.get('entertainment_memo', '')
        summary_text = f"{base_summary} {memo}".strip()
        
        cols = [
            "2000", "", "", date_str, debit_subj, debit_sub, "全社", tax_type, amount, "0",
            credit_subj, credit_sub, "全社", "対象外", amount, "0", summary_text, "", "", "NO"
        ]
        lines.append(",".join([f'"{c}"' for c in cols]))
    return "\r\n".join(lines)

# ==========================================
# 5. Streamlit メイン UI
# ==========================================
st.set_page_config(page_title="九門グループ 統合経理・消込＆Drive自動保管", layout="wide")

st.sidebar.title("🏢 経理統制システム")
current_user_email = st.sidebar.selectbox("操作者選択", list(USERS.keys()), format_func=lambda x: USERS[x]["name"])
selected_company = st.sidebar.selectbox("🏢 対象法人", USERS[current_user_email]["companies"])

company_conf = COMPANY_CONFIG[selected_company]
current_input_folder_id = company_conf["input_folder_id"]
current_output_folder_id = company_conf["output_folder_id"]

st.sidebar.markdown(f"**📂 1次読込フォルダID:**\n`{current_input_folder_id}`")
st.sidebar.markdown(f"**📁 出力先親フォルダID:**\n`{current_output_folder_id}`")

# ------------------------------------------
# ☁️ Google ドライブから領収書を同期する（各社連動UI）
# ------------------------------------------
st.title(f"🏢 経理自動仕訳・消込・Drive月別保管 ({selected_company})")

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

# ------------------------------------------
# 🍽️ 交際費 / 会議費 自動判別 ＆ メモ入力ツール
# ------------------------------------------
with st.expander("🍽️ 【交際費/会議費】自動判別（1人あたり10,000円判定）＆ メモ入力ツール", expanded=False):
    st.markdown("飲食を伴う支払いは、**1人あたり10,000円以下**であれば全額損金算入の「会議費」に自動判定されます。")
    c1, c2, c3 = st.columns(3)
    with c1:
        e_amount = st.number_input("飲食支払金額 (税込・円)", value=18000, step=1000)
    with c2:
        e_people = st.number_input("参加人数 (合計)", value=2, min_value=1, step=1)
    with c3:
        per_person = int(e_amount / e_people) if e_people > 0 else 0
        if per_person <= 10000:
            st.success(f"判定: **会議費（全額損金）**\n1人あたり: ¥{per_person:,} ≦ ¥10,000")
            judged_category = "会議費"
        else:
            st.warning(f"判定: **接待交際費**\n1人あたり: ¥{per_person:,} > ¥10,000")
            judged_category = "交際費"

    e_partner = st.text_input("相手先企業名 ＆ 参加者氏名")
    e_purpose = st.text_input("飲食の目的・打合せ内容")

    if st.button("📝 この飲食メモを記憶・登録"):
        if not e_partner.strip() or not e_purpose.strip():
            st.error("⚠️ 税務署対策のため「相手先」と「目的」の入力は必須です！")
        else:
            st.success(f"✅ バリデーション完了！【{judged_category}】として仕訳メモを生成しました:\n`[{judged_category}] {e_partner} ({e_people}名/単価¥{per_person:,}) 目的:{e_purpose}`")

st.markdown("---")

# ------------------------------------------
# メイン処理：PayPay明細CSVアップロード ＆ 消込・Drive月別自動保存
# ------------------------------------------
col_top1, col_top2 = st.columns(2)
with col_top1:
    target_month = st.text_input("対象年月 (YYYY-MM)", value=datetime.now().strftime("%Y-%m"))
with col_top2:
    paypay_csv_file = st.file_uploader("① PayPay銀行 口座明細CSVをアップロード", type=["csv"])

if paypay_csv_file:
    paypay_records = parse_paypay_csv(paypay_csv_file.read(), selected_company)
    st.info(f"PayPay銀行明細: {len(paypay_records)} 件 読み込み完了（研究日報メモ自動付与済）")
    
    st.subheader("📋 自動仕訳 ＆ 判定結果プレビュー")
    df_preview = pd.DataFrame(paypay_records)[["date", "amount", "summary", "category", "sub_account", "research_memo"]]
    st.dataframe(df_preview, use_container_width=True)

    st.markdown("---")
    st.subheader(f"📥 弥生仕訳CSV出力 ＆ ④ Google Drive（{selected_company}経理くんデータ）月別自動移動")

    yayoi_csv_str = generate_yayoi_csv(paypay_records, selected_company)
    try:
        yayoi_bytes = yayoi_csv_str.encode("cp932", errors="replace")
    except Exception:
        yayoi_bytes = yayoi_csv_str.encode("utf-8-sig")

    col_act1, col_act2 = st.columns(2)
    with col_act1:
        st.download_button(
            label="📥 ③ 弥生会計仕訳CSVをダウンロード",
            data=yayoi_bytes,
            file_name=f"弥生仕訳_{company_conf['code']}_{target_month}.csv",
            mime="text/csv"
        )
    
    with col_act2:
        if st.button("📁 ④ 指定Google Driveの月別フォルダへ自動保存・移動を実行"):
            service = get_drive_service()
            parent_id = current_output_folder_id

            if not service:
                st.error("Google Drive API認証情報が見つかりません。")
            else:
                with st.spinner(f"Google Drive（{selected_company}経理くんデータ）内に「{target_month}」フォルダを作成し、データ保管中..."):
                    try:
                        month_folder_id = get_or_create_monthly_folder(service, parent_id, target_month)
                        upload_file_to_drive(service, month_folder_id, f"弥生仕訳_{company_conf['code']}_{target_month}.csv", yayoi_bytes, "text/csv")
                        
                        moved_count = 0
                        for fname in get_pooled_files(DEFAULT_POOL_DIR):
                            fpath = os.path.join(DEFAULT_POOL_DIR, fname)
                            if os.path.isfile(fpath):
                                with open(fpath, "rb") as rf:
                                    mime = "application/pdf" if fname.lower().endswith(".pdf") else "image/jpeg"
                                    upload_file_to_drive(service, month_folder_id, fname, rf.read(), mime)
                                os.remove(fpath)
                                moved_count += 1
                        
                        log_text = (
                            f"【九門グループ経理消込・保管実行ログ】\n"
                            f"対象会社: {selected_company}\n"
                            f"対象年月: {target_month}\n"
                            f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"処理仕訳件数: {len(paypay_records)} 件\n"
                            f"月別Driveフォルダへ移動した領収書数: {moved_count} 件\n"
                            f"出力先親フォルダID: {parent_id}\n"
                        )
                        upload_file_to_drive(service, month_folder_id, f"消込実行ログ_{target_month}.txt", log_text.encode("utf-8"), "text/plain")

                        st.success(f"🎉 処理完了！\nGoogle Drive『{selected_company}経理くんデータ』内の「{target_month}」フォルダに、仕訳CSV・領収書（{moved_count}件）・消込ログを自動移動・保存しました！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Google Drive保存エラー: {str(e)}")
