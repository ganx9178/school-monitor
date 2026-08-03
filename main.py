"""
奕阳教育 - 客户资料数据库机器人 (Cloud 版)
功能：用户在飞书群里@机器人+学校名，机器人返回该学校的完整资料+商业洞察

特性：
1. 支持任意学校查询（不依赖本地清单）
2. 智能模糊匹配（自动处理省市前缀缺失）
3. AI 商业洞察（采购潜力评估、核心诉求推测、推荐切入点）
4. 24/7 在线（设计用于云平台部署）

部署方式：
  推荐 Railway / Render / Cloudflare Workers
  详见 README.md
"""
import os
import json
import hashlib
import hmac
import base64
import time
import re
import urllib.request
import urllib.parse
from typing import List, Dict, Optional
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

# ===== 配置 =====
APP_ID = os.getenv("APP_ID", "")
APP_SECRET = os.getenv("APP_SECRET", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
ENCRYPT_KEY = os.getenv("ENCRYPT_KEY", "")
BOT_NAME = os.getenv("BOT_NAME", "客户资料数据库")

app = FastAPI(title="Sunglory School Bot")

# ===== 飞书 API =====

def get_tenant_token() -> str:
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read().decode())
    if result.get("code") == 0:
        return result["tenant_access_token"]
    raise Exception(f"Token 获取失败: {result}")


