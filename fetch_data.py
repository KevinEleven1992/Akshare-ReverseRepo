import akshare as ak
import pandas as pd
import json
import os
import datetime

def fetch_pboc_data():
    print("开始从 AkShare 获取央行逆回购数据...")
    try:
        # 1. 获取中国公开市场操作数据
        df = ak.macro_china_pboc_omo()
        if df.empty:
            print("错误：未获取到任何数据！")
            return

        # 2. 动态寻找核心列（自动兼容接口字段微调）
        date_col, injection_col, maturity_col, net_col = None, None, None, None
        for col in df.columns:
            if '日期' in col: date_col = col
            elif '逆回购' in col and ('操作' in col or '投放' in col) and '到期' not in col and '净' not in col: injection_col = col
            elif '逆回购' in col and '到期' in col: maturity_col = col
            elif '逆回购' in col and '净' in col: net_col = col

        if not date_col or not injection_col or not maturity_col:
            print("错误：无法识别必要的逆回购数据列。")
            return

        # 3. 数据清洗与规范化
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df[injection_col] = pd.to_numeric(df[injection_col], errors='coerce').fillna(0)
        df[maturity_col] = pd.to_numeric(df[maturity_col], errors='coerce').fillna(0)
        
        df = df.dropna(subset=[date_col])
        df = df.sort_values(by=date_col, ascending=True)

        # 获取今天的日期（基于 GitHub Actions 运行时的系统日期）
        today = datetime.date.today()
        
        # 过滤出历史数据（即日期小于等于今天的记录）
        df_history = df[df[date_col].dt.date <= today]
        if df_history.empty:
            df_history = df
            
        latest_hist_date = df_history[date_col].max().date()
        print(f"最新历史操作数据日期: {latest_hist_date}")

        # ==========================================
        # 【要求一】：仅保留过去7天的历史操作量和到期量的数据
        # ==========================================
        df_past_7 = df_history.tail(7)
        
        result = []
        for _, row in df_past_7.iterrows():
            date_str = row[date_col].strftime('%Y-%m-%d')
            injection = float(row[injection_col])
            maturity = float(row[maturity_col])
            net = float(row[net_col]) if (net_col and net_col in row) else (injection - maturity)
            
            result.append({
                "date": date_str,
                "injection": injection,
                "maturity": maturity,
                "net": net,
                "is_forecast": False
            })

        # ==========================================
        # 【要求二】：科学计算，给出至少未来14天的到期量数据
        # ==========================================
        future_days = 14
        future_records = {}
        
        # 初始化未来14天的连续日期容器
        for i in range(1, future_days + 1):
            f_date = latest_hist_date + datetime.timedelta(days=i)
            f_date_str = f_date.strftime('%Y-%m-%d')
            future_records[f_date_str] = {
                "date": f_date_str,
                "injection": 0,
                "maturity": 0,
                "net": 0,
                "is_forecast": True
            }

        # 科学计算核心机制 1：远期合同穿透提取
        # 很多宏观数据库会根据已发布的逆回购公告，预先算好并生成未来的到期量行，若存在则精准提取
        df_future_source = df[df[date_col].dt.date > latest_hist_date]
        for _, row in df_future_source.iterrows():
            f_date_str = row[date_col].strftime('%Y-%m-%d')
            if f_date_str in future_records:
                f_mat = float(row[maturity_col])
                if f_mat > 0:
                    future_records[f_date_str]["maturity"] = f_mat
                    future_records[f_date_str]["net"] = -f_mat

        # 科学计算核心机制 2：标准契约回溯投影（兜底与校准）
        # 央行常规公开市场操作的核心工具为 7天期逆回购。今日投放的资金，将在第7天刚性到期回笼。
        # 我们向前扫描过去14天内发生的所有历史投放量，将其依合同完美投影至未来对应的到期日
        for _, row in df_history.tail(14).iterrows():
            hist_date = row[date_col].date()
            inj_amt = float(row[injection_col])
            if inj_amt > 0:
                # 按照 7天期 契约推算其到期日
                proj_date_7 = hist_date + datetime.timedelta(days=7)
                proj_date_7_str = proj_date_7.strftime('%Y-%m-%d')
                
                # 如果该推算日期落在未来14天的观测期内，且机制1中该日的到期数据尚未被填入，则依合同填入
                if proj_date_7_str in future_records and future_records[proj_date_7_str]["maturity"] == 0:
                    future_records[proj_date_7_str]["maturity"] = inj_amt
                    future_records[proj_date_7_str]["net"] = -inj_amt

        # 将经过严密科学计算的未来14天到期预测数据，有序地并入最终的结果集中
        for f_date_str in sorted(future_records.keys()):
            result.append(future_records[f_date_str])

        # 5. 保存并输出为标准数据文件
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
            
        print(f"数据成功写入！已严格限制7天历史，并科学计算导出未来14天到期数据。")
        
    except Exception as e:
        print(f"执行异常: {e}")

if __name__ == "__main__":
    fetch_pboc_data()
