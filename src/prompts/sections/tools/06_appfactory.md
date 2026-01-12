---

# PART 4 (CONTINUED): APPFACTORY INTEGRATION GUIDE

## Third-Party Integrations (AppFactory)

# Apps & Actions: Step-by-Step Guide

This guide shows how to discover, configure, and run **App actions** using the `AppFactory`. The system includes intelligent validation, sequential dependency management, and automatic prop reloading.

## 🚀 Key Features

1. **Sequential Dependency Validation**: Ensures required remote option props are configured in the correct order
2. **Automatic Value Validation**: Validates configured values against fetched options
3. **Smart Prop Reloading**: Automatically reloads component props when configuring props with `reloadProps=true`
4. **Dependency Clearing**: Clears dependent props when their parent props change
5. **Helpful Error Messages**: Clear feedback about what's wrong and how to fix it

## Concepts in 30 seconds

- **AppFactory**: entry point to get an app instance (e.g., `"google_drive"`)
- **App**: a connector/integration that exposes one or more **actions**
- **Action**: a callable unit (e.g., `"google_drive-upload-file"`) with **properties** you configure before running
- **Properties**: inputs to the action (strings, numbers, booleans, files, etc.)
- **Remote options**: some properties have dynamic, server-fetched choices (e.g., folders). Use `get_options_for_prop(...)` **only** for these

## 0) Discover available apps

Search for apps by their slug (app identifier). Use `list_apps(query="app_slug")` to find apps.

```python
from integrations import AppFactory

factory = AppFactory()

# Search for specific apps by slug
# list_apps() returns a simple list of matching app slugs (strings)
apps = factory.list_apps(query="salesforce")
print(apps)  # Output: ['salesforce', 'salesforce_sandbox', ...]

# Just print the results to see matching apps
people_apps = factory.list_apps(query="apollo")
print("Available apollo-related apps:")
print(people_apps)  # This prints the list of app slugs

# More examples
slack_apps = factory.list_apps(query="slack")
print(slack_apps)  # ['slack', 'slack_bot', ...]

# List all apps (returns all 2000+ app slugs - usually not needed)
all_apps = factory.list_apps()
```

**What list_apps() returns:**

- Returns a **list of strings** (app slugs), NOT a list of objects
- Example output: `['salesforce', 'salesforce_sandbox']`
- Do NOT try to call `.get()` on the results - they are strings, not dictionaries

**Correct usage:**

```python
apps = factory.list_apps(query="apollo")
print(apps)  # Just print the list

# If you find the right app slug, load it directly:
if apps:
    apollo = factory.app(apps[0])  # Load first matching app
```

**Common app slugs:**
`"notion"`, `"google_sheets"`, `"google_docs"`, `"google_calendar"`, `"google_drive"`, `"airtable"`, `"trello"`, `"asana"`, `"clickup"`, `"monday"`, `"coda"`, `"linear"`, `"smartsheet"`, `"confluence"`, `"evernote"`, `"quip"`, `"todoist"`, `"figma"`, `"canva"`, `"adobe_acrobat_sign"`, `"docusign"`, `"miro"`, `"lucidchart"`, `"slack"`, `"microsoft_teams"`, `"zoom"`, `"gmail"`, `"outlook"`, `"telegram"`, `"discord"`, `"whatsapp_business"`, `"intercom"`, `"calendly"`, `"front"`, `"twilio"`, `"dropbox"`, `"box"`, `"onedrive"`, `"egnyte"`, `"mysql"`, `"postgresql"`, `"mongodb"`, `"snowflake"`, `"supabase"`, `"firebase"`, `"bigquery"`, `"redshift"`, `"aws"`, `"github"`, `"gitlab"`, `"bitbucket"`, `"netlify"`, `"webflow"`, `"vercel"`, `"sentry"`, `"heroku"`, `"jenkins"`, `"salesforce"`, `"hubspot"`, `"zoho_crm"`, `"pipedrive"`, `"freshsales"`, `"shopify"`, `"woocommerce"`, `"stripe"`, `"square"`, `"paypal"`, `"amazon"`, `"apollo"`, `"greenhouse"`, `"ashby"`, `"jira"`, `"quickbooks"`

**Note:** The query parameter searches for the **app slug**, not the display name. Use lowercase with underscores (e.g., `"google_drive"` not `"Google Drive"`).

## 1) Initialize the factory and load an app

```python
from integrations import AppFactory

factory = AppFactory()
google_drive = factory.app("google_drive")
```

**🔐 Authentication Rule:** If an integration isn't connected, STOP immediately, send the authentication link to the user, and ask them to authenticate - don't try alternative methods or workarounds.

## 2) Discover available actions

```python
print(google_drive)
```

## 2a) Search actions within an app (semantic/match)

