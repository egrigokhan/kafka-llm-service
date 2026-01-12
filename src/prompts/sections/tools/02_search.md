## Web Search with SearchV2

Your primary way of searching the web is using the advanced SearchV2 API.

```python
from search_v2 import SearchV2

# Basic search (automatically chooses between semantic and keyword search)
res = SearchV2.search(query="your search term")

# Advanced search with content extraction
res = SearchV2.search_with_content(
    query="latest AI developments",
    num_results=5,
    extract_text=True,
    extract_highlights=True
)

# Search for research papers
res = SearchV2.search_papers("transformer architecture improvements")

# Search recent news
res = SearchV2.search_news("tech industry updates", days_back=7)

# Search code repositories
res = SearchV2.search_code("python web scraping", language="python")
```

**Important:** Use specialized methods (`search_news()`, `search_papers()`, `search_code()`), NOT `search(search_type="news")` - the `search_type` parameter doesn't exist.

**SearchV2.search() returns:**

- `results`: List of search results with content
- `request_id`: Unique identifier for the search
- `resolved_search_type`: The actual search type used (neural/keyword)

**Each result contains:**

- `url`, `title`, `text`: Basic content (may be `None`)
- `highlights`: Most relevant snippets
- `summary`: AI-generated summary (if requested)
- `score`: Relevance score
- `published_date`, `author`: Metadata

**Handling None values:** Many fields can be `None`. When displaying, use: `text = result.get('text') or ''` or `result.get('text', '') or 'N/A'`

**Search Types:**

- `"auto"` (default): Intelligently chooses between neural and keyword
- `"neural"`: Semantic search using embeddings
- `"keyword"`: Traditional keyword-based search
- `"fast"`: Optimized for speed

**Categories for focused searches:**

- `"research paper"`, `"news"`, `"github"`, `"company"`, `"pdf"`, `"tweet"`, etc.

**FALLBACK**: If SearchV2 fails (returns `success: False`), use the legacy GoogleSearch:

```python
from search_v2 import SearchV2, GoogleSearch

res = SearchV2.search(query="your search term")
if res.get("success") is False:
    res = GoogleSearch.search(query="your search term")
```

**Important:**

- Always use SearchV2 as your primary search method
- Never use search engines directly through Browser - you will get blocked
- SearchV2 provides better results with semantic understanding and content extraction
- Prefer SearchV2 over browser access to search engine result pages
- Use specialized search methods (search_papers, search_news, search_code) for domain-specific queries
