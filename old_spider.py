import asyncio
import sys
import os
import argparse
import math
import json
import random
import base64
import re
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIStatusError
from playwright.async_api import async_playwright, Response, TimeoutError as PlaywrightTimeoutError
from requests.exceptions import HTTPError

# 定义登录状态文件的路径
STATE_FILE = "xianyu_state.json"
# 定义闲鱼搜索API的URL特征
API_URL_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search"
# 定义闲鱼详情页API的URL特征
DETAIL_API_URL_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail"

# --- AI & Notification Configuration ---
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
NTFY_TOPIC_URL = os.getenv("NTFY_TOPIC_URL")
WX_BOT_URL = os.getenv("WX_BOT_URL")
PCURL_TO_MOBILE = os.getenv("PCURL_TO_MOBILE")
RUN_HEADLESS = os.getenv("RUN_HEADLESS", "true").lower() != "false"

# 检查配置是否齐全
if not all([BASE_URL, MODEL_NAME]):
    sys.exit("错误：请确保在 .env 文件中完整设置了 OPENAI_BASE_URL 和 OPENAI_MODEL_NAME。(OPENAI_API_KEY 对于某些服务是可选的)")

# 初始化 OpenAI 客户端
try:
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
except Exception as e:
    sys.exit(f"初始化 OpenAI 客户端时出错: {e}")

# 定义目录和文件名
IMAGE_SAVE_DIR = "images"
os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)

# 定义下载图片所需的请求头
IMAGE_DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0',
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def convert_goofish_link(url: str) -> str:
    """
    将Goofish商品链接转换为只包含商品ID的手机端格式。

    Args:
        url: 原始的Goofish商品链接。

    Returns:
        转换后的简洁链接，或在无法解析时返回原始链接。
    """
    # 匹配第一个链接中的商品ID模式：item?id= 后面的数字串
    match_first_link = re.search(r'item\?id=(\d+)', url)
    if match_first_link:
        item_id = match_first_link.group(1)
        return f"https://pages.goofish.com/sharexy?loadingVisible=false&bft=item&bfs=idlepc.item&spm=a21ybx.item.0.0&bfp={{\"id\":{item_id}}}"

    return url

def get_link_unique_key(link: str) -> str:
    """截取链接中第一个"&"之前的内容作为唯一标识依据。"""
    return link.split('&', 1)[0]

async def random_sleep(min_seconds: float, max_seconds: float):
    """异步等待一个在指定范围内的随机时间。"""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"   [延迟] 等待 {delay:.2f} 秒... (范围: {min_seconds}-{max_seconds}s)") # 调试时可以取消注释
    await asyncio.sleep(delay)

async def save_to_jsonl(data_record: dict, keyword: str):
    """将一个包含商品和卖家信息的完整记录追加保存到 .jsonl 文件。"""
    filename = f"{keyword.replace(' ', '_')}_full_data.jsonl"
    try:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(data_record, ensure_ascii=False) + "\n")
        return True
    except IOError as e:
        print(f"写入文件 {filename} 出错: {e}")
        return False

async def calculate_reputation_from_ratings(ratings_json: list) -> dict:
    """从原始评价API数据列表中，计算作为卖家和买家的好评数与好评率。"""
    seller_total = 0
    seller_positive = 0
    buyer_total = 0
    buyer_positive = 0

    for card in ratings_json:
        # 使用 safe_get 保证安全访问
        data = await safe_get(card, 'cardData', default={})
        role_tag = await safe_get(data, 'rateTagList', 0, 'text', default='')
        rate_type = await safe_get(data, 'rate') # 1=好评, 0=中评, -1=差评

        if "卖家" in role_tag:
            seller_total += 1
            if rate_type == 1:
                seller_positive += 1
        elif "买家" in role_tag:
            buyer_total += 1
            if rate_type == 1:
                buyer_positive += 1

    # 计算比率，并处理除以零的情况
    seller_rate = f"{(seller_positive / seller_total * 100):.2f}%" if seller_total > 0 else "N/A"
    buyer_rate = f"{(buyer_positive / buyer_total * 100):.2f}%" if buyer_total > 0 else "N/A"

    return {
        "作为卖家的好评数": f"{seller_positive}/{seller_total}",
        "作为卖家的好评率": seller_rate,
        "作为买家的好评数": f"{buyer_positive}/{buyer_total}",
        "作为买家的好评率": buyer_rate
    }

async def _parse_user_items_data(items_json: list) -> list:
    """解析用户主页的商品列表API的JSON数据。"""
    parsed_list = []
    for card in items_json:
        data = card.get('cardData', {})
        status_code = data.get('itemStatus')
        if status_code == 0:
            status_text = "在售"
        elif status_code == 1:
            status_text = "已售"
        else:
            status_text = f"未知状态 ({status_code})"

        parsed_list.append({
            "商品ID": data.get('id'),
            "商品标题": data.get('title'),
            "商品价格": data.get('priceInfo', {}).get('price'),
            "商品主图": data.get('picInfo', {}).get('picUrl'),
            "商品状态": status_text
        })
    return parsed_list