Use `app.search_actions(query, limit=10)` to quickly find the most relevant actions within a specific app by name, slug, and description.

```python
from integrations import AppFactory

factory = AppFactory()
clickup = factory.app("clickup")

# Search for actions within ClickUp related to team membership
matches = clickup.search_actions("team members", limit=5)
for m in matches:
    print(f"{m.get('name')} ({m.get('key')}) score={m.get('score'):.2f}")

# Example output:
# Get Team Members (clickup-get-team-members) score=0.95
# Add Team Member (clickup-add-team-member) score=0.87
```

**EFFICIENCY TIP**: When you need to work with multiple items, **look for batch/bulk actions**:

```python
# ❌ INEFFICIENT: Updating multiple cells one by one
google_sheets.search_actions("update cell")
# → Returns: Update Cell, Update Row, Update Multiple Rows, ...

# ✅ EFFICIENT: Choose the batch operation
google_sheets.search_actions("update multiple")
# → Returns: Update Multiple Rows - use this for multiple updates!
```

**Common batch action patterns to look for:**

- `"update-multiple-rows"` over `"update-cell"` (when updating multiple cells)
- `"create-multiple-tasks"` over `"create-task"` (when creating multiple tasks)
- `"batch-upload"` over `"upload-file"` (when uploading multiple files)
- `"bulk-send"` over `"send-email"` (when sending multiple emails)

**Best practice:** When working with multiple items, check if batch actions like "multiple", "batch", or "bulk" are available before defaulting to single-item operations.

**GOOGLE SHEETS SPECIFIC**: Always use `google_sheets-add-multiple-rows` instead of `google_sheets-add-single-row`. The single row action is bugged. The multiple rows action can handle both single and multiple rows correctly.

```python
# ❌ AVOID: google_sheets-add-single-row (bugged)
# ✅ ALWAYS USE: google_sheets-add-multiple-rows (works for single or multiple rows)

google_sheets = factory.app("google_sheets")
add_rows = google_sheets.action("google_sheets-add-multiple-rows")

# Works for single row
add_rows.configure({
    "spreadsheetId": "abc123",
    "rows": [{"Name": "John", "Email": "john@example.com"}]
})

# Works for multiple rows
add_rows.configure({
    "spreadsheetId": "abc123",
    "rows": [
        {"Name": "John", "Email": "john@example.com"},
        {"Name": "Jane", "Email": "jane@example.com"}
    ]
})
```
**GMAIL ACTION SPECIFIC**: When drafting a reply to an email, or sending a reply to an email, you should default to sending it in the same email thread. 

**PAGINATION TIP**: Many list/search actions return paginated results. Always check the response for:

```python
# After running a list/search action, check for pagination
result = action.run()
ret = result.get("ret", {})

# Look for pagination indicators:
next_token = ret.get("nextToken") or ret.get("cursor") or ret.get("pageToken")
has_more = ret.get("hasMore") or ret.get("has_next_page")

# If pagination exists, loop to get all data:
all_items = ret.get("items", [])
while next_token or has_more:
    # Configure action with pagination token and run again
    action.configure({"pageToken": next_token})
    result = action.run()
    ret = result.get("ret", {})
    all_items.extend(ret.get("items", []))
    next_token = ret.get("nextToken")
    has_more = ret.get("hasMore")
```

**Common pagination fields**: `nextToken`, `cursor`, `pageToken`, `hasMore`, `has_next_page`, `next_cursor`, `offset`, `page`

Notes:

- `search_actions()` is called on an **app instance** (e.g., `clickup.search_actions()`)
- It searches within that specific app's available actions
- Internally calls `list_actions(pretty_print=False)` and ranks results locally
- Always execute actions by their actual slug returned in `list_actions`/`search_actions`

Pick the action you need:

```python
# For single item
upload_file = google_drive.action("google_drive-upload-file")

# For multiple items - look for batch actions
update_rows = google_sheets.action("google_sheets-update-multiple-rows")
```

## 3) Configure the action

Print the action to see what inputs it requires: `print(upload_file)`

## 3a) Common Mistakes to Avoid ⚠️

### 1. Array Fields - Use Lists!

```python
# ❌ WRONG
action.configure({"assignees": 99927317.0})  # Single value for array field

# ✅ CORRECT
action.configure({"assignees": [99927317.0]})  # List for array field
```

### 2. Static Options - Use Exact Values!

```python
# ❌ WRONG
action.configure({"priority": "4. Low"})  # Don't use display indices

# ✅ CORRECT
action.configure({"priority": "Low"})  # Use exact value from options
```

### 3. Result Validation - Don't Trust Status Alone!

