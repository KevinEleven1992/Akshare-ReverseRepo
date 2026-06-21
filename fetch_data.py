import akshare as ak
import pandas as pd
import json
import os
import datetime

def clean_financial_value(val):
    """
    清洗金融核心数值，剔除千分位逗号、特殊非数字字符，确保科学计算的正确性
    """
    if pd.isna(val):
        return 0.0
    val_str = str(val).replace(',', '').replace('亿元', '').strip()
    if val_str in ['', '--', '-', '无', '非公开', 'None']:
        return 0.0
    try:
        return float(val_str)
    except:
        return 0.0

def fetch_pboc_data():
    print("开始从 AkShare 获取央行逆回购数据...")
    try:
        # 1. 抓取央行公开市场操作表
        df = ak.macro_china_pboc_omo()
        if df.empty:
            print("错误：AkShare 未返回任何原始数据！")
            return

        # 2. 强力字段名匹配
        date_col = next((c for c in df.columns if '日期' in c), '日期')
        injection_col = next((c for c in df.columns if '逆回购' in c and ('操作' in c or '投放' in c) and '到期' not in c and '净' not in c), '逆回购-操作量')
        maturity_col = next((c for c in df.columns if '逆回购' in c and '到期' in c), '逆回购-到期量')
        net_col = next((c for c in df.columns if '逆回购' in c and '净' in c), '逆回购-净投放')

        print(f"解析定位成功 -> 日期列: {date_col}, 投放列: {injection_col}, 到期列: {maturity_col}")

        # 3. 基础类型转换与核心数据清洗
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col])
        
        df[injection_col] = df[injection_col].apply(clean_financial_value)
        df[maturity_col] = df[maturity_col].apply(clean_financial_value)
        if net_col in df.columns:
            df[net_col] = df[net_col].apply(clean_financial_value)
        else:
            df[net_col] = df[injection_col] - df[maturity_col]

        # 4. 按日期从旧到新升序排列
        df = df.sort_values(by=date_col, ascending=True)

        # 5. 准确定位今天的日期基准
        today = datetime.date.today()
        df_history = df[df[date_col].dt.date <= today]
        if df_history.empty:
            df_history = df  # 避免时区微调导致取空
            
        latest_hist_date = df_history[date_col].max().date()

        # ==========================================
        # 【要求一】：仅保留过去7天的历史操作量和到期量数据
        # ==========================================
        start_history_date = today - datetime.timedelta(days=7)
        df_past_7 = df_history[df_history[date_col].dt.date >= start_history_date]
        
        # 容错：如果遇到连休长假导致过去7天全无数据，保底截取最后7个有记录的交易日
        if len(df_past_7) < 2:
            df_past_7 = df_history.tail(7)
        
        result = []
        for _, row in df_past_7.iterrows():
            date_str = row[date_col].strftime('%Y-%m-%d')
            result.append({
                "date": date_str,
                "injection": row[injection_col],
                "maturity": row[maturity_col],
                "net": row[net_col],
                "is_forecast": False
            })

        # ==========================================
        # 【要求二】：科学计算，精确推演未来至少14天的到期量数据
        # ==========================================
        future_days = 14
        future_records = {}
        
        # 预初始化未来14天连续的时间线
        for i in range(1, future_days + 1):
            f_date = latest_hist_date + datetime.timedelta(days=i)
            f_date_str = f_date.strftime('%Y-%m-%d')
            future_records[f_date_str] = {
                "date": f_date_str,
                "injection": 0.0,
                "maturity": 0.0,
                "net": 0.0,
                "is_forecast": True
            }

        # 科学推演路径 1：远期合同公告穿透提取（针对已有远期行数据）
        df_future_source = df[df[date_col].dt.date > latest_hist_date]
        for _, row in df_future_source.iterrows():
            f_date_str = row[date_col].strftime('%Y-%m-%d')
            if f_date_str in future_records:
                f_mat = row[maturity_col]
                if f_mat > 0:
                    future_records[f_date_str]["maturity"] = f_mat
                    future_records[f_date_str]["net"] = -f_mat

        # 科学推演路径 2：7天OMO刚性契约回溯投影（针对标准操作在未来回笼的刚性推算）
        # 扫描过去14天内的投放，严格按7天周期向后映射到未来的到期日
        df_past_14_for_forecast = df_history.tail(14)
        for _, row in df_past_14_for_forecast.iterrows():
            h_date = row[date_col].date()
            inj_amt = row[injection_col]
            if inj_amt > 0:
                proj_date_7 = h_date + datetime.timedelta(days=7)
                proj_date_7_str = proj_date_7.strftime('%Y-%m-%d')
                
                if proj_date_7_str in future_records:
                    # 如果路径1中未登记到期量，则依照7天契约刚性归入
                    if future_records[proj_date_7_str]["maturity"] == 0:
                        future_records[proj_date_7_str]["maturity"] = inj_amt
                        future_records[proj_date_7_str]["net"] = -inj_amt

        # 合并处理完的未来14天科学计算行
        for f_date_str in sorted(future_records.keys()):
            result.append(future_records[f_date_str])

        # 6. 保存并持久化输出
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
            
        print(f"🎉 核心数据清洗完成！已成功写入 data.json。总共包含 {len(result)} 条安全的数据记录。")
        
    except Exception as e:
        print(f"运行发生致命异常: {e}")
        # 保底机制：如果完全崩溃，输出结构化数据防止前端白屏
        if not os.path.exists('data.json'):
            with open('data.json', 'w') as f:
                json.dump([], f)

if __name__ == "__main__":
    fetch_pboc_data()
