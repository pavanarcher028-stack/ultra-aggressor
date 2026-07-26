"""
Knowledge Scraper — Pulls research papers, blogs, and books from the internet.
Integrates with web search to continuously expand the knowledge base.
"""
import json
import re
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path


class KnowledgeScraper:
    def __init__(self):
        self.knowledge_dir = Path(__file__).parent / "knowledge"
        self.knowledge_dir.mkdir(exist_ok=True)
        self.sources_file = self.knowledge_dir / "sources.json"

    def fetch_arxiv_papers(self, query="cryptocurrency trading strategy", max_results=10):
        """Fetch papers from ArXiv API."""
        base_url = "http://export.arxiv.org/api/query"
        params = f"search_query=all:{urllib.parse.quote(query)}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
        url = f"{base_url}?{params}"

        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "AutonomousTradingAI/1.0")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode("utf-8")

            papers = []
            entries = re.findall(r"<entry>(.*?)</entry>", data, re.DOTALL)
            for entry in entries:
                title = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                summary = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                paper_id = re.search(r"<id>(.*?)</id>", entry, re.DOTALL)
                if title:
                    papers.append({
                        "title": title.group(1).strip(),
                        "summary": summary.group(1).strip()[:500] if summary else "",
                        "url": paper_id.group(1).strip() if paper_id else "",
                        "source": "arxiv",
                    })
            return papers
        except Exception as e:
            print(f"  ArXiv fetch error: {e}")
            return []

    def fetch_ssrn_papers(self, query="cryptocurrency", max_results=5):
        """Fetch papers from SSRN search."""
        base_url = "https://api.ssrn.com/v1/papers/search"
        params = urllib.parse.urlencode({
            "query": query,
            "limit": max_results,
        })
        url = f"{base_url}?{params}"

        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "AutonomousTradingAI/1.0")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            papers = []
            for item in data.get("results", []):
                papers.append({
                    "title": item.get("title", ""),
                    "summary": item.get("abstract", "")[:500],
                    "url": item.get("url", ""),
                    "source": "ssrn",
                })
            return papers
        except Exception:
            return []

    def crawl_investment_blogs(self):
        """Scrape key investment blogs for strategy ideas."""
        blog_urls = [
            "https://www.quantamagazine.org/tag/computer-science/",
            "https://www.investopedia.com/",
        ]
        articles = []
        for url in blog_urls:
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "AutonomousTradingAI/1.0")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8")
                titles = re.findall(r"<h[23][^>]*>(.*?)</h[23]>", html)
                for t in titles[:5]:
                    clean = re.sub(r"<[^>]+>", "", t).strip()
                    if clean and len(clean) > 10:
                        articles.append({
                            "title": clean,
                            "url": url,
                            "source": "blog",
                        })
            except Exception:
                continue
        return articles

    def expand_knowledge_base(self):
        """Run all scrapers and add findings to the knowledge base."""
        print("  Expanding knowledge base from internet...")

        queries = [
            "cryptocurrency momentum trading strategy",
            "machine learning crypto trading",
            "statistical arbitrage cryptocurrency",
            "deep reinforcement learning portfolio optimization",
            "trend following crypto strategy 2025",
        ]

        all_papers = []
        for q in queries:
            papers = self.fetch_arxiv_papers(q, max_results=3)
            all_papers.extend(papers)

        blogs = self.crawl_investment_blogs()

        # Save sources
        sources = {
            "papers": all_papers,
            "blogs": blogs,
            "fetched_at": __import__("datetime").datetime.now().isoformat(),
        }
        with open(self.sources_file, "w", encoding="utf-8") as f:
            json.dump(sources, f, indent=2)

        print(f"  Found {len(all_papers)} papers, {len(blogs)} blog articles")
        return sources