```python
# ❌ WRONG
result = action.run()
print("Success!")  # Assuming it worked

# ✅ CORRECT
result = action.run()
ret = result.get("ret", {})
if ret.get("priority", {}).get("priority") != "low":
    print("⚠️ Priority wasn't set correctly!")
```

### 4. Don't Assume Sequential Dependencies

Remote option props are generally INDEPENDENT. You can fetch/configure them in any order.

## 3b) Understanding Remote Options and Configuration Flow

**Remote Options** are properties whose valid values are fetched dynamically from the integrated service.

### Critical Rules for Remote Options:

1. **Two Approaches**: You can either:

   - **Discovery Flow**: Fetch options for props you need to discover
   - **Direct Configuration**: Skip straight to configuring if you know the value

2. **No Sequential Dependency Enforcement**: Remote option props are generally INDEPENDENT

3. **Skip Unnecessary Steps**: Don't waste time fetching props you don't need

4. **Validation**: Once options are fetched for a prop, the system validates your configuration values

5. **Automatic Reload**: Props with `reloadProps=true` automatically trigger a props reload when configured

   This reload may:

   - Update available options for other props
   - Generate entirely new configurable props based on your data
   - Change validation rules for dependent props

   After the reload completes, print the action to see what changed.

6. **Options Cache Invalidation**: When you change a prop with `reloadProps=true`, cached options for subsequent remote props are invalidated

7. **Handling Dynamic Props from reloadProps**: Some props generate NEW configurable properties when set

   - Props marked with 🔄 (reloadProps=true) can generate additional props after configuration
   - After configuring such props, **print the action again** to see newly generated fields
   - These new fields will appear in the action's prop list and must be configured before running

   **Pattern:**

   ```python
   action = app.action("some-action")
   print(action)  # Shows: propA (🔄), propB

   # Configure the reload prop
   action.configure({"propA": "value"})

   # Print again to see dynamically generated props
   print(action)  # Now shows: propA, propB, propC (new!), propD (new!)

   # Configure the new props
   action.configure({
       "propC": "value",
       "propD": "value"
   })

   # Now run
   result = action.run()
   ```

   **Key behaviors:**

   - Dynamic props appear AFTER configuring the reload prop, not before
   - They're based on your data/configuration (e.g., reading column names from a spreadsheet)
   - Always print after configuring reload props to discover what new fields are available
   - Configure all required dynamic props before running the action

### Example 1: Wizard Flow (when you need to discover values)

```python
from integrations import AppFactory

factory = AppFactory()
clickup = factory.app("clickup")
create_task = clickup.action("clickup-create-task")

# Print to see all props
print(create_task)

# Step 1: Fetch workspaceId options
workspace_options = create_task.get_options_for_prop("workspaceId")
create_task.configure({"workspaceId": "12345"})

# Step 2: Fetch spaceId options
space_options = create_task.get_options_for_prop("spaceId")
create_task.configure({"spaceId": "222"})

# Step 3: Fetch listId options
list_options = create_task.get_options_for_prop("listId")
create_task.configure({"listId": "abc123"})

# Step 4: Configure other required props
create_task.configure({
    "name": "New task from Kafka",
    "description": "Task created via integration"
})

# Step 5: Run
result = create_task.run()
print(result)
```

### Example 2: Direct Configuration (when you know the values)

```python
from integrations import AppFactory

factory = AppFactory()
clickup = factory.app("clickup")
create_task = clickup.action("clickup-create-task")

# Skip all the intermediate props - just configure what you need!
create_task.configure({
    "listId": "abc123",  # You already know this
    "name": "New task from Kafka",
    "description": "Task created via integration"
})

# Run immediately
result = create_task.run()
print(result)
```

**When to use each approach:**

- **Wizard Flow**: User says "create a task" without specifying where
- **Direct Configuration**: User says "create a task in list abc123"

## 4) Direct Custom Actions (Proxy)

Use this when a prebuilt action doesn't cover your use case.

```python
from integrations import AppFactory

factory = AppFactory()

# Simple GET
files = factory.proxy_get(
    "google_drive",
    "https://www.googleapis.com/drive/v3/files?spaces=drive&pageSize=10"
)
print(files)

# POST example
resp = factory.proxy_post(
    "slack",
    "https://slack.com/api/chat.postMessage",
    body={"channel": "C123456", "text": "Hello from Kafka!"}
)
print(resp)

# Full control
resp = factory.custom_request(
    app_slug="google_drive",
    method="POST",
    url="https://www.googleapis.com/drive/v3/files",
    headers={"Content-Type": "application/json"},
    body={
        "name": "Kafka Docs",
        "mimeType": "application/vnd.google-apps.folder"
    }
)
print(resp)
```

## 5) Action Selection Rules

Only invoke actions that actually appear in `app.list_actions()`. Do not guess or fabricate action slugs.

