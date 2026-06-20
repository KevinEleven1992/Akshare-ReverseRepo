import akshare as ak
import pandas as pd
import json
import os

def fetch_pboc_data():
    print("开始从 AkShare 获取央行逆回购数据...")
    try:
        # 获取中国公开市场操作数据
        df = ak.macro_china_pboc_omo()
        
        # 打印列名以便调试
        print("获取到的数据列名:", df.columns.tolist())
        
        # AkShare 返回的常见列名有：'日期', '逆回购-操作量', '逆回购-到期量', '逆回购-净投放' 等
        # 我们进行标准重命名和过滤
        # 注意：这里做强校验和兼容处理
        date_col = '日期'
        injection_col = '逆回购-操作量'
        maturity_col = '逆回购-到期量'
        
        if date_col not in df.columns:
            # 如果列名不匹配，尝试寻找包含“日期”的列
            date_col = [c for c in df.columns if '日期' in c][0]
            
        # 转换日期格式为 YYYY-MM-DD
        df[date_col] = pd.to_datetime(df[date_col]).dt.strftime('%Y-%m-%d')
        
        result = []
        # 只取最近 180 天的数据（可根据需要调整，数据太多影响前端加载）
        df_recent = df.tail(180)
        
        for _, row in df_recent.iterrows():
            date_str = str(row[date_col])
            # 获取投放量和到期量（单位通常是亿元）
            injection = float(row.get(injection_col, 0) or 0)
            maturity = float(row.get(maturity_col, 0) or 0)
            net = float(row.get('逆回购-净投放', injection - maturity) or 0)
            
            # 只记录有操作或者有到期的日子
            if injection > 0 or maturity > 0:
                result.append({
                    "date": date_str,
                    "injection": injection,
                    "maturity": maturity,
                    "net": net
                })
        
        # 将数据保存为标准 JSON 格式
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
            
        print(f"数据抓取成功，共保存 {len(result)} 条记录数据。")
        
    except Exception as e:
        print(f"抓取数据发生错误: {e}")
        # 如果报错，生成一个空的或基础的 JSON，防止前端崩溃
        if not os.path.exists('data.json'):
            with open('data.json', 'w') as f:
                json.dump([], f)

if __name__ == "__main__":
    fetch_pboc_data()