def send_message(chat_id: str, text: str, token: str = None):
    """发送消息到群聊"""
    if not token:
        token = get_tenant_token()
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    content_json = json.dumps({"text": text}, ensure_ascii=False)
    data = json.dumps({
        "receive_id": chat_id,
        "msg_type": "text",
        "content": content_json
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.read().decode()
    except Exception as e:
        print(f"[发送失败] {e}")
        return None


def send_typing(chat_id: str, token: str = None):
    """发送输入中状态"""
    if not token:
        token = get_tenant_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages/read"
    # 飞书没有专门的 typing 接口，通常直接发"正在查询..."消息
    pass


# ===== 搜索引擎 =====

class SearchResult:
    def __init__(self, title: str, url: str, desc: str, source: str):
        self.title = title
        self.url = url
        self.desc = desc
        self.source = source

def generate_variants(name: str) -> List[str]:
    """生成名称变体用于模糊搜索"""
    variants = [name]
    prefixes = [
        "杭州市", "宁波市", "丽水市", "台州市", "温州市", "嘉兴市", "湖州市", 
        "绍兴市", "金华市", "衢州市", "舟山市", "浙江省"
    ]
    areas = [
        "滨江区", "西湖区", "拱墅区", "上城区", "临平区", "钱塘区", "萧山区", 
        "余杭区", "富阳区", "鄞州区", "海曙区", "江北区", "北仑区", "镇海区", 
        "奉化区", "象山县", "宁海县", "慈溪市", "余姚市"
    ]
    
    for p in prefixes + areas:
        if name.startswith(p):
            short = name[len(p):].strip()
            if short and short not in variants:
                variants.append(short)
    
    # 尝试补全（如果名字很短）
    if len(name) < 6:
        for p in prefixes:
            full = p + name
            if full not in variants:
                variants.append(full)
    
    return variants[:6]

def search_web(query: str) -> List[SearchResult]:
    """执行网络搜索（百度）"""
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.baidu.com/s?wd={encoded}&rn=10"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", errors="ignore")
        
        # 解析结果
        h3_pat = re.compile(r'<h3[^>]*class="[^"]*t[^"]*"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
        abs_pat = re.compile(r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
        
        titles = h3_pat.findall(html)
        abstracts = abs_pat.findall(html)
        
        for i, (href, title_html) in enumerate(titles[:8]):
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if len(title) < 4 or "百度" in title: continue
            
            desc = ""
            if i < len(abstracts):
                desc = re.sub(r'<[^>]+>', '', abstracts[i]).strip()
            
            results.append(SearchResult(title=title[:80], url=href, desc=desc[:120], source="Baidu"))
            
    except Exception as e:
        print(f"[搜索错误] {query}: {e}")
    
    return results

def search_school_info(school_name: str) -> Dict:
    """
    核心搜索逻辑：返回结构化数据 + AI 分析
    """
    variants = generate_variants(school_name)
    all_results = []
    
    # 构建查询
    queries = []
    for v in variants:
        queries.extend([
            f"{v} 校长 副校长",
            f"{v} 学校特色",
            f"{v} 机器人 竞赛",
            f"{v} 科技 课程",
            f"{v} 采购 招标",
            f"{v} 人工智能 教育",
        ])
    
    # 执行搜索
    seen_urls = set()
    for q in queries:
        items = search_web(q)
        for item in items:
            if item.url not in seen_urls:
                seen_urls.add(item.url)
                all_results.append({"title": item.title, "url": item.url, "desc": item.desc, "query": q})
        time.sleep(0.3)
    
    # 分类
    leaders = []
    features = []
    tech = []
    bids = []
    
    for item in all_results:
        text = (item["title"] + " " + item["desc"]).lower()
        if any(k in text for k in ["校长", "副校长", "书记", "领导", "任命"]):
            leaders.append(item)
        elif any(k in text for k in ["招标", "采购", "中标", "意向"]):
            bids.append(item)
        elif any(k in text for k in ["机器人", "竞赛", "编程", "创客", "获奖"]):
            tech.append(item)
        elif any(k in text for k in ["特色", "科技", "stem", "人工智能"]):
            features.append(item)
    
    # 生成 AI 分析
    analysis = generate_ai_analysis(school_name, leaders, features, tech, bids)
    
    return {
        "name": school_name,
        "leaders": leaders[:5],
        "features": features[:5],
        "tech": tech[:5],
        "bids": bids[:5],
        "analysis": analysis,
        "total": len(all_results)
    }

def generate_ai_analysis(name: str, leaders: list, features: list, tech: list, bids: list) -> str:
    """生成商业洞察"""
    lines = []
    
    # 潜力评估
    score = 0
    if bids: score += 2
    if tech: score += 1
    if features: score += 1
    
    level = "🔴 高潜力" if score >= 3 else "🟡 中潜力" if score >= 1 else "⚪ 低潜力"
    lines.append(f"📊 **采购潜力**: {level}")
    
    # 诉求推测
    focus = []
    if bids: focus.append("硬件更新/信息化建设")
    if tech: focus.append("科技竞赛/社团活动")
    if features: focus.append("特色课程/品牌打造")
    focus_str = "、".join(focus) if focus else "暂无明确倾向"
    lines.append(f"🎯 **核心诉求**: {focus_str}")
    
    # 推荐切入点
    rec = "建议先以‘免费科技讲座’或‘师资培训’切入，建立联系后再推器材。"
    if bids:
        rec = "该校近期有采购动作，建议直接携带‘招标参数对照表’拜访，重点推匹配产品。"
    elif tech:
        rec = "该校重视竞赛成绩，可推荐‘竞赛级器材套装’及‘赛前集训方案’。"
    lines.append(f"💡 **推荐切入点**: {rec}")
    
    # 综合评价
    summary = f"该校为{name}。"
    if leaders:
        summary += "领导班子稳定。"
    if tech:
        summary += "科技活动活跃，学生参与度高。"
    if not any([leaders, features, tech, bids]):
        summary = "公开信息较少，建议通过教育局或同行了解内幕。"
    lines.append(f"📝 **综合评价**: {summary}")
    
    return "\n".join(lines)

def format_report(data: Dict) -> str:
    """格式化最终回复"""
    lines = []
    lines.append(f"🏫 **{data['name']}** 资料查询")
    lines.append("=" * 30)
    
    # 领导
    if data["leaders"]:
        lines.append("👤 **现任领导**")
        for x in data["leaders"]:
            lines.append(f"• {x['title']}")
    else:
        lines.append("👤 **现任领导**: 未检索到")
    
    lines.append("")
    
    # 特色
    if data["features"]:
        lines.append(" **学校特色**")
        for x in data["features"]:
            lines.append(f"• {x['title']}")
    else:
        lines.append("🌟 **学校特色**: 未检索到")
    
    lines.append("")
    
    # 科技
    if data["tech"]:
        lines.append("🏆 **科技成绩**")
        for x in data["tech"]:
            lines.append(f"• {x['title']}")
    else:
        lines.append("🏆 **科技成绩**: 未检索到")
    
    lines.append("")
    
    # 招标
    if data["bids"]:
        lines.append("💰 **近期招标**")
        for x in data["bids"]:
            lines.append(f"• {x['title']}")
    else:
        lines.append(" **近期招标**: 无公开记录")
    
    lines.append("")
    lines.append("---")
    lines.append("🤖 **AI 商业洞察**")
    lines.append(data["analysis"])
    
    return "\n".join(lines)


# ===== 路由 =====

@app.get("/")
def root():
    return {"msg": "Sunglory School Bot is running."}

@app.post("/webhook")
async def handle_event(request: Request):
    """处理飞书事件（包含 URL 验证）"""
    try:
        body = await request.json()
        
        # 处理飞书 URL 验证请求
        if "challenge" in body:
            print(f"[验证] 收到 challenge: {body['challenge']}")
            return {"challenge": body["challenge"]}
        
        # 处理正常事件
        event = body.get("event", {})
        msg = event.get("message", {})
        chat_id = msg.get("chat_id")
        msg_id = msg.get("message_id")
        content = json.loads(msg.get("content", "{}"))
        text = content.get("text", "")
        
        # 检查@
        mentions = msg.get("mentions", [])
        is_mention = False
        school_name = text
        
        for m in mentions:
            if m.get("name") == BOT_NAME or "客户资料" in m.get("name", ""):
                is_mention = True
                # 去掉@标记
                school_name = text.replace(m.get("key", ""), "").strip()
                break
        
        if not is_mention:
            return {"code": 0}
        
        if not school_name or len(school_name) < 2:
            send_message(chat_id, f"请输入学校名称，例如：@{BOT_NAME} 浦沿小学")
            return {"code": 0}
        
        # 搜索并回复
        send_message(chat_id, f"正在查询 [{school_name}]，请稍候...")
        data = search_school_info(school_name)
        report = format_report(data)
        send_message(chat_id, report)
        
        return {"code": 0}
        
    except Exception as e:
        print(f"[Error] {e}")
        return {"code": 1}
