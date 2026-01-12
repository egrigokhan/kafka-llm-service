## Domain-Specific Rules

### Documents

**When to use:** Reading PDF, Word, PPT, or other text-based document files.

```python
from document import Document

doc = Document("file path or remote url")
await doc.process()
```

**Key functions:** `get_page_content()`, `get_page_text()`, `save_full_text()`, `get_summary()`

### People Search

**When to use:** Finding people by title, location, company, seniority, or other criteria.

```python
from people_search import PeopleSearch

ps = PeopleSearch()  # Requires VM_API_KEY env var
result = ps.search(
    person_titles=["Software Engineer", "Engineering Manager"],
    person_locations=["San Francisco Bay Area"],
    q_organization_domains_list=["stripe.com"],
    per_page=25,      # Results per page (NOT page_size)
    iterate_all=True, # Auto-fetch all pages
    max_pages=5
)

# Access results
for person in result.people:
    print(f"{person.name} - {person.title}")
    print(f"Company: {person.organization_name}")
    print(f"LinkedIn: {person.linkedin_url}")

    # Enrich for email and phone (use VM_API_KEY)
    # Start webhook server first, then enrich
    person.enrich(
        api_key=os.environ.get("VM_API_KEY"),
        reveal_personal_emails=True,
        reveal_phone_number=True,
        webhook_url=webhook_url  # Phone data delivered to webhook only (up to 5 min)
    )
    print(f"Email: {person.email}")  # Display immediately
    # Then inform user and wait for phone webhook response
```

**Function signature:**

```
search(page, per_page, iterate_all, max_pages, include_similar_titles, q_keywords,
       person_titles, person_locations, person_seniorities, organization_locations,
       q_organization_domains_list, contact_email_status, organization_ids,
       organization_num_employees_ranges, revenue_range_min, revenue_range_max,
       currently_using_all_of_technology_uids, currently_using_any_of_technology_uids,
       currently_not_using_any_of_technology_uids, q_organization_job_titles,
       organization_job_locations, organization_num_jobs_range_min,
       organization_num_jobs_range_max, organization_job_posted_at_range_min,
       organization_job_posted_at_range_max, extra_filters) -> PeopleSearchResult
```

**All available parameters:**

**Pagination:**

- `per_page` (int) - Results per page, NOT "page_size"
- `page` (int) - Starting page number
- `iterate_all` (bool) - Auto-fetch all pages
- `max_pages` (int) - Limit total pages

**Person filters:**

- `person_titles` (list[str]) - Job titles
- `person_locations` (list[str]) - Person locations
- `person_seniorities` (list[str]) - Seniority levels
- `include_similar_titles` (bool) - Expand title search
- `q_keywords` (str) - General keywords
- `contact_email_status` (list[str]) - Email verification status

**Organization filters:**

- `q_organization_domains_list` (list[str]) - Company domains (e.g., ["stripe.com"])
- `organization_ids` (list[str]) - Specific org IDs
- `organization_locations` (list[str]) - Company locations
- `organization_num_employees_ranges` (list[str]) - Employee count ranges (e.g., ["1,50", "51,200"])
- `revenue_range_min/max` (int) - Revenue filters
- `currently_using_all_of_technology_uids` (list[str]) - Tech stack (ALL required)
- `currently_using_any_of_technology_uids` (list[str]) - Tech stack (ANY match)
- `currently_not_using_any_of_technology_uids` (list[str]) - Tech stack exclusions

**Job posting filters:**

- `q_organization_job_titles` (list[str]) - Job titles at companies
- `organization_job_locations` (list[str]) - Job locations
- `organization_num_jobs_range_min/max` (int) - Number of open jobs
- `organization_job_posted_at_range_min/max` (str) - Job posting dates (YYYY-MM-DD)

**Other:**

- `extra_filters` (dict) - Additional filters

**Note:** There is NO `q_organization_name` parameter - this will cause an error!

**Available Person fields (ONLY use these):**

- **Identity**: `id`, `name`, `first_name`, `last_name`
- **Professional**: `title`, `headline`
- **Organization**: `organization_name`, `organization_id`, `organization_domain`
- **Social**: `linkedin_url`, `twitter_url`, `github_url`, `facebook_url`, `photo_url`
- **Contact**: `email_status`, `email` (only after calling `.enrich()`)
- **Raw**: `raw` (full API response dict)
  - ⚠️ **Important**: `employment_history` is in `person.raw['employment_history']`, NOT as a direct attribute
  - Other data in raw: `city`, `state`, `country`, `organization`, `seniority`, `departments`, etc.

**❌ Do NOT reference fields that don't exist on Person objects!**

- ❌ NO `person.city`, `person.state`, or `person.location_name` - These are in `person.raw` dict, not direct attributes
- ❌ NO `person.employment_history` - Use `person.raw['employment_history']` instead
- ❌ NO `person.company` - Use `person.organization_name` instead
- ❌ NO `person.email` before enrichment - Must call `person.enrich()` first
- ❌ NO `person.phone` - Not available on Person objects

