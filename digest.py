#!/usr/bin/env python3
"""AI+医疗每日资讯摘要生成器"""

import feedparser
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
import html
import re
import sys
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

BJT = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

SOURCES = [
    # 英文源
    {"name": "ArXiv AI",        "feed": "https://rss.arxiv.org/rss/cs.AI",            "lang": "en"},
    {"name": "ArXiv ML",        "feed": "https://rss.arxiv.org/rss/cs.LG",            "lang": "en"},
    {"name": "ArXiv Bio",       "feed": "https://rss.arxiv.org/rss/q-bio.QM",         "lang": "en"},
    {"name": "MIT Tech Review", "feed": "https://www.technologyreview.com/tag/artificial-intelligence/feed/", "lang": "en"},
    {"name": "TechCrunch AI",   "feed": "https://techcrunch.com/category/artificial-intelligence/feed/", "lang": "en"},
    # 中文源
    {"name": "Google News - AI医疗",  "feed": "https://news.google.com/rss/search?q=AI+%E5%8C%BB%E7%96%97&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "lang": "zh"},
    {"name": "Google News - 人工智能医疗", "feed": "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+%E5%8C%BB%E7%96%97&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "lang": "zh"},
]

PUBMED_QUERY = (
    "((artificial intelligence) OR (machine learning) OR (deep learning)) "
    "AND (healthcare OR medical OR clinical OR drug OR diagnosis)"
)

RELEVANCE_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning",
    "large language model", "foundation model", "transformer",
    "neural network", "computer vision", "nlp",
    "medical", "healthcare", "clinical", "drug", "diagnos",
    "patient", "hospital", "biomedical", "genomics", "protein",
    "imaging", "pathology", "surgery", "therapy", "treatment",
    "biotech", "pharma", "cell", "gene", "molecular",
    "radiology", "oncology", "cardiology", "neurology",
    "fda", "clinical trial", "digital health",
    "precision medicine", "drug discovery",
    "health record", "medical image", "medical device",
    "diagnostic", "therapeutic", "biomarker",
    "medical ai", "health ai",
    "人工智能", "深度学习", "机器学习", "大模型", "大语言模型",
    "医疗", "医学", "健康", "临床", "药物", "诊断",
    "影像", "基因", "蛋白", "细胞", "病理",
    "手术", "治疗", "生物", "制药", "医院",
    "数字健康", "精准医疗", "医疗AI", "智慧医疗",
    "临床试验", "医疗器械", "生物技术",
]

# 英文分类名 → 中文翻译
CATEGORY_ZH = {
    "AI Models & LLM":                "AI模型与大语言模型",
    "Drug Discovery & Development":   "药物发现与开发",
    "Medical Imaging & Diagnosis":    "医学影像与诊断",
    "Genomics & Biotechnology":       "基因组学与生物技术",
    "Clinical Applications":          "临床应用",
    "Digital Health":                 "数字健康",
    "Industry & Policy":              "产业与政策",
    "Other":                          "其他",
}

CATEGORY_ORDER = [
    "AI Models & LLM", "Drug Discovery & Development", "Medical Imaging & Diagnosis",
    "Genomics & Biotechnology", "Clinical Applications", "Digital Health",
    "Industry & Policy", "Other",
]


def is_relevant(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(kw.lower() in text for kw in RELEVANCE_KEYWORDS)


def fetch_rss(source: dict) -> list:
    items = []
    try:
        resp = requests.get(source["feed"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:30]:
            title = html.unescape(entry.get("title", "")).strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            summary = html.unescape(entry.get("summary", entry.get("description", ""))).strip()
            summary = re.sub(r"<[^>]+>", "", summary)
            # 提取 arXiv 论文摘要
            if "arxiv.org" in link:
                m = re.search(r"Abstract:\s*(.*?)(?:\n\S|\Z)", summary, re.DOTALL)
                if m:
                    summary = m.group(1).strip()
            items.append({
                "title": title,
                "link": link,
                "summary": summary[:600],
                "source": source["name"],
                "lang": source["lang"],
            })
    except Exception as e:
        print(f"  [跳过] {source['name']}: {e}", file=sys.stderr)
    return items


def fetch_pubmed() -> list:
    items = []
    try:
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {"db": "pubmed", "term": PUBMED_QUERY, "retmax": 15,
                  "sort": "date", "retmode": "json"}
        resp = requests.get(search_url, params=params, timeout=20)
        resp.raise_for_status()
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return items

        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        resp = requests.get(fetch_url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        for uid in ids:
            result = data.get("result", {}).get(uid, {})
            title = result.get("title", "")
            if not title:
                continue
            authors = ", ".join(a.get("name", "") for a in result.get("authors", [])[:5])
            source = result.get("source", "")
            items.append({
                "title": html.unescape(title),
                "link": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "summary": f"{source} | {authors}" if authors else source,
                "source": "PubMed",
                "lang": "en",
            })
    except Exception as e:
        print(f"  [跳过] PubMed: {e}", file=sys.stderr)
    return items


def classify_item(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    rules = [
        ("Drug Discovery & Development", ["drug", "pharma", "molecule", "compound", "clinical trial", "药物", "制药"]),
        ("Medical Imaging & Diagnosis",  ["imaging", "diagnos", "radiology", "pathology", "影像", "诊断", "病理"]),
        ("AI Models & LLM",             ["large language model", "llm", "foundation model", "transformer", "gpt", "大模型", "语言模型"]),
        ("Genomics & Biotechnology",    ["genom", "gene", "protein", "cell", "molecular", "基因", "蛋白", "细胞"]),
        ("Clinical Applications",       ["clinical", "patient", "hospital", "surgery", "治疗", "临床", "患者", "手术", "therapy"]),
        ("Digital Health",             ["digital health", "health tech", "wearable", "remote", "数字健康", "可穿戴"]),
        ("Industry & Policy",          ["fda", "approval", "funding", "startup", "investment", "regulation"]),
    ]
    for category, keywords in rules:
        if any(kw in text for kw in keywords):
            return category
    return "Other"


def fetch_article_content(url: str, timeout: int = 12) -> str | None:
    """抓取文章正文，返回纯文本。如果失败返回 None。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct and "application/xhtml" not in ct:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         "noscript", "iframe", "form", "button", "svg", "img"]):
            tag.decompose()
        main = (soup.find("article") or soup.find("main")
                or soup.find("div", class_=re.compile(r"article|post|content|main", re.I))
                or soup.find("body"))
        text = main.get_text(separator="\n", strip=True) if main else ""
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20]
        return "\n".join(lines[:80]) if lines else None
    except Exception:
        return None


def summarize_content(text: str, max_chars: int = 300) -> str:
    """从正文中提取关键段落作为摘要（优先找含有关键词的开头段落）"""
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 30]
    if not paragraphs:
        return text[:max_chars]

    start_idx = 0
    for i, para in enumerate(paragraphs):
        if any(kw.lower() in para.lower() for kw in RELEVANCE_KEYWORDS):
            start_idx = max(0, i - 1)
            break

    result = ""
    for para in paragraphs[start_idx:]:
        if len(result) + len(para) > max_chars:
            remaining = max_chars - len(result)
            if remaining > 20:
                result += para[:remaining]
            break
        result += para + " "
        if len(result) >= max_chars:
            break
    return result.strip()[:max_chars] if result else text[:max_chars]


def fetch_all_articles(items: list) -> dict:
    """并行抓取文章内容，返回 {url: summary_text} 映射。
    跳过 arXiv（RSS 已有完整摘要）和 PubMed（页面不易抓取）。"""
    skip_domains = ("arxiv.org", "pubmed.ncbi.nlm.nih.gov")
    urls = [it["link"] for it in items
            if it["link"].startswith("http") and not any(d in it["link"] for d in skip_domains)]
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        fut_map = {pool.submit(fetch_article_content, url): url for url in urls}
        for fut in as_completed(fut_map):
            url = fut_map[fut]
            try:
                content = fut.result()
                if content:
                    results[url] = summarize_content(content)
            except Exception:
                continue
    return results


def generate_digest():
    today = datetime.now(BJT).strftime("%Y-%m-%d")
    print(f"=== 生成 AI+医疗每日资讯  {today} ===")

    all_items = []

    for src in SOURCES:
        items = fetch_rss(src)
        print(f"  {src['name']}: {len(items)} 条")
        all_items.extend(items)

    pubmed_items = fetch_pubmed()
    print(f"  PubMed: {len(pubmed_items)} 条")
    all_items.extend(pubmed_items)

    relevant = [it for it in all_items if is_relevant(it["title"], it["summary"])]
    seen = set()
    unique = []
    for it in relevant:
        key = it["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(it)

    print(f"\n相关条目（去重后）: {len(unique)} 条")

    # 并行抓取文章正文并生成摘要
    print("正在抓取文章内容并生成摘要...")
    article_summaries = fetch_all_articles(unique)
    summary_count = len(article_summaries)
    print(f"成功获取 {summary_count}/{len(unique)} 篇文章内容")

    zh_items = [it for it in unique if it["lang"] == "zh"]
    en_items = [it for it in unique if it["lang"] == "en"]

    lines = [f"# AI+医疗 每日资讯 — {today}\n"]

    # ---- 中文资讯 ----
    if zh_items:
        lines.append("## 中文资讯\n")
        for item in zh_items[:20]:
            title = item["title"][:80] + "..." if len(item["title"]) > 80 else item["title"]
            lines.append(f"- [{title}]({item['link']}) — {item['source']}")
            summary = article_summaries.get(item["link"], item["summary"])
            if summary:
                display = summary[:400].replace("\n", " ")
                lines.append(f"  > {display}")
            lines.append("")

    # ---- 英文资讯 ----
    if en_items:
        lines.append("## 英文资讯\n")
        categorized = {}
        for item in en_items:
            cat = classify_item(item["title"], item["summary"])
            categorized.setdefault(cat, []).append(item)

        for cat in CATEGORY_ORDER:
            items = categorized.get(cat)
            if not items:
                continue
            cat_zh = CATEGORY_ZH.get(cat, cat)
            lines.append(f"### {cat_zh}\n")
            for item in items[:8]:
                title = item["title"][:100] + "..." if len(item["title"]) > 100 else item["title"]
                lines.append(f"- [{title}]({item['link']}) — {item['source']}")
                summary = article_summaries.get(item["link"], item["summary"])
                if summary:
                    display = summary[:400].replace("\n", " ")
                    lines.append(f"  > {display}")
                lines.append("")

    lines.append("---")
    lines.append(f"*生成时间: {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S BJT')}*\n")

    output_dir = Path("digests")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{today}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n摘要已写入 {output_path}")
    return output_path


if __name__ == "__main__":
    generate_digest()
