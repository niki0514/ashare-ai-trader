import akshare as ak
import pandas as pd

targets = [
    ("000547", "sz000547"),  # 航天发展
    ("000021", "sz000021"),  # 深科技
]
start_date = "2026-03-16"
end_date = "2026-03-18"
period = "1"  # 1 分钟
adjust = ""  # 不复权（你要真实当时成交价）


def fetch_and_save(sym_prefixed):
    print("fetching", sym_prefixed)
    # 优先调用 stock_zh_a_minute（Sina 分时封装），若无数据再尝试其他接口
    try:
        df = ak.stock_zh_a_minute(symbol=sym_prefixed, period=period, adjust=adjust)
    except Exception as e:
        print("stock_zh_a_minute failed:", e)
        df = None
    if df is None or df.shape[0] == 0:
        # 备用接口（若 akshare 版本支持）
        try:
            # 注意：不同 akshare 版本函数名/参数可能不同，这里只是尝试性调用
            df = ak.stock_zh_a_hist_min_em(
                symbol=sym_prefixed.replace("sz", ""),
                start_date=start_date + " 09:30:00",
                end_date=end_date + " 15:00:00",
                period=period,
                adjust=adjust,
            )
        except Exception as e:
            print("备用接口也失败:", e)
            df = None
    if df is None or df.shape[0] == 0:
        raise RuntimeError(
            f"无法通过 akshare 获取 {sym_prefixed} 的分钟数据（请升级 akshare 或改用 TuShare Pro）"
        )
    # 统一 datetime 列名
    if "datetime" in df.columns:
        df["dt"] = pd.to_datetime(df["datetime"])
    elif "time" in df.columns and "day" in df.columns:
        df["dt"] = pd.to_datetime(df["day"].astype(str) + " " + df["time"].astype(str))
    elif "time" in df.columns:
        # 部分接口只返回 time（当日），尝试推断日期
        df["dt"] = pd.to_datetime(df["time"].astype(str))
    else:
        # 尝试找到第一列能 parse 的
        parsed = False
        for c in df.columns:
            try:
                df["dt"] = pd.to_datetime(df[c])
                parsed = True
                break
            except Exception:
                continue
        if not parsed:
            raise RuntimeError("无法解析返回表的时间列，请检查 akshare 版本和接口返回格式")
    # filter range
    start_ts = pd.to_datetime(start_date + " 00:00:00")
    end_ts = pd.to_datetime(end_date + " 23:59:59")
    df = df[(df["dt"] >= start_ts) & (df["dt"] <= end_ts)].copy()
    df = df.sort_values("dt")
    # write csv
    out = sym_prefixed + "_1min_" + start_date + "_" + end_date + ".csv"
    df.rename(columns={"dt": "datetime"}, inplace=True)
    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df.to_csv(out, index=False)
    print("wrote", out, "rows=", len(df))
    return out


if __name__ == "__main__":
    outfiles = []
    for plain, sym in targets:
        try:
            outfiles.append(fetch_and_save(sym))
        except Exception as e:
            print("ERROR for", sym, e)
    print("done. files:", outfiles)
