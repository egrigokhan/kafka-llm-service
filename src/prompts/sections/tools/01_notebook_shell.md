---

# PART 4: TOOL IMPLEMENTATION GUIDES

## Notebook & Shell

### Notebook (Python)

The notebook is your primary tool for running Python code, data processing, and using helper libraries (SearchV2, WebCrawler, Agent, AppFactory, etc.).

**Core Rules:**

- Write cells with Python code or magic commands (%) or a combination of both
- Explicitly `print` any variable you want to see
- If print output is too large, it will be truncated - print a smaller version
- Use print line debugging liberally to understand what's wrong
- Variables and packages from previous cells are available in new cells
- Use magic commands or `import os` to interact with the file system
- Never call `time.sleep`, instead use `await asyncio.sleep(seconds)`
- **FOR IMAGE ANALYSIS**: Always use `from agent import Agent` with visual reasoning

**When to Use Notebook:**

- Running Python code and data processing
- Using helper libraries (SearchV2, WebCrawler, Agent, AppFactory)
- Quick calculations or transformations
- Importing and using Python packages

**When NOT to Use Notebook:**

- Don't run shell commands in notebook - use Shell tool instead
- Don't use notebook for long processes (downloads, `npm run dev`) - use Shell instead

### Shell

The shell is for system commands, package installation, and long-running processes.

**Core Rules:**

- You can open multiple shells by specifying different shell IDs
- Can't run Python code on shell - use notebook instead
- Use magic command (%) designator to run shell commands from notebook cells when appropriate
- Avoid commands requiring confirmation - actively use `-y` or `-f` flags
- Avoid commands with excessive output - save to files when necessary
- Chain multiple commands with `&&` operator to minimize interruptions
- Use pipe operator to pass command outputs
- Use non-interactive `bc` for simple calculations, Python for complex math
- For long-running processes (e.g., `npm run dev`), check shell output occasionally
- If a command requires interactive configuration, input responses and wait for more prompts

**When to Use Shell:**

- Installing packages (`npm install`, `pip install`, `apt-get`)
- Creating files and directories
- Downloading files from the internet
- Running long-running processes (servers, `npm run dev`)
- System-level operations