async def scrape_user_profile(context, user_id: str) -> dict:
    """
    【新版】访问指定用户的个人主页，按顺序采集其摘要信息、完整的商品列表和完整的评价列表。
    """
    print(f"   -> 开始采集用户ID: {user_id} 的完整信息...")
    profile_data = {}
    page = await context.new_page()

    # 为各项异步任务准备Future和数据容器
    head_api_future = asyncio.get_event_loop().create_future()

    all_items, all_ratings = [], []
    stop_item_scrolling, stop_rating_scrolling = asyncio.Event(), asyncio.Event()

    async def handle_response(response: Response):
        # 捕获头部摘要API
        if "mtop.idle.web.user.page.head" in response.url and not head_api_future.done():
            try:
                head_api_future.set_result(await response.json())
                print(f"      [API捕获] 用户头部信息... 成功")
            except Exception as e:
                if not head_api_future.done(): head_api_future.set_exception(e)

        # 捕获商品列表API
        elif "mtop.idle.web.xyh.item.list" in response.url:
            try:
                data = await response.json()
                all_items.extend(data.get('data', {}).get('cardList', []))
                print(f"      [API捕获] 商品列表... 当前已捕获 {len(all_items)} 件")
                if not data.get('data', {}).get('nextPage', True):
                    stop_item_scrolling.set()
            except Exception as e:
                stop_item_scrolling.set()

        # 捕获评价列表API
        elif "mtop.idle.web.trade.rate.list" in response.url:
            try:
                data = await response.json()
                all_ratings.extend(data.get('data', {}).get('cardList', []))
                print(f"      [API捕获] 评价列表... 当前已捕获 {len(all_ratings)} 条")
                if not data.get('data', {}).get('nextPage', True):
                    stop_rating_scrolling.set()
            except Exception as e:
                stop_rating_scrolling.set()

    page.on("response", handle_response)

    try:
        # --- 任务1: 导航并采集头部信息 ---
        await page.goto(f"https://www.goofish.com/personal?userId={user_id}", wait_until="domcontentloaded", timeout=20000)
        head_data = await asyncio.wait_for(head_api_future, timeout=15)
        profile_data = await parse_user_head_data(head_data)

        # --- 任务2: 滚动加载所有商品 (默认页面) ---
        print("      [采集阶段] 开始采集该用户的商品列表...")
        await random_sleep(2, 4) # 等待第一页商品API完成
        while not stop_item_scrolling.is_set():
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            try:
                await asyncio.wait_for(stop_item_scrolling.wait(), timeout=8)
            except asyncio.TimeoutError:
                print("      [滚动超时] 商品列表可能已加载完毕。")
                break
        profile_data["卖家发布的商品列表"] = await _parse_user_items_data(all_items)

        # --- 任务3: 点击并采集所有评价 ---
        print("      [采集阶段] 开始采集该用户的评价列表...")
        rating_tab_locator = page.locator("//div[text()='信用及评价']/ancestor::li")
        if await rating_tab_locator.count() > 0:
            await rating_tab_locator.click()
            await random_sleep(3, 5) # 等待第一页评价API完成

            while not stop_rating_scrolling.is_set():
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                try:
                    await asyncio.wait_for(stop_rating_scrolling.wait(), timeout=8)
                except asyncio.TimeoutError:
                    print("      [滚动超时] 评价列表可能已加载完毕。")
                    break

            profile_data['卖家收到的评价列表'] = await parse_ratings_data(all_ratings)
            reputation_stats = await calculate_reputation_from_ratings(all_ratings)
            profile_data.update(reputation_stats)
        else:
            print("      [警告] 未找到评价选项卡，跳过评价采集。")

    except Exception as e:
        print(f"   [错误] 采集用户 {user_id} 信息时发生错误: {e}")
    finally:
        page.remove_listener("response", handle_response)
        await page.close()
        print(f"   -> 用户 {user_id} 信息采集完成。")

    return profile_data

async def parse_user_head_data(head_json: dict) -> dict:
    """解析用户头部API的JSON数据。"""
    data = head_json.get('data', {})
    ylz_tags = await safe_get(data, 'module', 'base', 'ylzTags', default=[])
    seller_credit, buyer_credit = {}, {}
    for tag in ylz_tags:
        if await safe_get(tag, 'attributes', 'role') == 'seller':
            seller_credit = {'level': await safe_get(tag, 'attributes', 'level'), 'text': tag.get('text')}
        elif await safe_get(tag, 'attributes', 'role') == 'buyer':
            buyer_credit = {'level': await safe_get(tag, 'attributes', 'level'), 'text': tag.get('text')}
    return {
        "卖家昵称": await safe_get(data, 'module', 'base', 'displayName'),
        "卖家头像链接": await safe_get(data, 'module', 'base', 'avatar', 'avatar'),
        "卖家个性签名": await safe_get(data, 'module', 'base', 'introduction', default=''),
        "卖家在售/已售商品数": await safe_get(data, 'module', 'tabs', 'item', 'number'),
        "卖家收到的评价总数": await safe_get(data, 'module', 'tabs', 'rate', 'number'),
        "卖家信用等级": seller_credit.get('text', '暂无'),
        "买家信用等级": buyer_credit.get('text', '暂无')
    }


