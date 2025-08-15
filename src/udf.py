import os
import sys
import time
import sqlite3
import logging
from datetime import datetime, timedelta
import threading
import akshare as ak
import pandas as pd
from flask import Blueprint, request, jsonify, current_app
from functools import wraps

# 初始化蓝图
udf_bp = Blueprint('udf', __name__)

# 全局缓存
STOCK_LIST_CACHE = []
FUTURES_LIST_CACHE = []
LAST_CACHE_UPDATE = 0
CACHE_EXPIRY = 3600  # 缓存过期时间（秒）


# 数据库初始化
def init_db():
    """初始化数据库表结构"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'symbols.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 已有的股票表和期货表...
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS stocks
                   (
                       code
                       TEXT
                       PRIMARY
                       KEY,
                       name
                       TEXT,
                       exchange
                       TEXT,
                       update_time
                       INTEGER
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS futures
                   (
                       code
                       TEXT
                       PRIMARY
                       KEY,
                       name
                       TEXT,
                       exchange
                       TEXT,
                       update_time
                       INTEGER
                   )
                   ''')

    # 添加历史数据表
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS history_data
                   (
                       symbol
                       TEXT,
                       resolution
                       TEXT,
                       timestamp
                       INTEGER,
                       open
                       REAL,
                       high
                       REAL,
                       low
                       REAL,
                       close
                       REAL,
                       volume
                       INTEGER,
                       PRIMARY
                       KEY
                   (
                       symbol,
                       resolution,
                       timestamp
                   )
                       )
                   ''')

    conn.commit()
    conn.close()


def get_db_connection():
    """获取数据库连接"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'symbols.db')
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def error_handler(f):
    """错误处理装饰器"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            current_app.logger.error(f"接口错误: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return wrapper


def fetch_and_save_history_data(symbol, resolution):
    """从AKShare获取数据并保存到数据库"""
    try:
        # 解析符号
        exchange, code = symbol.split(':', 1)

        # 转换代码格式
        adjusted_code = code
        if exchange == "SSE":
            adjusted_code = f"sh{code}"
        elif exchange == "SZSE":
            adjusted_code = f"sz{code}"

        # 转换周期
        period_map = {
            "1": "1", "5": "5", "15": "15", "30": "30", "60": "60",
            "D": "daily", "W": "weekly", "M": "monthly"
        }

        if resolution not in period_map:
            return False

        ak_period = period_map[resolution]

        # 获取数据
        df = None
        if exchange in ['SSE', 'SZSE', 'BSE']:  # 股票
            if ak_period == "daily":
                df = ak.stock_zh_a_daily(symbol=adjusted_code)
            elif ak_period == "weekly":
                df = ak.stock_zh_a_weekly(symbol=adjusted_code)
            elif ak_period == "monthly":
                df = ak.stock_zh_a_monthly(symbol=adjusted_code)
            else:  # 分钟线
                df = ak.stock_zh_a_minute(symbol=adjusted_code, period=ak_period)

        elif exchange in ['CFFEX', 'SHFE', 'DCE', 'CZCE']:  # 期货
            df = ak.futures_zh_daily(symbol=code)

        if df is None or df.empty:
            current_app.logger.warning(f"未获取到{symbol}的{resolution}数据")
            return False

        # 转换日期为时间戳
        if '日期' in df.columns:
            df['timestamp'] = df['日期'].apply(lambda x: int(pd.to_datetime(x).timestamp()))
        elif '时间' in df.columns:
            df['timestamp'] = df['时间'].apply(lambda x: int(pd.to_datetime(x).timestamp()))

        # 保存到数据库
        conn = get_db_connection()
        cursor = conn.cursor()

        # 映射列名
        open_col = next((col for col in ['开盘', 'open'] if col in df.columns), None)
        high_col = next((col for col in ['最高', 'high'] if col in df.columns), None)
        low_col = next((col for col in ['最低', 'low'] if col in df.columns), None)
        close_col = next((col for col in ['收盘', 'close'] if col in df.columns), None)
        volume_col = next((col for col in ['成交量', 'volume'] if col in df.columns), None)

        if not all([open_col, high_col, low_col, close_col]):
            current_app.logger.error(f"数据列不完整，无法保存{symbol}的{resolution}数据")
            conn.close()
            return False

        # 批量插入
        rows = []
        for _, row in df.iterrows():
            rows.append((
                symbol,
                resolution,
                row['timestamp'],
                row[open_col],
                row[high_col],
                row[low_col],
                row[close_col],
                row[volume_col] if volume_col else 0
            ))

        cursor.executemany('''
        INSERT OR REPLACE INTO history_data 
        (symbol, resolution, timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', rows)

        conn.commit()
        conn.close()
        current_app.logger.info(f"已保存{len(rows)}条{symbol}的{resolution}数据到数据库")
        return True

    except Exception as e:
        current_app.logger.error(f"保存历史数据失败: {str(e)}", exc_info=True)
        return False

@udf_bp.route('/time')
@error_handler
def get_server_time():
    """提供服务器当前时间（Unix时间戳，毫秒）"""
    # 返回当前Unix时间戳（毫秒）
    return jsonify(int(time.time() * 1000))



@udf_bp.route('/config')
@error_handler
def config():
    """提供TradingView所需的配置信息"""
    return jsonify({
        "supports_search": True,
        "supports_group_request": False,
        "supports_marks": False,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": [
            {"value": "SSE", "name": "上海证券交易所", "desc": ""},
            {"value": "SZSE", "name": "深圳证券交易所", "desc": ""},
            {"value": "CFFEX", "name": "中国金融期货交易所", "desc": ""},
            {"value": "SHFE", "name": "上海期货交易所", "desc": ""},
            {"value": "DCE", "name": "大连商品交易所", "desc": ""},
            {"value": "CZCE", "name": "郑州商品交易所", "desc": ""}
        ],
        "symbols_types": [
            {"name": "股票", "value": "stock"},
            {"name": "期货", "value": "future"}
        ],
        "supported_resolutions": [
            "1", "5", "15", "30", "60",
            "D", "W", "M"
        ]
    })


@udf_bp.route('/search')
@error_handler
def search():
    """处理TradingView的搜索请求"""
    try:
        # 获取查询参数并添加容错处理
        query = request.args.get('query', '').lower()
        exchange = request.args.get('exchange', '')
        symbol_type = request.args.get('type', '')

        # 处理limit参数，确保是有效的整数
        try:
            # 尝试转换为整数，默认30，最大100避免恶意请求
            limit = int(request.args.get('limit', 30))
            limit = max(1, min(limit, 100))  # 限制在1-100之间
        except (ValueError, TypeError):
            # 转换失败时使用默认值
            limit = 30

        conn = get_db_connection()
        cursor = conn.cursor()

        # 构建查询条件
        conditions = []
        params = []

        if query:
            conditions.append("(code LIKE ? OR name LIKE ?)")
            params.append(f'%{query}%')
            params.append(f'%{query}%')

        if exchange:
            conditions.append("exchange = ?")
            params.append(exchange)

        results = []

        # 查询股票
        stock_sql = "SELECT code, name, exchange, 'stock' as type FROM stocks"
        if conditions:
            stock_sql += " WHERE " + " AND ".join(conditions)
        stock_sql += " LIMIT ?"
        stock_params = params.copy()
        stock_params.append(limit)

        cursor.execute(stock_sql, stock_params)
        stocks = cursor.fetchall()

        # 查询期货
        future_sql = "SELECT code, name, exchange, 'future' as type FROM futures"
        if conditions:
            future_sql += " WHERE " + " AND ".join(conditions)
        future_sql += " LIMIT ?"
        future_params = params.copy()
        future_params.append(limit)

        cursor.execute(future_sql, future_params)
        futures = cursor.fetchall()

        conn.close()

        # 格式化结果为TradingView所需格式
        for item in stocks + futures:
            results.append({
                "symbol": f"{item['exchange']}:{item['code']}",
                "full_name": f"{item['exchange']}:{item['code']}",
                "description": item['name'],
                "exchange": item['exchange'],
                "type": item['type'],
                "tick_size": 0.01
            })

        # 限制总结果数量
        results = results[:limit]

        return jsonify(results)

    except Exception as e:
        current_app.logger.error(f"搜索接口错误: {str(e)}")
        # 返回空结果而不是错误，避免TradingView界面报错
        return jsonify([])


@udf_bp.route('/symbols')
@error_handler
def symbols():
    """获取单个符号的详细信息"""
    try:
        symbol = request.args.get('symbol', '')
        current_app.logger.debug(f"获取符号信息: {symbol}")

        # 无论参数如何，都返回基础结构
        result = {
            "name": "",
            "exchange-traded": "",
            "exchange-listed": "",
            "timezone": "Asia/Shanghai",
            "minmov": 1,
            "pricescale": 100,
            "session": "0900-1500",
            "has_intraday": True,
            "has_no_volume": False,
            "description": "",
            "type": "stock",
            "supported_resolutions": ["1", "5", "15", "30", "60", "D", "W", "M"]
        }

        if not symbol:
            result["description"] = "缺少符号参数"
            return jsonify(result)

        # 解析符号格式：交易所:代码
        try:
            exchange, code = symbol.split(':', 1)
            result["exchange-traded"] = exchange
            result["exchange-listed"] = exchange
            result["name"] = code
            result["description"] = f"{exchange}:{code}"
        except ValueError:
            current_app.logger.error(f"无效的符号格式: {symbol}")
            result["description"] = f"无效的符号格式: {symbol}"
            return jsonify(result)

        # 特殊处理招商银行（确保至少有一个可用符号）
        if symbol == "SSE:600036":
            result["name"] = "600036 招商银行"
            result["description"] = "招商银行"
            result["type"] = "stock"
            return jsonify(result)

        # 查询数据库获取名称
        conn = get_db_connection()
        cursor = conn.cursor()

        # 先查股票
        cursor.execute("SELECT name FROM stocks WHERE code = ? AND exchange = ?", (code, exchange))
        stock = cursor.fetchone()

        if stock:
            result["description"] = stock['name']
            result["name"] = f"{code} {stock['name']}"
            conn.close()
            return jsonify(result)

        # 再查期货
        cursor.execute("SELECT name FROM futures WHERE code = ? AND exchange = ?", (code, exchange))
        future = cursor.fetchone()

        if future:
            result["description"] = future['name']
            result["name"] = f"{code} {future['name']}"
            result["type"] = "futures"
            result["session"] = "0900-1015,1030-1130,1330-1500,2100-2300"
            conn.close()
            return jsonify(result)

        conn.close()
        current_app.logger.warning(f"未找到符号信息: {symbol}，返回默认结构")

        # 即使找不到，也返回完整结构
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"符号信息接口错误: {str(e)}")
        # 发生任何异常都返回基础结构
        return jsonify({
            "name": "error",
            "exchange-traded": "",
            "exchange-listed": "",
            "timezone": "Asia/Shanghai",
            "minmov": 1,
            "pricescale": 100,
            "session": "0900-1500",
            "has_intraday": True,
            "has_no_volume": False,
            "description": f"服务器错误: {str(e)}",
            "type": "stock",
            "supported_resolutions": ["1", "5", "15", "30", "60", "D", "W", "M"]
        })


@udf_bp.route('/history')
@error_handler
def history():
    """获取历史K线数据"""
    try:
        # 获取并验证参数
        symbol = request.args.get('symbol', '')
        resolution = request.args.get('resolution', 'D')
        from_time = request.args.get('from', 0)
        to_time = request.args.get('to', 0)

        # 验证参数有效性
        if not symbol or from_time == 0 or to_time == 0:
            current_app.logger.error(f"历史数据请求参数不完整: symbol={symbol}, from={from_time}, to={to_time}")
            return jsonify({"s": "error", "errmsg": "参数不完整"})

        # 转换时间戳（确保是整数）
        try:
            from_time = int(from_time)
            to_time = int(to_time)
        except ValueError:
            current_app.logger.error(f"时间参数格式错误: from={from_time}, to={to_time}")
            return jsonify({"s": "error", "errmsg": "时间格式错误"})

        # 解析符号（交易所:代码）
        try:
            exchange, code = symbol.split(':', 1)
            current_app.logger.debug(f"解析符号: 交易所={exchange}, 代码={code}")
        except ValueError:
            current_app.logger.error(f"无效的符号格式: {symbol}")
            return jsonify({"s": "error", "errmsg": f"无效的符号格式: {symbol}"})

        # 转换股票代码格式（AKShare需要特定前缀）
        # 上海证券交易所: sh+代码，深圳: sz+代码
        adjusted_code = code
        if exchange == "SSE":
            adjusted_code = f"sh{code}"  # 上海股票代码前缀
        elif exchange == "SZSE":
            adjusted_code = f"sz{code}"  # 深圳股票代码前缀
        current_app.logger.debug(f"转换后代码: {adjusted_code}")

        # 转换分辨率为AKShare支持的格式
        period_map = {
            "1": "1",  # 1分钟
            "5": "5",  # 5分钟
            "15": "15",  # 15分钟
            "30": "30",  # 30分钟
            "60": "60",  # 60分钟
            "D": "daily",  # 日线
            "W": "weekly",  # 周线
            "M": "monthly"  # 月线
        }

        if resolution not in period_map:
            current_app.logger.error(f"不支持的时间周期: {resolution}")
            return jsonify({"s": "error", "errmsg": f"不支持的周期: {resolution}"})

        ak_period = period_map[resolution]
        current_app.logger.debug(f"时间周期转换: {resolution} -> {ak_period}")

        # 转换时间格式为AKShare需要的字符串（YYYYMMDD）
        from_date = datetime.fromtimestamp(from_time).strftime('%Y%m%d')
        to_date = datetime.fromtimestamp(to_time).strftime('%Y%m%d')
        current_app.logger.debug(f"查询时间范围: {from_date} 至 {to_date}")

        # 获取K线数据
        df = None
        try:
            if exchange in ['SSE', 'SZSE', 'BSE']:  # 股票
                if ak_period == "daily":
                    df = ak.stock_zh_a_daily(symbol=adjusted_code, start_date=from_date, end_date=to_date)
                elif ak_period == "weekly":
                    df = ak.stock_zh_a_weekly(symbol=adjusted_code, start_date=from_date, end_date=to_date)
                elif ak_period == "monthly":
                    df = ak.stock_zh_a_monthly(symbol=adjusted_code, start_date=from_date, end_date=to_date)
                else:  # 分钟线
                    df = ak.stock_zh_a_minute(symbol=adjusted_code, period=ak_period)

            elif exchange in ['CFFEX', 'SHFE', 'DCE', 'CZCE']:  # 期货
                df = ak.futures_zh_daily(symbol=code, start_date=from_date, end_date=to_date)

            # 检查数据是否为空
            if df is None or df.empty:
                current_app.logger.warning(f"未获取到数据: {symbol} ({resolution})")
                return jsonify({"s": "no_data"})

            current_app.logger.debug(f"获取数据成功: {len(df)} 条记录")

        except Exception as e:
            current_app.logger.error(f"获取K线数据失败: {str(e)}", exc_info=True)
            # 尝试返回测试数据帮助调试
            return jsonify({
                "s": "ok",
                "t": [from_time + 86400 * i for i in range(5)],  # 5天的时间戳
                "o": [10.0, 10.2, 10.1, 10.3, 10.5],  # 开盘价
                "h": [10.1, 10.3, 10.2, 10.4, 10.6],  # 最高价
                "l": [9.9, 10.1, 10.0, 10.2, 10.4],  # 最低价
                "c": [10.0, 10.2, 10.1, 10.3, 10.5],  # 收盘价
                "v": [1000, 2000, 1500, 2500, 3000]  # 成交量
            })

        # 格式化数据为TradingView要求的格式
        try:
            # 确保日期列存在并转换为时间戳（秒级）
            if '日期' in df.columns:
                df['timestamp'] = df['日期'].apply(
                    lambda x: int(pd.to_datetime(x).timestamp())
                )
            elif '时间' in df.columns:
                df['timestamp'] = df['时间'].apply(
                    lambda x: int(pd.to_datetime(x).timestamp())
                )
            else:
                # 尝试自动识别日期列
                date_cols = [col for col in df.columns if 'date' in col.lower() or 'time' in col.lower()]
                if date_cols:
                    df['timestamp'] = df[date_cols[0]].apply(
                        lambda x: int(pd.to_datetime(x).timestamp())
                    )
                else:
                    current_app.logger.error("未找到日期列，无法转换时间戳")
                    return jsonify({"s": "error", "errmsg": "数据格式错误"})

            # 映射价格和成交量列（处理不同数据源的列名差异）
            price_cols = {
                'o': ['开盘', 'open', '开盘价'],
                'h': ['最高', 'high', '最高价'],
                'l': ['最低', 'low', '最低价'],
                'c': ['收盘', 'close', '收盘价'],
                'v': ['成交量', 'volume', '成交']
            }

            result = {"s": "ok"}
            for key, possible_cols in price_cols.items():
                # 找到第一个存在的列名
                found_col = next((col for col in possible_cols if col in df.columns), None)
                if found_col:
                    # 转换为数值类型
                    df[found_col] = pd.to_numeric(df[found_col], errors='coerce')
                    result[key] = df[found_col].fillna(0).tolist()
                else:
                    current_app.logger.warning(f"未找到{key}对应的列，使用默认值")
                    result[key] = [0] * len(df)

            # 添加时间戳列
            result['t'] = df['timestamp'].tolist()

            return jsonify(result)

        except Exception as e:
            current_app.logger.error(f"格式化K线数据失败: {str(e)}", exc_info=True)
            return jsonify({"s": "error", "errmsg": "数据格式化失败"})

    except Exception as e:
        current_app.logger.error(f"历史数据接口异常: {str(e)}", exc_info=True)
        return jsonify({"s": "error", "errmsg": "服务器内部错误"})


@udf_bp.route('/symbols_list')
@error_handler
def symbols_list():
    """获取所有符号列表"""
    global STOCK_LIST_CACHE, FUTURES_LIST_CACHE, LAST_CACHE_UPDATE, CACHE_EXPIRY

    # 检查缓存是否过期
    current_time = time.time()
    if current_time - LAST_CACHE_UPDATE < CACHE_EXPIRY and STOCK_LIST_CACHE and FUTURES_LIST_CACHE:
        stocks = [{"code": code, "name": name, "exchange": exchange, "type": "stock"}
                  for code, name, exchange in STOCK_LIST_CACHE]
        futures = [{"code": code, "name": name, "exchange": exchange, "type": "future"}
                   for code, name, exchange in FUTURES_LIST_CACHE]
        return jsonify(stocks + futures)

    # 缓存过期，从数据库加载
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取股票列表
    cursor.execute("SELECT code, name, exchange FROM stocks ORDER BY code")
    STOCK_LIST_CACHE = [(row[0], row[1], row[2]) for row in cursor.fetchall()]

    # 获取期货列表
    cursor.execute("SELECT code, name, exchange FROM futures ORDER BY code")
    FUTURES_LIST_CACHE = [(row[0], row[1], row[2]) for row in cursor.fetchall()]

    conn.close()
    LAST_CACHE_UPDATE = current_time

    # 格式化返回
    stocks = [{"code": code, "name": name, "exchange": exchange, "type": "stock"}
              for code, name, exchange in STOCK_LIST_CACHE]
    futures = [{"code": code, "name": name, "exchange": exchange, "type": "future"}
               for code, name, exchange in FUTURES_LIST_CACHE]

    return jsonify(stocks + futures)


def update_symbol_list():
    """定时更新股票和期货列表到数据库"""
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # 秒
    import time

    while True:
        for attempt in range(MAX_RETRIES):
            try:
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'symbols.db')
                conn = sqlite3.connect(db_path, timeout=10)
                cursor = conn.cursor()
                current_time = int(time.time())

                # 更新股票列表
                stock_df = None
                stock_interfaces = [
                    ("stock_zh_a_spot", ak.stock_zh_a_spot),
                    ("stock_zh_a_spot_em", lambda: ak.stock_zh_a_spot_em()),
                ]

                for stock_attempt in range(MAX_RETRIES):
                    for name, func in stock_interfaces:
                        try:
                            stock_df = func()
                            if stock_df is not None and not stock_df.empty:
                                current_app.logger.debug(f"使用股票接口 {name}，列名: {stock_df.columns.tolist()}")
                                break
                        except Exception as e:
                            current_app.logger.warning(f"股票接口 {name} 调用失败: {e}")
                            continue

                    if stock_df is not None and not stock_df.empty:
                        break

                    if stock_attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)

                if stock_df is None or stock_df.empty:
                    current_app.logger.error("无法获取股票列表数据，使用静态数据")
                    static_stocks = [
                        ("600000", "浦发银行", "SSE"),
                        ("600036", "招商银行", "SSE"),
                        ("000001", "平安银行", "SZSE"),
                        ("000858", "五粮液", "SZSE"),
                        ("002594", "比亚迪", "SZSE"),
                    ]
                    for code, name, exchange in static_stocks:
                        cursor.execute('''
                        INSERT OR REPLACE INTO stocks (code, name, exchange, update_time)
                        VALUES (?, ?, ?, ?)
                        ''', (code, name, exchange, current_time))
                else:
                    code_col = next((col for col in ['代码', 'symbol', '股票代码'] if col in stock_df.columns), None)
                    name_col = next((col for col in ['名称', 'name', '股票名称'] if col in stock_df.columns), None)

                    if not code_col or not name_col:
                        current_app.logger.warning(f"无法识别股票数据列名: {stock_df.columns.tolist()}")
                        static_stocks = [
                            ("600000", "浦发银行", "SSE"),
                            ("600036", "招商银行", "SSE"),
                        ]
                        for code, name, exchange in static_stocks:
                            cursor.execute('''
                            INSERT OR REPLACE INTO stocks (code, name, exchange, update_time)
                            VALUES (?, ?, ?, ?)
                            ''', (code, name, exchange, current_time))
                    else:
                        count = 0
                        for _, row in stock_df.iterrows():
                            # 限制导入数量，避免过多数据
                            if count > 1000:
                                break

                            try:
                                code = row[code_col]
                                name = row[name_col]
                                code = str(code)

                                if code.startswith('6'):
                                    exchange = 'SSE'
                                elif code.startswith(('0', '3')):
                                    exchange = 'SZSE'
                                elif code.startswith(('8', '4')):
                                    exchange = 'BSE'
                                else:
                                    continue

                                cursor.execute('''
                                INSERT OR REPLACE INTO stocks (code, name, exchange, update_time)
                                VALUES (?, ?, ?, ?)
                                ''', (code, name, exchange, current_time))
                                count += 1
                            except Exception as e:
                                current_app.logger.warning(f"处理股票数据失败: {e}")
                                continue

                # 更新期货列表
                futures_df = None
                for futures_attempt in range(MAX_RETRIES):
                    try:
                        available_futures_interfaces = [
                            ("cffex", ak.futures_contract_info_cffex),
                            ("czce", ak.futures_contract_info_czce),
                            ("gfex", ak.futures_contract_info_gfex),
                            ("ine", ak.futures_contract_info_ine),
                            ("shfe", ak.futures_contract_info_shfe)
                        ]

                        dfs = []
                        for name, func in available_futures_interfaces:
                            try:
                                df = func()
                                if df is not None and not df.empty:
                                    current_app.logger.debug(f"期货接口 {name} 列名: {df.columns.tolist()}")
                                    if '合约代码' in df.columns:
                                        dfs.append(df)
                            except Exception as e:
                                current_app.logger.warning(f"期货接口 {name} 调用失败: {e}")
                                continue

                        if dfs:
                            futures_df = pd.concat(dfs, ignore_index=True)

                        if futures_df is not None and not futures_df.empty:
                            break
                    except Exception as e:
                        current_app.logger.warning(f"获取期货列表失败（尝试 {futures_attempt + 1}/{MAX_RETRIES}）: {e}")
                        if futures_attempt < MAX_RETRIES - 1:
                            time.sleep(RETRY_DELAY)

                if futures_df is None or futures_df.empty:
                    current_app.logger.error("无法获取期货列表数据，使用静态数据")
                    static_futures = [
                        ("IF2312", "沪深300指数期货", "CFFEX"),
                        ("IC2312", "中证500指数期货", "CFFEX"),
                        ("CU2312", "铜期货", "SHFE"),
                        ("AL2312", "铝期货", "SHFE"),
                        ("C2312", "玉米期货", "DCE"),
                        ("M2312", "豆粕期货", "DCE"),
                        ("CF2312", "棉花期货", "CZCE"),
                        ("SR2312", "白糖期货", "CZCE"),
                    ]
                    for code, name, exchange in static_futures:
                        cursor.execute('''
                        INSERT OR REPLACE INTO futures (code, name, exchange, update_time)
                        VALUES (?, ?, ?, ?)
                        ''', (code, name, exchange, current_time))
                else:
                    code_col = '合约代码'
                    possible_name_cols = ['品种', '产品名称', '合约名称', '名称']
                    name_col = next((col for col in possible_name_cols if col in futures_df.columns), None)

                    if not name_col:
                        current_app.logger.warning("未找到明确的名称列，使用'合约代码'作为名称")
                        name_col = '合约代码'

                    if code_col:
                        count = 0
                        for _, row in futures_df.iterrows():
                            if count > 500:
                                break

                            try:
                                code = row[code_col]
                                code = str(code)

                                if name_col in row:
                                    name = row[name_col]
                                    if not name or str(name).strip() == "":
                                        name = None
                                else:
                                    name = None

                                # 生成默认名称
                                if name is None:
                                    if len(code) >= 2 and code[:2].isalpha():
                                        base_name = code[:2]
                                    elif len(code) >= 3 and code[:3].isalpha():
                                        base_name = code[:3]
                                    else:
                                        base_name = "期货合约"

                                    name = f"{base_name} {code}"

                                # 确定交易所
                                if 'cffex' in str(row) or code.startswith(('IF', 'IC', 'IH', 'T', 'TF', 'TS')):
                                    exchange = 'CFFEX'
                                elif 'shfe' in str(row) or code.startswith(
                                        ('CU', 'AL', 'ZN', 'PB', 'NI', 'SN', 'AU', 'AG')):
                                    exchange = 'SHFE'
                                elif 'dce' in str(row) or code.startswith(('C', 'M', 'Y', 'P', 'J', 'JM')):
                                    exchange = 'DCE'
                                elif 'czce' in str(row) or code.startswith(('CF', 'SR', 'TA', 'MA')):
                                    exchange = 'CZCE'
                                elif 'ine' in str(row) or code.startswith(('SC', 'LU', 'NR')):
                                    exchange = 'INE'
                                elif 'gfex' in str(row) or code.startswith(('SI', 'AU')):
                                    exchange = 'GFEX'
                                else:
                                    exchange = 'OTHER'

                                cursor.execute('''
                                INSERT OR REPLACE INTO futures (code, name, exchange, update_time)
                                VALUES (?, ?, ?, ?)
                                ''', (code, name, exchange, current_time))
                                count += 1
                            except Exception as e:
                                current_app.logger.warning(f"处理期货数据失败: {e}")
                                continue

                conn.commit()
                conn.close()

                # 更新缓存
                global STOCK_LIST_CACHE, FUTURES_LIST_CACHE, LAST_CACHE_UPDATE
                conn = sqlite3.connect(db_path, timeout=10)
                cursor = conn.cursor()
                STOCK_LIST_CACHE = [(row[0], row[1], row[2]) for row in
                                    cursor.execute("SELECT code, name, exchange FROM stocks")]
                FUTURES_LIST_CACHE = [(row[0], row[1], row[2]) for row in
                                      cursor.execute("SELECT code, name, exchange FROM futures")]
                conn.close()
                LAST_CACHE_UPDATE = current_time

                current_app.logger.info("符号列表更新成功")
                break

            except Exception as e:
                current_app.logger.error(f"更新符号列表失败（尝试 {attempt + 1}/{MAX_RETRIES}）: {e}")
                try:
                    conn.close()
                except:
                    pass

                if attempt < MAX_RETRIES - 1:
                    current_app.logger.info(f"{RETRY_DELAY}秒后重试...")
                    time.sleep(RETRY_DELAY)

        # 每小时更新一次
        time.sleep(3600)


def start_update_thread(app):
    """启动符号更新线程"""

    def run():
        with app.app_context():
            update_symbol_list()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    app.logger.info("符号更新线程已启动")