```python
from integrations import AppFactory

factory = AppFactory()
app = factory.app("google_drive")

actions = app.list_actions(pretty_print=False)
available_slugs = {a.get("key") for a in actions}

desired_slug = "google_drive-some-missing-action"
if desired_slug not in available_slugs:
    # Use the authenticated proxy instead
    resp = factory.custom_request(
        app_slug="google_drive",
        method="POST",
        url="https://www.googleapis.com/drive/v3/some/endpoint",
        headers={"Content-Type": "application/json"},
        body={"example": True}
    )
else:
    action = app.action(desired_slug)
    action.configure({"example": True})
    resp = action.run()
```

### STRONG RULES TO AVOID HALLUCINATED ACTIONS

- ALWAYS validate the slug against `app.list_actions(pretty_print=False)` before calling `app.action(slug)`
- Prefer using `app.search_actions(query)` to discover likely slugs
- If no matching slug exists, DO NOT invent one. Use the proxy instead

## 6) File Uploads (Multipart/Form-Data)

Some APIs require file uploads using `multipart/form-data` (e.g., ClickUp attachments, Slack file uploads). The standard `custom_request()` method only supports JSON bodies, so use these dedicated upload methods instead:

### Upload Methods

```python
from integrations import AppFactory

factory = AppFactory()

# 1. Upload a local file from /workspace
result = factory.proxy_upload_file(
    app_slug="clickup",
    url="https://api.clickup.com/api/v2/task/abc123/attachment",
    file_path="/workspace/report.pdf",
    file_field_name="attachment"  # The form field name the API expects
)

# 2. Upload a file from a URL (proxy fetches and uploads it)
result = factory.proxy_upload_from_url(
    app_slug="clickup",
    url="https://api.clickup.com/api/v2/task/abc123/attachment",
    file_url="https://example.com/document.pdf",
    file_field_name="attachment",
    file_name="document.pdf"  # Optional: override the filename
)

# 3. Upload in-memory bytes (e.g., generated PDF, processed image)
pdf_bytes = generate_pdf_report()  # Returns bytes
result = factory.proxy_upload_bytes(
    app_slug="clickup",
    url="https://api.clickup.com/api/v2/task/abc123/attachment",
    file_bytes=pdf_bytes,
    file_name="generated_report.pdf",
    file_field_name="attachment",
    file_content_type="application/pdf"  # Optional: MIME type
)
```

### Parameters

All upload methods support these optional parameters:
- `file_content_type`: MIME type (auto-detected from filename if not provided)
- `form_fields`: Additional form fields as `Dict[str, str]`
- `headers`: Additional headers as `Dict[str, str]`
- `method`: HTTP method, default "POST"
- `account_id`: Explicit OAuth account ID (auto-resolved if not provided)

### Common Use Cases

**ClickUp task attachments:**
```python
result = factory.proxy_upload_file(
    app_slug="clickup",
    url=f"https://api.clickup.com/api/v2/task/{task_id}/attachment",
    file_path="/workspace/screenshot.png",
    file_field_name="attachment"
)
```

**Slack file uploads:**
```python
result = factory.proxy_upload_file(
    app_slug="slack",
    url="https://slack.com/api/files.upload",
    file_path="/workspace/data.csv",
    file_field_name="file",
    form_fields={"channels": "C123456", "title": "Data Export"}
)
```

### Limits
- Maximum file size: **25MB**
- Supported for any API that accepts `multipart/form-data`

## FAQs & Tips

- **I have to upload a file, how do I do it?** Use `factory.proxy_upload_file()` for local files, `factory.proxy_upload_from_url()` for URL-based files, or `factory.proxy_upload_bytes()` for in-memory data. See the "File Uploads" section above.
- **Do I have to configure everything at once?** No—call `configure(...)` multiple times; later calls override earlier ones
- **How do I know required vs optional props?** Print the action. Look for ❌ (required) vs ✅ (optional)
- **When should I use `get_options_for_prop`?** Use it when you need to discover what values are available. If you already know the exact ID/value, skip it and configure directly
- **How do I configure array fields?** Always use a list: `action.configure({"assignees": [value1, value2]})`
- **How do I use static options?** Use the EXACT value shown in the options list
- **What if configure() returns an error?** Check the error message - it will tell you which value is invalid
- **Understanding action.run() response structure:**

```python
result = action.run()
# Result structure:
# {
#   "ret": <return value>,        # Main result data
#   "exports": {                  # Named exports from the action
#     "$summary": "..."           # Human-readable summary
#   },
#   "os": [],                     # Observations/logs
#   "stash": {...}                # File stash info (if applicable)
# }

data = result.get("ret")
summary = result.get("exports", {}).get("$summary")
```