async def parse_ratings_data(ratings_json: list) -> list:
    """解析评价列表API的JSON数据。"""
    parsed_list = []
    for card in ratings_json:
        data = await safe_get(card, 'cardData', default={})
        rate_tag = await safe_get(data, 'rateTagList', 0, 'text', default='未知角色')
        rate_type = await safe_get(data, 'rate')
        if rate_type == 1: rate_text = "好评"
        elif rate_type == 0: rate_text = "中评"
        elif rate_type == -1: rate_text = "差评"
        else: rate_text = "未知"
        parsed_list.append({
            "评价ID": data.get('rateId'),
            "评价内容": data.get('feedback'),
            "评价类型": rate_text,
            "评价来源角色": rate_tag,
            "评价者昵称": data.get('raterUserNick'),
            "评价时间": data.get('gmtCreate'),
            "评价图片": await safe_get(data, 'pictCdnUrlList', default=[])
        })
    return parsed_list

async def safe_get(data, *keys, default="暂无"):
    """安全获取嵌套字典值"""
    for key in keys:
        try:
            data = data[key]
        except (KeyError, TypeError, IndexError):
            return default
    return data

async def _parse_search_results_json(json_data: dict, source: str) -> list:
    """解析搜索API的JSON数据，返回基础商品信息列表。"""
    page_data = []
    try:
        items = await safe_get(json_data, "data", "resultList", default=[])
        if not items:
            print(f"LOG: ({source}) API响应中未找到商品列表 (resultList)。")
            return []

        for item in items:
            main_data = await safe_get(item, "data", "item", "main", "exContent", default={})
            click_params = await safe_get(item, "data", "item", "main", "clickParam", "args", default={})

            title = await safe_get(main_data, "title", default="未知标题")
            price_parts = await safe_get(main_data, "price", default=[])
            price = "".join([str(p.get("text", "")) for p in price_parts if isinstance(p, dict)]).replace("当前价", "").strip() if isinstance(price_parts, list) else "价格异常"
            if "万" in price: price = f"¥{float(price.replace('¥', '').replace('万', '')) * 10000:.0f}"
            area = await safe_get(main_data, "area", default="地区未知")
            seller = await safe_get(main_data, "userNickName", default="匿名卖家")
            raw_link = await safe_get(item, "data", "item", "main", "targetUrl", default="")
            image_url = await safe_get(main_data, "picUrl", default="")
            pub_time_ts = click_params.get("publishTime", "")
            item_id = await safe_get(main_data, "itemId", default="未知ID")
            original_price = await safe_get(main_data, "oriPrice", default="暂无")
            wants_count = await safe_get(click_params, "wantNum", default='NaN')


            tags = []
            if await safe_get(click_params, "tag") == "freeship":
                tags.append("包邮")
            r1_tags = await safe_get(main_data, "fishTags", "r1", "tagList", default=[])
            for tag_item in r1_tags:
                content = await safe_get(tag_item, "data", "content", default="")
                if "验货宝" in content:
                    tags.append("验货宝")

            page_data.append({
                "商品标题": title,
                "当前售价": price,
                "商品原价": original_price,
                "“想要”人数": wants_count,
                "商品标签": tags,
                "发货地区": area,
                "卖家昵称": seller,
                "商品链接": raw_link.replace("fleamarket://", "https://www.goofish.com/"),
                "发布时间": datetime.fromtimestamp(int(pub_time_ts)/1000).strftime("%Y-%m-%d %H:%M") if pub_time_ts.isdigit() else "未知时间",
                "商品ID": item_id
            })
        print(f"LOG: ({source}) 成功解析到 {len(page_data)} 条商品基础信息。")
        return page_data
    except Exception as e:
        print(f"LOG: ({source}) JSON数据处理异常: {str(e)}")
        return []

def format_registration_days(total_days: int) -> str:
    """
    将总天数格式化为“X年Y个月”的字符串。
    """
    if not isinstance(total_days, int) or total_days <= 0:
        return '未知'

    # 使用更精确的平均天数
    DAYS_IN_YEAR = 365.25
    DAYS_IN_MONTH = DAYS_IN_YEAR / 12  # 大约 30.44

    # 计算年数
    years = math.floor(total_days / DAYS_IN_YEAR)

    # 计算剩余天数
    remaining_days = total_days - (years * DAYS_IN_YEAR)

    # 计算月数，四舍五入
    months = round(remaining_days / DAYS_IN_MONTH)

    # 处理进位：如果月数等于12，则年数加1，月数归零
    if months == 12:
        years += 1
        months = 0

    # 构建最终的输出字符串
    if years > 0 and months > 0:
        return f"来闲鱼{years}年{months}个月"
    elif years > 0 and months == 0:
        return f"来闲鱼{years}年整"
    elif years == 0 and months > 0:
        return f"来闲鱼{months}个月"
    else: # years == 0 and months == 0
        return "来闲鱼不足一个月"