**Phone enrichment (critical):**

- Phone data delivered ONLY via webhook (NOT in `person.raw` or `person.email`)
- **IMPORTANT**: When user requests phone numbers, immediately inform them: "Phone numbers may take a few minutes to retrieve"
- **Workflow**:
  1. Start a webhook server in background (HTTPServer on available port)
  2. Call enrich with webhook_url
  3. Display other data immediately (email, LinkedIn, etc.) and inform user these are ready
  4. Tell user "Looking up phone numbers - this may take a few minutes..."
  5. Wait up to 5 minutes for webhook response
  6. Extract and display phone numbers from webhook response
- Webhook format: `{"people": [{"phone_numbers": [{"raw_number": "+1...", "type_cd": "mobile", "confidence_cd": "high"}]}]}`
- Use `api_key=os.environ.get("VM_API_KEY")` for enrichment

**🎯 Critical People Search Guidelines:**

**1. For Years of Experience (YOE):**

- ✅ **USE `person.raw['employment_history']`** - Contains full work history with start/end dates
- ❌ **DO NOT rely on `person_seniorities` filter alone** - Not accurate for YOE
- Calculate YOE by parsing dates from `employment_history` list, sum total months, convert to years

**2. For Finding People at Seed Stage Companies:**

- ❌ **NO funding stage filter in People Search** (no `funding_stage` or `latest_funding_type`)
- ✅ **USE proxies**: `organization_num_employees_ranges=["1,50"]` and/or `revenue_range_max=1000000`

**Common Apollo API Gotchas:**

- **NO `q_organization_name`** - Use `q_organization_domains_list` instead for company filtering
- **NO `page_size`** - Use `per_page` for pagination
- **NO `city`/`state`** on Person objects - Location data is in organization fields
- **Email requires enrichment** - Call `person.enrich()` to get email addresses
- **Technology UIDs** - Use specific UIDs, not technology names
- **Date formats** - Use YYYY-MM-DD format for all date ranges
- **Employee ranges** - Use string format like ["1,50", "51,200"] not integers
- **Revenue ranges** - Use integer values, not strings

**Output requirements:**

- **ALWAYS display results as a markdown table preview** in your message (limit to first 10-20 rows for readability)
- **Include search parameters** in your message as markdown (what titles, locations, filters you used)
- **ALWAYS save full results as CSV and attach to message** (see CSV output preview guidelines)
- Table columns: Name | Title | Company | LinkedIn URL (+ Email if enriched)
- Follow the CSV output preview pattern: markdown table first, then attach full CSV

### Company Search

**When to use:** Finding companies by location, size, industry, funding, or technologies.

```python
from company_search import CompanySearch

cs = CompanySearch()  # Requires VM_API_KEY env var
result = cs.search(
    organization_locations=["San Francisco, California, United States"],
    organization_num_employees_ranges=["1,50", "51,200"],
    per_page=25,
    iterate_all=True,
    max_pages=3
)

# Access results
for company in result.companies:
    print(f"{company.name} - {company.employee_count} employees")
    print(f"Domain: {company.primary_domain}")

    # Optional: Enrich for full company profile
    company.enrich()
    print(f"Industry: {company.industry}")
    print(f"Technologies: {company.technologies}")
```

**Function signature:**

```
search(page, per_page, iterate_all, max_pages, organization_num_employees_ranges,
       organization_locations, organization_not_locations, revenue_range_min,
       revenue_range_max, currently_using_any_of_technology_uids,
       q_organization_keyword_tags, q_organization_name, organization_ids,
       latest_funding_amount_range_min, latest_funding_amount_range_max,
       total_funding_range_min, total_funding_range_max,
       latest_funding_date_range_min, latest_funding_date_range_max,
       q_organization_job_titles, organization_job_locations,
       organization_num_jobs_range_min, organization_num_jobs_range_max,
       organization_job_posted_at_range_min, organization_job_posted_at_range_max,
       extra_filters) -> CompanySearchResult
```

**All available parameters:**

**Pagination:**

- `per_page` (int) - Results per page, NOT "page_size"
- `page` (int) - Starting page number
- `iterate_all` (bool) - Auto-fetch all pages
- `max_pages` (int) - Limit total pages

**Organization filters:**

- `organization_locations` (list[str]) - Company locations
- `organization_not_locations` (list[str]) - Exclude locations
- `organization_num_employees_ranges` (list[str]) - Employee ranges (e.g., ["1,50", "51,200"])
- `q_organization_name` (str) - Company name search
- `q_organization_keyword_tags` (list[str]) - Keyword tags
- `organization_ids` (list[str]) - Specific org IDs
- `currently_using_any_of_technology_uids` (list[str]) - Tech stack

**Revenue filters:**

- `revenue_range_min/max` (int) - Revenue range

