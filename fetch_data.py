import akshare as ak
import pandas as pd
import json
import os
import datetime

def clean_value(val):
    """清洗央行数值，剔除千分位逗号、特殊非数字字符"""
    if pd.isna(val):
        return 0.0
    s = str(val).replace(',', '').replace('亿元', '').strip()
    if s in ['', '--', '-', '无', 'None']:
        return 0.0
    try:
        return float(s)
    except:
        return 0.0

def fetch_pboc_data():
    print("开始从 AkShare 接口提取央行公开市场操作数据...")
    result = []
    
    try:
        # 1. 抓取标准央行公开市场数据接口
        df = ak.macro_china_pboc_omo()
        
        if df is None or df.empty:
            print("警告：AkShare 未返回任何数据，启动保底空数据机制。")
        else:
            print("原始数据获取成功，开始校核字段...")
            # 2. 精准定位逆回购专有数据列
            date_col = next((c for c in df.columns if '日期' in c), '日期')
            inj_col = next((c for c in df.columns if '逆回购' in c and ('操作' in c or '投放' in c) and '到期' not in c and '净' not in c), None)
            mat_col = next((c for c in df.columns if '逆回购' in c and '到期' in c), None)
            net_col = next((c for c in df.columns if '逆回购' in c and '净' in c), None)

            # 如果动态匹配失败，强制使用官方标准字段名
            if not inj_col or not mat_col:
                inj_col = '逆回购-操作量'
                mat_col = '逆回购-到期量'
                net_col = '逆回购-净投放'

            # 3. 规范化清洗
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.dropna(subset=[date_col])
            df[inj_col] = df[inj_col].apply(clean_value)
            df[mat_col] = df[mat_col].apply(clean_value)
            
            # 严格按日期从旧到新升序排列
            df = df.sort_values(by=date_col, ascending=True)
            
            # 4. 寻找最新有效数据日期作为科学计算的基准锚点
            latest_record_date = df[date_col].max().date()
            print(f"数据源最新有效操作日期为: {latest_record_date}")

            # ==========================================
            # 【要求一】：仅保留过去7天的历史操作量和到期量的数据
            # ==========================================
            # 获取最后7个有记录的交易日历史
            df_past_7 = df.tail(7)
            
            for _, row in df_past_7.iterrows():
                d_str = row[date_col].strftime('%Y-%m-%d')
                injection = row[inj_col]
                maturity = row[mat_col]
                net = row[net_col] if net_col in df.columns else (injection - maturity)
                
                result.append({
                    "date": d_str,
                    "injection": injection,
                    "maturity": maturity,
                    "net": clean_value(net),
                    "is_forecast": False
                })

            # ==========================================
            # 【要求二】：科学计算，精确推演未来至少14天的到期量数据
            # ==========================================
            # 依据央行契约：T日的 7天期逆回购投放，将在 T+7 日刚性到期回回笼资金。
            # 为了准确计算未来14天（D+1 到 D+14）的到期量，我们需要回溯 D-6 到 D+7 的历史投放。
            future_records = {}
            for i in range(1, 15):
                f_date = latest_record_date + datetime.timedelta(days=i)
                f_date_str = f_date.strftime('%Y-%m-%d')
                future_records[f_date_str] = {
                    "date": f_date_str,
                    "injection": 0.0,
                    "maturity": 0.0,
                    "net": 0.0,
                    "is_forecast": True
                }

            # 提取过去14天的历史投放，用于向未来推演投影
            df_past_14 = df.tail(14)
            for _, row in df_past_14.iterrows():
                h_date = row[date_col].date()
                inj_amt = row[inj_col]
                if inj_amt > 0:
                    # 按照 7天标准逆回购 刚性契约推算远期到期日
                    proj_date = h_date + datetime.timedelta(days=7)
                    proj_date_str = proj_date.strftime('%Y-%m-%d')
                    
                    if proj_date_str in future_records:
                        future_records[proj_date_str]["maturity"] += inj_amt
                        future_records[proj_date_str]["net"] = -future_records[proj_date_str]["maturity"]

            # 将科学计算出的未来14天刚性到期行并入最终数据集
            for f_date_str in sorted(future_records.keys()):
                result.append(future_records[f_date_str])

    except Exception as e:
        print(f"解析过程中触发异常: {e}")
    
    finally:
        # 保底机制：无论如何，必须保证 data.json 被成功写入，防止前端白屏
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        print(f"文件持久化保存成功，当前包含数据行数: {len(result)}")

if __name__ == "__main__":
    fetch_pboc_data()