# --- AI分析及通知辅助函数 (从 ai_filter.py 移植并异步化改造) ---

def retry_on_failure(retries=3, delay=5):
    """
    一个通用的异步重试装饰器，增加了对HTTP错误的详细日志记录。
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (APIStatusError, HTTPError) as e:
                    print(f"函数 {func.__name__} 第 {i + 1}/{retries} 次尝试失败，发生HTTP错误。")
                    if hasattr(e, 'status_code'):
                        print(f"  - 状态码 (Status Code): {e.status_code}")
                    if hasattr(e, 'response') and hasattr(e.response, 'text'):
                        response_text = e.response.text
                        print(
                            f"  - 返回值 (Response): {response_text[:300]}{'...' if len(response_text) > 300 else ''}")
                except json.JSONDecodeError as e:
                    print(f"函数 {func.__name__} 第 {i + 1}/{retries} 次尝试失败: JSON解析错误 - {e}")
                except Exception as e:
                    print(f"函数 {func.__name__} 第 {i + 1}/{retries} 次尝试失败: {type(e).__name__} - {e}")

                if i < retries - 1:
                    print(f"将在 {delay} 秒后重试...")
                    await asyncio.sleep(delay)

            print(f"函数 {func.__name__} 在 {retries} 次尝试后彻底失败。")
            return None
        return wrapper
    return decorator


@retry_on_failure(retries=2, delay=3)
async def _download_single_image(url, save_path):
    """一个带重试的内部函数，用于异步下载单个图片。"""
    loop = asyncio.get_running_loop()
    # 使用 run_in_executor 运行同步的 requests 代码，避免阻塞事件循环
    response = await loop.run_in_executor(
        None,
        lambda: requests.get(url, headers=IMAGE_DOWNLOAD_HEADERS, timeout=20, stream=True)
    )
    response.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path


async def download_all_images(product_id, image_urls):
    """异步下载一个商品的所有图片。如果图片已存在则跳过。"""
    if not image_urls:
        return []

    urls = [url.strip() for url in image_urls if url.strip().startswith('http')]
    if not urls:
        return []

    saved_paths = []
    total_images = len(urls)
    for i, url in enumerate(urls):
        try:
            clean_url = url.split('.heic')[0] if '.heic' in url else url
            file_name_base = os.path.basename(clean_url).split('?')[0]
            file_name = f"product_{product_id}_{i + 1}_{file_name_base}"
            file_name = re.sub(r'[\\/*?:"<>|]', "", file_name)
            if not os.path.splitext(file_name)[1]:
                file_name += ".jpg"

            save_path = os.path.join(IMAGE_SAVE_DIR, file_name)

            if os.path.exists(save_path):
                print(f"   [图片] 图片 {i + 1}/{total_images} 已存在，跳过下载: {os.path.basename(save_path)}")
                saved_paths.append(save_path)
                continue

            print(f"   [图片] 正在下载图片 {i + 1}/{total_images}: {url}")
            if await _download_single_image(url, save_path):
                print(f"   [图片] 图片 {i + 1}/{total_images} 已成功下载到: {os.path.basename(save_path)}")
                saved_paths.append(save_path)
        except Exception as e:
            print(f"   [图片] 处理图片 {url} 时发生错误，已跳过此图: {e}")

    return saved_paths


def encode_image_to_base64(image_path):
    """将本地图片文件编码为 Base64 字符串。"""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"编码图片时出错: {e}")
        return None


@retry_on_failure(retries=3, delay=5)
async def send_ntfy_notification(product_data, reason):
    """当发现推荐商品时，异步发送一个高优先级的 ntfy.sh 通知。"""
    if not NTFY_TOPIC_URL:
        print("警告：未在 .env 文件中配置 NTFY_TOPIC_URL，跳过通知。")
        return
    if not WX_BOT_URL:
        print("警告：未在 .env 文件中配置 WX_BOT_URL，跳过通知。")
        return
    title = product_data.get('商品标题', 'N/A')
    price = product_data.get('当前售价', 'N/A')
    link = product_data.get('商品链接', '#')
    if PCURL_TO_MOBILE:
        mobile_link = convert_goofish_link(link)
        message = f"价格: {price}\n原因: {reason}\n手机端链接: {mobile_link}\n电脑端链接: {link}"
    else:
        message = f"价格: {price}\n原因: {reason}\n链接: {link}"

    notification_title = f"🚨 新推荐! {title[:30]}..."

    try:
        print(f"   -> 正在发送 ntfy 通知到: {NTFY_TOPIC_URL}")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: requests.post(
                NTFY_TOPIC_URL,
                data=message.encode('utf-8'),
                headers={
                    "Title": notification_title.encode('utf-8'),
                    "Priority": "urgent",
                    "Tags": "bell,vibration"
                },
                timeout=10
            )
        )
        print("   -> 通知发送成功。")
    except Exception as e:
        print(f"   -> 发送 ntfy 通知失败: {e}")
        raise

    # 企业微信文本消息的 payload 格式
    payload = {
        "msgtype": "text",
        "text": {
            "content": f"{notification_title}\n{message}"
        }
    }

    try:
        print(f"   -> 正在发送企业微信通知到: {WX_BOT_URL}")
        # 设置正确的 Content-Type 为 application/json
        headers = {
            "Content-Type": "application/json"
        }
        # 使用 json 参数直接发送字典，requests 会自动处理编码和 Content-Type
        response = requests.post(
            WX_BOT_URL,
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()  # 检查HTTP状态码是否为错误 (如4xx或5xx)
        result = response.json()
        print(f"   -> 通知发送成功。响应: {result}")
    except requests.exceptions.RequestException as e:
        print(f"   -> 发送企业微信通知失败: {e}")
        raise  # 重新抛出异常，以便上层可以捕获
    except Exception as e:
        print(f"   -> 发送企业微信通知时发生未知错误: {e}")
        raise

@retry_on_failure(retries=5, delay=10)
async def get_ai_analysis(product_data, image_paths=None, prompt_text=""):
    """将完整的商品JSON数据和所有图片发送给 AI 进行分析（异步）。"""
    item_info = product_data.get('商品信息', {})
    product_id = item_info.get('商品ID', 'N/A')

    print(f"\n   [AI分析] 开始分析商品 #{product_id} (含 {len(image_paths or [])} 张图片)...")
    print(f"   [AI分析] 标题: {item_info.get('商品标题', '无')}")

    if not prompt_text:
        print("   [AI分析] 错误：未提供AI分析所需的prompt文本。")
        return None

    product_details_json = json.dumps(product_data, ensure_ascii=False, indent=2)
    system_prompt = prompt_text

    combined_text_prompt = f"""{system_prompt}