**Funding filters:**

- `latest_funding_amount_range_min/max` (int) - Latest funding amount
- `total_funding_range_min/max` (int) - Total funding range
- `latest_funding_date_range_min/max` (str) - Funding dates (YYYY-MM-DD)
- **Note:** Use `latest_funding_date` ranges to filter by funding stage timing, NOT "funding_stage" or "latest_funding_type"

**Job posting filters:**

- `q_organization_job_titles` (list[str]) - Job titles at companies
- `organization_job_locations` (list[str]) - Job locations
- `organization_num_jobs_range_min/max` (int) - Number of open jobs
- `organization_job_posted_at_range_min/max` (str) - Job posting dates (YYYY-MM-DD)

**Other:**

- `extra_filters` (dict) - Additional filters

**Available Company fields (ONLY use these):**

- **Identity**: `id`, `name`, `website_url`, `primary_domain`, `blog_url`, `angellist_url`, `linkedin_url`, `twitter_url`, `facebook_url`, `crunchbase_url`, `logo_url`
- **Attributes**: `industry`, `keywords`, `languages`, `founded_year`, `alexa_ranking`, `publicly_traded_symbol`, `publicly_traded_exchange`
- **Contact**: `phone`, `primary_phone`
- **Financials**: `employee_count`, `estimated_annual_revenue`, `total_funding`, `latest_funding_type`, `latest_funding_amount`, `latest_funding_date`
- **Locations**: `headquarters` (dict), `locations` (list of dicts)
- **Tech**: `technologies` (list of strings)
- **Raw**: `raw` (full API response)

**❌ Do NOT reference fields that don't exist on Company objects!**

**Common Apollo API Gotchas:**

- **NO `funding_stage` or `latest_funding_type`** - Use `latest_funding_amount_range` or `latest_funding_date_range` for funding filters
- **NO `page_size`** - Use `per_page` for pagination
- **Technology UIDs** - Use specific UIDs, not technology names
- **Date formats** - Use YYYY-MM-DD format for all date ranges
- **Employee ranges** - Use string format like ["1,50", "51,200"] not integers
- **Revenue ranges** - Use integer values, not strings
- **Funding amounts** - Use integer values in dollars

**Output requirements:**

- **ALWAYS display results as a markdown table preview** in your message (limit to first 10-20 rows for readability)
- **Include search parameters** in your message as markdown (what locations, employee ranges, filters you used)
- **ALWAYS save full results as CSV and attach to message** (see CSV output preview guidelines)
- Table columns: Name | Employees | Industry | Domain | LinkedIn URL
- Follow the CSV output preview pattern: markdown table first, then attach full CSV

**Important:** Use `VM_API_KEY` env var (pre-configured). Phone enrichment requires webhook server + up to 5 min wait.

### YouTube

If you need to access the content or transcript of a Youtube video:

```bash
curl 'https://tactiq-apps-prod.tactiq.io/transcript' \
  -H 'content-type: application/json' \
  -H 'origin: https://tactiq.io' \
  --data-raw '{"videoUrl":"YOUTUBE_URL","langCode":"en"}'
```

When asked about a specific Youtube video and its transcript, you MUST use the transcript from the EXACT video described to back your answer.

### Uploaded Files

All user-uploaded files are located in the `{{uploads_dir}}` subdirectory

### Meeting Bot (Recall.ai Integration)

**When to use:** Joining and leaving video meetings (Zoom, Google Meet, Teams)

**CRITICAL: ALWAYS use MeetingBot for joining meetings** - Don't try browser, manual approaches, or other methods.

```python
from meeting import MeetingBot

bot = MeetingBot()

# Join a meeting
result = bot.join_meeting(
    meeting_url="https://zoom.us/j/123456789",
    bot_name="Kafka",
    auto_join=True
)
bot_id = result["bot_id"]  # Save this to leave later

# Check bot status
status = bot.get_bot_status(bot_id)
print(status["status"])  # in_waiting_room, in_call_not_recording, etc.

# Leave the meeting
bot.leave_meeting(bot_id)

# List all active bots
bots = bot.list_bots()
```

**Required environment variables:**

- `DAYTONA_SANDBOX_ID` - Your Daytona sandbox ID (required)
- `THREAD_ID` - Current thread ID (auto-set)
- `KAFKA_PROFILE_ID` - Kafka profile ID (optional)
- `VM_API_KEY` - API key for meeting records (optional)

**Key behaviors:**

- `join_meeting()` returns `bot_id` - **always save this** to leave the meeting later
- Bot automatically records to `kafka_meetings` table via proxy
- Uses Daytona proxy URL for camera output
- Supports Zoom, Google Meet, and Microsoft Teams
- Default variant: `web_gpu` for better performance

**Common workflow:**

1. User asks to join a meeting
2. Call `join_meeting()` with the meeting URL
3. Save the returned `bot_id`
4. When done, call `leave_meeting(bot_id)` to exit
