## Web Crawling with WebCrawler

**CRITICAL**: For ALL web content extraction, ALWAYS use the `WebCrawler` class from the `crawler` module. NEVER use requests, urllib, curl, wget, or BeautifulSoup directly.

### Basic Web Crawling

```python
from crawler import WebCrawler

# Basic crawl - gets markdown, links, and media
result = await WebCrawler.crawl("https://example.com")
print(result['markdown'])      # Clean markdown content
print(result['links'])         # {'internal': [...], 'external': [...]}
print(result['media'])         # {'images': [...], 'videos': [...], 'audios': [...]}

# Use session for stateful crawling (maintains cookies, auth)
result = await WebCrawler.crawl(
    "https://example.com",
    use_session=True  # Automatically creates and manages session
)
```

### Crawling Multiple URLs

```python
# Crawl multiple URLs in parallel (efficient for research)
urls = ["https://url1.com", "https://url2.com", "https://url3.com"]
results = await WebCrawler.crawl_multiple(
    urls,
    parallel=True,          # Parallel processing
    max_concurrent=5        # Max concurrent requests
)

# Alternative method name (both work identically)
results = await WebCrawler.crawl_batch(urls, parallel=True)
```

### Simple HTTP Crawling (Lightweight Alternative)

```python
# Use for static sites when browser automation isn't needed
# This is faster and uses less resources - good for basic content extraction
result = await WebCrawler.crawl_simple("https://example.com")
if result['success']:
    content = result['markdown']    # Clean markdown content
    title = result['title']         # Page title
else:
    error = result['error']
    # Fallback to full browser crawl if needed
    result = await WebCrawler.crawl("https://example.com")
```

### Search and Crawl (Combined Workflow)

```python
from search_v2 import SearchV2
from crawler import WebCrawler

# Method 1: Using SearchV2 with content extraction
results = SearchV2.search_with_content(
    query="machine learning trends 2025",
    num_results=5,
    extract_highlights=True,
    extract_text=True
)

# Method 2: Manual search then crawl for more detailed content
search_results = SearchV2.search("your query", num_results=5)
urls = [r['url'] for r in search_results.get('results', [])]
crawled = await WebCrawler.crawl_multiple(urls)

# Method 3: Using search_and_crawl helper (still works)
results = await WebCrawler.search_and_crawl(
    query="machine learning trends 2025",
    max_results=5
)
```

### Dynamic Content & JavaScript Sites

```python
# For SPAs and dynamic content
result = await WebCrawler.crawl_dynamic(
    "https://example.com",
    wait_for_selector=".content-loaded",   # Wait for specific element
    scroll_to_bottom=True,                 # Scroll to load content
    infinite_scroll=True,                  # Handle infinite scroll
    max_scroll_attempts=10
)

# Custom JavaScript execution
result = await WebCrawler.crawl(
    "https://example.com",
    js_code="document.querySelector('.load-more').click();"
)
```

### Page Interactions (Forms, Clicks, etc.)

```python
# Interact with page elements (automatically uses session)
interactions = [
    {'type': 'fill', 'selector': '#search', 'value': 'search term'},
    {'type': 'click', 'selector': '.search-button'},
    {'type': 'wait', 'value': 3},
    {'type': 'scroll', 'value': 500}
]

result = await WebCrawler.crawl_with_interaction(
    "https://example.com",
    interactions=interactions
)
```

### Structured Data Extraction

```python
# Extract specific data using CSS selectors
result = await WebCrawler.extract_structured(
    "https://example.com/products",
    css_rules={
        'name': 'h2.product-name',
        'price': '.price',
        'description': '.product-description'
    },
    multiple_items=True  # Extract list of items
)

# Extract with LLM (when CSS is complex)
result = await WebCrawler.extract_with_llm(
    "https://example.com",
    extraction_prompt="Extract all product names, prices, and availability",
    model="gpt-4o-mini"
)
```

### Authenticated Pages

```python
# Basic authentication
result = await WebCrawler.crawl_with_auth(
    "https://protected.example.com",
    auth_type="basic",
    credentials={'username': 'user', 'password': 'pass'}
)

# Form-based login
result = await WebCrawler.crawl_with_auth(
    "https://example.com/dashboard",
    auth_type="form",
    login_url="https://example.com/login",
    credentials={
        'username': 'user@email.com',
        'password': 'password123',
        'username_selector': '#email',
        'password_selector': '#password',
        'submit_selector': 'button[type="submit"]'
    }
)
```

### Advanced Options

```python
# Full control over crawling
result = await WebCrawler.crawl(
    "https://example.com",
    extract_media=True,           # Extract images/videos
    extract_links=True,           # Extract all links
    screenshot=True,              # Take screenshot
    pdf=True,                     # Generate PDF
    css_selector=".main-content", # Extract specific section
    wait_for=".dynamic-content",  # Wait for element
    cache_mode="bypass",          # Cache control
    headless=True,                # Headless browser
    exclude_social=True,          # Exclude social media links
    viewport_width=1920,
    viewport_height=1080
)
```

### Error Handling

```python
result = await WebCrawler.crawl(url)
if result['success']:
    content = result['markdown']
else:
    error = result['error']
    # Handle error or try alternative approach
```

### Choosing the Right Crawling Method

```python
# Decision tree for method selection:

# 1. For static content sites (news, blogs, documentation)
result = await WebCrawler.crawl_simple("https://example.com")

# 2. If crawl_simple fails, try full browser crawl
if not result['success']:
    result = await WebCrawler.crawl("https://example.com")

# 3. For known dynamic/JS-heavy sites (SPAs, social media)
result = await WebCrawler.crawl_dynamic("https://app.example.com")

# 4. For multiple URLs (research, aggregation)
results = await WebCrawler.crawl_multiple(urls, parallel=True)

# 5. For specific data extraction
result = await WebCrawler.extract_structured(url, css_rules={...})
```

### Important WebCrawler Rules:

1. **NEVER use requests, urllib, curl, or BeautifulSoup** - Always use WebCrawler
2. **NEVER parse HTML manually** - WebCrawler returns clean markdown
3. **ALWAYS use WebCrawler for web content** - It handles JavaScript, authentication, and dynamic content
4. **Choose the right crawling method**:
   - Use `crawl_simple()` for static sites (faster, lightweight)
   - Use `crawl()` for JavaScript-heavy or dynamic sites
   - Use `crawl_multiple()` or `crawl_batch()` for parallel processing
5. **Use sessions for stateful operations** - Sessions maintain cookies and authentication
6. **Prefer parallel crawling** for multiple URLs - It's much faster
7. **Use search_and_crawl** for research tasks - Combines search + crawl efficiently
8. **Handle errors gracefully** - Check result['success'] before using content
9. **Automatic fallback** - The crawler will automatically use the best available method
