import streamlit as st
import pandas as pd
import plotly.express as px
import awswrangler as wr
from datetime import datetime, timedelta
from dataclasses import dataclass
import boto3

# --------------------------------------------------
# 設定・定数
# --------------------------------------------------
@dataclass
class Config:
    athena_database: str = "fitbit"               # Athenaのデータベース名
    athena_output_s3: str = "s3://fitbit-dashboard" # Athenaクエリ結果の出力先S3バケット
    default_days: int = 60                          # デフォルトの読み込み日数
    metric_columns: dict = None                     # 各カテゴリの指標列名
    unit_columns: dict = None                       # 各カテゴリの単位

def init_config() -> Config:
    return Config(
        athena_database="fitbit",
        athena_output_s3="s3://fitbit-dashboard",
        default_days=60,
        metric_columns={
            "sleep": "total_sleep_hour",
            "steps": "steps",
            "high_intensity": "high_intensity_minutes"
        },
        unit_columns={
            "sleep": "hour",
            "steps": "steps",
            "high_intensity": "min"
        }
    )

# --------------------------------------------------
# ビジネスロジック
# --------------------------------------------------
def calculate_weekly_average(df: pd.DataFrame, metric: str) -> float:
    """直近1週間の平均値を計算します。"""
    today = datetime.now().date()
    start_date = today - timedelta(days=7)
    recent_data = df[(df["date"].dt.date >= start_date) & (df["date"].dt.date <= today)]
    avg = recent_data[metric].mean()
    return avg if not pd.isna(avg) else 0.0

@st.cache_data
def load_data_athena(category: str, config: Config, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    Athenaから指定カテゴリのデータを取得します。
    オプションでstart_date, end_dateを指定することで、日付フィルタを適用可能です。
    """
    table = category  # テーブル名はカテゴリ名と同一と仮定
    metric = config.metric_columns[category]
    date_filter = f"WHERE date BETWEEN '{start_date}' AND '{end_date}'" if start_date and end_date else ""
    query = f"""
    SELECT date, {metric}
    FROM {config.athena_database}.{table}
    {date_filter}
    """
    session = boto3.Session(region_name="ap-northeast-1")
    df = wr.athena.read_sql_query(
        query, 
        database=config.athena_database, 
        s3_output=config.athena_output_s3,
        boto3_session=session
    )
    # df = wr.athena.read_sql_query(query, database=config.athena_database, s3_output=config.athena_output_s3)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
        df[metric] = df[metric].astype(float)
    return df

def filter_data_by_date(df: pd.DataFrame, selected_start: datetime.date, selected_end: datetime.date) -> pd.DataFrame:
    """DataFrameを選択された日付範囲でフィルタします。"""
    return df[(df["date"].dt.date >= selected_start) & (df["date"].dt.date <= selected_end)].copy()

def plot_category_data(category: str, df: pd.DataFrame, config: Config, window: int = 30) -> None:
    """指定カテゴリのデータをグラフ表示します。"""
    metric = config.metric_columns[category]
    df["moving_avg"] = df[metric].rolling(window=window).mean()
    fig = px.bar(df, x="date", y=metric, title=f"{category.capitalize()}")
    fig.add_scatter(
        x=df["date"],
        y=df["moving_avg"],
        mode="lines",
        name=f"{window}日移動平均",
        line=dict(color="red")
    )
    st.plotly_chart(fig)

# --------------------------------------------------
# メイン処理
# --------------------------------------------------

# 設定の初期化とタイトル表示
config = init_config()
st.title("My Activity")

# デフォルトの日付範囲（直近 default_days 日）
today = datetime.now().date()
default_start = today - timedelta(days=config.default_days)
default_end = today - timedelta(days=1)

categories = ["sleep", "steps", "high_intensity"]

# Athenaから全データをロード（後でフィルタして利用）
data = {category: load_data_athena(category, config) for category in categories}

# 直近1週間の平均を数値カードで表示
st.header("直近1週間の平均")
cols = st.columns(len(categories))
for i, category in enumerate(categories):
    with cols[i]:
        avg_metric = calculate_weekly_average(data[category], config.metric_columns[category])
        st.metric(
            label=f"{category.capitalize()}の平均",
            value=f"{avg_metric:.1f} {config.unit_columns[category]}"
        )

# 日付範囲の選択
st.header("日付範囲の選択")
date_range = st.date_input("日付範囲を選択", value=(default_start, default_end))
selected_start, selected_end = date_range

# カテゴリ毎にグラフを表示
st.header("時系列推移")
for category in categories:
    # ユーザーが選択した範囲がデフォルトの範囲外の場合は再取得
    if selected_start < default_start or selected_end > default_end:
        df = load_data_athena(
            category,
            config,
            start_date=selected_start.strftime("%Y-%m-%d"),
            end_date=selected_end.strftime("%Y-%m-%d")
        )
    else:
        df = filter_data_by_date(data[category], selected_start, selected_end)
    
    plot_category_data(category, df, config, window=30)