请基于你的专业知识和我的要求，分析以下完整的商品JSON数据：

```json
    {product_details_json}
"""
    user_content_list = [{"type": "text", "text": combined_text_prompt}]

    if image_paths:
        for path in image_paths:
            base64_image = encode_image_to_base64(path)
            if base64_image:
                user_content_list.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

    messages = [{"role": "user", "content": user_content_list}]

    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        response_format={"type": "json_object"}
    )

    ai_response_content = response.choices[0].message.content

    try:
        return json.loads(ai_response_content)
    except json.JSONDecodeError as e:
        print("---!!! AI RESPONSE PARSING FAILED (JSONDecodeError) !!!---")
        print(f"原始返回值 (Raw response from AI):\n---\n{ai_response_content}\n---")
        raise e


async def scrape_xianyu(task_config: dict, debug_limit: int = 0):
    """
    【核心执行器】
    根据单个任务配置，异步爬取闲鱼商品数据，并对每个新发现的商品进行实时的、独立的AI分析和通知。
    """
    keyword = task_config['keyword']
    max_pages = task_config.get('max_pages', 1)
    personal_only = task_config.get('personal_only', False)
    min_price = task_config.get('min_price')
    max_price = task_config.get('max_price')
    ai_prompt_text = task_config.get('ai_prompt_text', '')

    processed_item_count = 0
    stop_scraping = False

    processed_links = set()
    output_filename = f"{keyword.replace(' ', '_')}_full_data.jsonl"
    if os.path.exists(output_filename):
        print(f"LOG: 发现已存在文件 {output_filename}，正在加载历史记录以去重...")
        try:
            with open(output_filename, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        link = record.get('商品信息', {}).get('商品链接', '')
                        if link:
                            processed_links.add(get_link_unique_key(link))
                    except json.JSONDecodeError:
                        print(f"   [警告] 文件中有一行无法解析为JSON，已跳过。")
            print(f"LOG: 加载完成，已记录 {len(processed_links)} 个已处理过的商品。")
        except IOError as e:
            print(f"   [警告] 读取历史文件时发生错误: {e}")
    else:
        print(f"LOG: 输出文件 {output_filename} 不存在，将创建新文件。")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=RUN_HEADLESS)
        context = await browser.new_context(storage_state=STATE_FILE, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3")
        page = await context.new_page()

        try:
            print("LOG: 步骤 1 - 直接导航到搜索结果页...")
            # 使用 'q' 参数构建正确的搜索URL，并进行URL编码
            params = {'q': keyword}
            search_url = f"https://www.goofish.com/search?{urlencode(params)}"
            print(f"   -> 目标URL: {search_url}")

            # 使用 expect_response 在导航的同时捕获初始搜索的API数据
            async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=30000) as response_info:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

            initial_response = await response_info.value

            # 等待页面加载出关键筛选元素，以确认已成功进入搜索结果页
            await page.wait_for_selector('text=新发布', timeout=15000)

            # --- 新增：检查是否存在验证弹窗 ---
            baxia_dialog = page.locator("div.baxia-dialog-mask")
            if await baxia_dialog.is_visible(timeout=2000): # 短暂等待检查
                print("\n==================== CRITICAL BLOCK DETECTED ====================")
                print("检测到闲鱼反爬虫验证弹窗 (baxia-dialog)，无法继续操作。")
                print("这通常是因为操作过于频繁或被识别为机器人。")
                print("建议：")
                print("1. 停止脚本一段时间再试。")
                print("2. (推荐) 在 .env 文件中设置 RUN_HEADLESS=false，以非无头模式运行，这有助于绕过检测。")
                print(f"任务 '{keyword}' 将在此处中止。")
                print("===================================================================")
                await browser.close()
                return processed_item_count
            # --- 结束新增 ---

            try:
                await page.click("div[class*='closeIconBg']", timeout=3000)
                print("LOG: 已关闭广告弹窗。")
            except PlaywrightTimeoutError:
                print("LOG: 未检测到广告弹窗。")

            final_response = None
            print("\nLOG: 步骤 2 - 应用筛选条件...")
            await page.click('text=新发布')
            await random_sleep(2, 4) # 原来是 (1.5, 2.5)
            async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                await page.click('text=最新')
                # --- 修改: 增加排序后的等待时间 ---
                await random_sleep(4, 7) # 原来是 (3, 5)
            final_response = await response_info.value

            if personal_only:
                async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                    await page.click('text=个人闲置')
                    # --- 修改: 将固定等待改为随机等待，并加长 ---
                    await random_sleep(4, 6) # 原来是 asyncio.sleep(5)
                final_response = await response_info.value

            if min_price or max_price:
                price_container = page.locator('div[class*="search-price-input-container"]').first
                if await price_container.is_visible():
                    if min_price:
                        await price_container.get_by_placeholder("¥").first.fill(min_price)
                        # --- 修改: 将固定等待改为随机等待 ---
                        await random_sleep(1, 2.5) # 原来是 asyncio.sleep(5)
                    if max_price:
                        await price_container.get_by_placeholder("¥").nth(1).fill(max_price)
                        # --- 修改: 将固定等待改为随机等待 ---
                        await random_sleep(1, 2.5) # 原来是 asyncio.sleep(5)

                    async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                        await page.keyboard.press('Tab')
                        # --- 修改: 增加确认价格后的等待时间 ---
                        await random_sleep(4, 7) # 原来是 asyncio.sleep(5)
                    final_response = await response_info.value
                else:
                    print("LOG: 警告 - 未找到价格输入容器。")

            print("\nLOG: 所有筛选已完成，开始处理商品列表...")

            current_response = final_response if final_response and final_response.ok else initial_response
            for page_num in range(1, max_pages + 1):
                if stop_scraping: break
                print(f"\n--- 正在处理第 {page_num}/{max_pages} 页 ---")

                if page_num > 1:
                    next_btn = page.locator("[class*='search-pagination-arrow-right']:not([disabled])")
                    if not await next_btn.count():
                        print("LOG: 未找到可用的“下一页”按钮，停止翻页。")
                        break
                    try:
                        async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                            await next_btn.click()
                            # --- 修改: 增加翻页后的等待时间 ---
                            await random_sleep(5, 8) # 原来是 (1.5, 3.5)
                        current_response = await response_info.value
                    except PlaywrightTimeoutError:
                        print(f"LOG: 翻页到第 {page_num} 页超时。")
                        break

                if not (current_response and current_response.ok):
                    print(f"LOG: 第 {page_num} 页响应无效，跳过。")
                    continue

                basic_items = await _parse_search_results_json(await current_response.json(), f"第 {page_num} 页")
                if not basic_items: break

                total_items_on_page = len(basic_items)
                for i, item_data in enumerate(basic_items, 1):
                    if debug_limit > 0 and processed_item_count >= debug_limit:
                        print(f"LOG: 已达到调试上限 ({debug_limit})，停止获取新商品。")
                        stop_scraping = True
                        break

                    unique_key = get_link_unique_key(item_data["商品链接"])
                    if unique_key in processed_links:
                        print(f"   -> [页内进度 {i}/{total_items_on_page}] 商品 '{item_data['商品标题'][:20]}...' 已存在，跳过。")
                        continue

                    print(f"-> [页内进度 {i}/{total_items_on_page}] 发现新商品，获取详情: {item_data['商品标题'][:30]}...")
                    # --- 修改: 访问详情页前的等待时间，模拟用户在列表页上看了一会儿 ---
                    await random_sleep(3, 6) # 原来是 (2, 4)

                    detail_page = await context.new_page()
                    try:
                        async with detail_page.expect_response(lambda r: DETAIL_API_URL_PATTERN in r.url, timeout=25000) as detail_info:
                            await detail_page.goto(item_data["商品链接"], wait_until="domcontentloaded", timeout=25000)

                        detail_response = await detail_info.value
                        if detail_response.ok:
                            detail_json = await detail_response.json()

                            ret_string = str(await safe_get(detail_json, 'ret', default=[]))
                            if "FAIL_SYS_USER_VALIDATE" in ret_string:
                                print("\n==================== CRITICAL BLOCK DETECTED ====================")
                                print("检测到闲鱼反爬虫验证 (FAIL_SYS_USER_VALIDATE)，程序将终止。")
                                long_sleep_duration = random.randint(300, 600)
                                print(f"为避免账户风险，将执行一次长时间休眠 ({long_sleep_duration} 秒) 后再退出...")
                                await asyncio.sleep(long_sleep_duration)
                                print("长时间休眠结束，现在将安全退出。")
                                print("===================================================================")
                                stop_scraping = True
                                break

                            # 解析商品详情数据并更新 item_data
                            item_do = await safe_get(detail_json, 'data', 'itemDO', default={})
                            seller_do = await safe_get(detail_json, 'data', 'sellerDO', default={})

                            reg_days_raw = await safe_get(seller_do, 'userRegDay', default=0)
                            registration_duration_text = format_registration_days(reg_days_raw)

                            # --- START: 新增代码块 ---

                            # 1. 提取卖家的芝麻信用信息
                            zhima_credit_text = await safe_get(seller_do, 'zhimaLevelInfo', 'levelName')

                            # 2. 提取该商品的完整图片列表
                            image_infos = await safe_get(item_do, 'imageInfos', default=[])
                            if image_infos:
                                # 使用列表推导式获取所有有效的图片URL
                                all_image_urls = [img.get('url') for img in image_infos if img.get('url')]
                                if all_image_urls:
                                    # 用新的字段存储图片列表，替换掉旧的单个链接
                                    item_data['商品图片列表'] = all_image_urls
                                    # (可选) 仍然保留主图链接，以防万一
                                    item_data['商品主图链接'] = all_image_urls[0]

                            # --- END: 新增代码块 ---
                            item_data['“想要”人数'] = await safe_get(item_do, 'wantCnt', default=item_data.get('“想要”人数', 'NaN'))
                            item_data['浏览量'] = await safe_get(item_do, 'browseCnt', default='-')
                            # ...[此处可添加更多从详情页解析出的商品信息]...

                            # 调用核心函数采集卖家信息
                            user_profile_data = {}
                            user_id = await safe_get(seller_do, 'sellerId')
                            if user_id:
                                # 新的、高效的调用方式:
                                user_profile_data = await scrape_user_profile(context, str(user_id))
                            else:
                                print("   [警告] 未能从详情API中获取到卖家ID。")
                            user_profile_data['卖家芝麻信用'] = zhima_credit_text
                            user_profile_data['卖家注册时长'] = registration_duration_text

                            # 构建基础记录
                            final_record = {
                                "爬取时间": datetime.now().isoformat(),
                                "搜索关键字": keyword,
                                "任务名称": task_config.get('task_name', 'Untitled Task'),
                                "商品信息": item_data,
                                "卖家信息": user_profile_data
                            }

                            # --- START: Real-time AI Analysis & Notification ---
                            print(f"   -> 开始对商品 #{item_data['商品ID']} 进行实时AI分析...")
                            # 1. Download images
                            image_urls = item_data.get('商品图片列表', [])
                            downloaded_image_paths = await download_all_images(item_data['商品ID'], image_urls)

                            # 2. Get AI analysis
                            ai_analysis_result = None
                            if ai_prompt_text:
                                try:
                                    # 注意：这里我们将整个记录传给AI，让它拥有最全的上下文
                                    ai_analysis_result = await get_ai_analysis(final_record, downloaded_image_paths, prompt_text=ai_prompt_text)
                                    if ai_analysis_result:
                                        final_record['ai_analysis'] = ai_analysis_result
                                        print(f"   -> AI分析完成。推荐状态: {ai_analysis_result.get('is_recommended')}")
                                    else:
                                        final_record['ai_analysis'] = {'error': 'AI analysis returned None after retries.'}
                                except Exception as e:
                                    print(f"   -> AI分析过程中发生严重错误: {e}")
                                    final_record['ai_analysis'] = {'error': str(e)}
                            else:
                                print("   -> 任务未配置AI prompt，跳过分析。")

                            # 3. Send notification if recommended
                            if ai_analysis_result and ai_analysis_result.get('is_recommended'):
                                print(f"   -> 商品被AI推荐，准备发送通知...")
                                await send_ntfy_notification(item_data, ai_analysis_result.get("reason", "无"))
                            # --- END: Real-time AI Analysis & Notification ---

                            # 4. 保存包含AI结果的完整记录
                            await save_to_jsonl(final_record, keyword)

                            processed_links.add(unique_key)
                            processed_item_count += 1
                            print(f"   -> 商品处理流程完毕。累计处理 {processed_item_count} 个新商品。")

                            # --- 修改: 增加单个商品处理后的主要延迟 ---
                            print("   [反爬] 执行一次主要的随机延迟以模拟用户浏览间隔...")
                            await random_sleep(15, 30) # 原来是 (8, 15)，这是最重要的修改之一

                    except PlaywrightTimeoutError:
                        print(f"   错误: 访问商品详情页或等待API响应超时。")
                    except Exception as e:
                        print(f"   错误: 处理商品详情时发生未知错误: {e}")
                    finally:
                        await detail_page.close()
                        # --- 修改: 增加关闭页面后的短暂整理时间 ---
                        await random_sleep(2, 4) # 原来是 (1, 2.5)

                # --- 新增: 在处理完一页所有商品后，翻页前，增加一个更长的“休息”时间 ---
                if not stop_scraping and page_num < max_pages:
                    print(f"--- 第 {page_num} 页处理完毕，准备翻页。执行一次页面间的长时休息... ---")
                    await random_sleep(25, 50)

        except PlaywrightTimeoutError as e:
            print(f"\n操作超时错误: 页面元素或网络响应未在规定时间内出现。\n{e}")
        except Exception as e:
            print(f"\n爬取过程中发生未知错误: {e}")
        finally:
            print("\nLOG: 任务执行完毕，浏览器将在5秒后自动关闭...")
            await asyncio.sleep(5)
            if debug_limit:
                input("按回车键关闭浏览器...")
            await browser.close()

    return processed_item_count

async def main():
    parser = argparse.ArgumentParser(
        description="闲鱼商品监控脚本，支持多任务配置和实时AI分析。",
        epilog="""
使用示例:
  # 运行 config.json 中定义的所有任务
  python spider_v2.py

  # 调试模式: 运行所有任务，但每个任务只处理前3个新发现的商品
  python spider_v2.py --debug-limit 3
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--debug-limit", type=int, default=0, help="调试模式：每个任务仅处理前 N 个新商品（0 表示无限制）")
    parser.add_argument("--config", type=str, default="config.json", help="指定任务配置文件路径（默认为 config.json）")
    args = parser.parse_args()

    if not os.path.exists(STATE_FILE):
        sys.exit(f"错误: 登录状态文件 '{STATE_FILE}' 不存在。请先运行 login.py 生成。")

    if not os.path.exists(args.config):
        sys.exit(f"错误: 配置文件 '{args.config}' 不存在。")

    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            tasks_config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        sys.exit(f"错误: 读取或解析配置文件 '{args.config}' 失败: {e}")

    # 读取所有prompt文件内容
    for task in tasks_config:
        if task.get("enabled", False) and task.get("ai_prompt_base_file") and task.get("ai_prompt_criteria_file"):
            try:
                with open(task["ai_prompt_base_file"], 'r', encoding='utf-8') as f_base:
                    base_prompt = f_base.read()
                with open(task["ai_prompt_criteria_file"], 'r', encoding='utf-8') as f_criteria:
                    criteria_text = f_criteria.read()

                # 动态组合成最终的Prompt
                task['ai_prompt_text'] = base_prompt.replace("{{CRITERIA_SECTION}}", criteria_text)

            except FileNotFoundError as e:
                print(f"警告: 任务 '{task['task_name']}' 的prompt文件缺失: {e}，该任务的AI分析将被跳过。")
                task['ai_prompt_text'] = ""
        elif task.get("enabled", False) and task.get("ai_prompt_file"):
            try:
                with open(task["ai_prompt_file"], 'r', encoding='utf-8') as f:
                    task['ai_prompt_text'] = f.read()
            except FileNotFoundError:
                print(f"警告: 任务 '{task['task_name']}' 的prompt文件 '{task['ai_prompt_file']}' 未找到，该任务的AI分析将被跳过。")
                task['ai_prompt_text'] = ""

    print("\n--- 开始执行监控任务 ---")
    if args.debug_limit > 0:
        print(f"** 调试模式已激活，每个任务最多处理 {args.debug_limit} 个新商品 **")
    print("--------------------")

    active_task_configs = [task for task in tasks_config if task.get("enabled", False)]
    if not active_task_configs:
        print("配置文件中没有启用的任务，程序退出。")
        return

    # 为每个启用的任务创建一个异步执行协程
    coroutines = []
    for task_conf in active_task_configs:
        print(f"-> 任务 '{task_conf['task_name']}' 已加入执行队列。")
        coroutines.append(scrape_xianyu(task_config=task_conf, debug_limit=args.debug_limit))

    # 并发执行所有任务
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    print("\n--- 所有任务执行完毕 ---")
    for i, result in enumerate(results):
        task_name = active_task_configs[i]['task_name']
        if isinstance(result, Exception):
            print(f"任务 '{task_name}' 因异常而终止: {result}")
        else:
            print(f"任务 '{task_name}' 正常结束，本次运行共处理了 {result} 个新商品。")

if __name__ == "__main__":
    asyncio.run(main())
