#!/usr/bin/env python3
"""AI+Medical Daily Digest Generator"""

import feedparser
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
import html
import re
import sys

BJT = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

SOURCES = [
    # English
    {"name": "ArXiv AI",        "feed": "http://export.arxiv.org/rss/cs.AI",          "lang": "en"},
    {"name": "ArXiv ML",        "feed": "http://export.arxiv.org/rss/cs.LG",          "lang": "en"},
    {"name": "ArXiv Bio",       "feed": "http://export.arxiv.org/rss/q-bio.QM",       "lang": "en"},
    {"name": "Nature AI",       "feed": "https://www.nature.com/subjects/artificial-intelligence.rss", "lang": "en"},
    {"name": "MIT Tech Review", "feed": "https://www.technologyreview.com/tag/artificial-intelligence/feed/", "lang": "en"},
    {"name": "TechCrunch AI",   "feed": "https://techcrunch.com/category/artificial-intelligence/feed/", "lang": "en"},
    # Chinese
    {"name": "Google News - AI医疗",  "feed": "https://news.google.com/rss/search?q=AI+%E5%8C%BB%E7%96%97&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "lang": "zh"},
    {"name": "Google News - 人工智能医疗", "feed": "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+%E5%8C%BB%E7%96%97&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "lang": "zh"},
]

PUBMED_QUERY = (
    "((artificial intelligence) OR (machine learning) OR (deep learning)) "
    "AND (healthcare OR medical OR clinical OR drug OR diagnosis)"
)

RELEVANCE_KEYWORDS = [
    # English
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
    # Chinese
    "人工智能", "深度学习", "机器学习", "大模型", "大语言模型",
    "医疗", "医学", "健康", "临床", "药物", "诊断",
    "影像", "基因", "蛋白", "细胞", "病理",
    "手术", "治疗", "生物", "制药", "医院",
    "数字健康", "精准医疗", "医疗AI", "智慧医疗",
    "临床试验", "医疗器械", "生物技术",
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
            items.append({
                "title": title,
                "link": link,
                "summary": summary[:400],
                "source": source["name"],
                "lang": source["lang"],
            })
    except Exception as e:
        print(f"  [SKIP] {source['name']}: {e}", file=sys.stderr)
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
        print(f"  [SKIP] PubMed: {e}", file=sys.stderr)
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


def generate_digest():
    today = datetime.now(BJT).strftime("%Y-%m-%d")
    print(f"=== Generating AI+Medical Digest for {today} ===")

    all_items = []

    for src in SOURCES:
        items = fetch_rss(src)
        print(f"  {src['name']}: {len(items)} items")
        all_items.extend(items)

    pubmed_items = fetch_pubmed()
    print(f"  PubMed: {len(pubmed_items)} items")
    all_items.extend(pubmed_items)

    relevant = [it for it in all_items if is_relevant(it["title"], it["summary"])]
    seen = set()
    unique = []
    for it in relevant:
        key = it["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(it)

    print(f"\nTotal relevant items: {len(unique)}")

    zh_items = [it for it in unique if it["lang"] == "zh"]
    en_items = [it for it in unique if it["lang"] == "en"]

    lines = [f"# AI+医疗 每日资讯 — {today}\n"]

    if zh_items:
        lines.append("## 中文资讯\n")
        for item in zh_items[:20]:
            title = item["title"][:80] + "..." if len(item["title"]) > 80 else item["title"]
            lines.append(f"- [{title}]({item['link']}) — {item['source']}")
            if item["summary"]:
                lines.append(f"  > {item['summary'][:200].replace(chr(10), ' ')}")
            lines.append("")

    if en_items:
        lines.append("## English News\n")
        categorized = {}
        for item in en_items:
            cat = classify_item(item["title"], item["summary"])
            categorized.setdefault(cat, []).append(item)

        cat_order = ["AI Models & LLM", "Drug Discovery & Development", "Medical Imaging & Diagnosis",
                     "Genomics & Biotechnology", "Clinical Applications", "Digital Health",
                     "Industry & Policy", "Other"]
        for cat in cat_order:
            items = categorized.get(cat)
            if not items:
                continue
            lines.append(f"### {cat}\n")
            for item in items[:8]:
                title = item["title"][:100] + "..." if len(item["title"]) > 100 else item["title"]
                lines.append(f"- [{title}]({item['link']}) — {item['source']}")
                if item["summary"]:
                    lines.append(f"  > {item['summary'][:200].replace(chr(10), ' ')}")
                lines.append("")

    lines.append("---")
    lines.append(f"*Generated on {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S BJT')}*\n")

    output_dir = Path("digests")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{today}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDigest written to {output_path}")
    return output_path


if __name__ == "__main__":
    generate_digest()
