# Thread-Based Chat Completions API

An OpenAI-compatible API server that manages conversation history server-side using threads.

## What is this?

Instead of sending the full message history on every request (like standard OpenAI), this server:

1. **Stores conversations in threads** - Messages are persisted in Supabase
2. **Thread ID in URL** - Each request specifies which thread to use
3. **Only send new messages** - The server retrieves history automatically
4. **Any LLM via Portkey** - Use OpenAI, Anthropic, or any other provider

```
Standard OpenAI:     POST /v1/chat/completions       (send ALL messages every time)
This server:         POST /v1/threads/{id}/chat/completions  (send only NEW message)
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up Supabase

Create these tables in your Supabase project:

```sql
-- Threads table
CREATE TABLE threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB
);

-- Messages table  
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID REFERENCES threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    name TEXT,
    tool_calls JSONB,
    tool_call_id TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB
);

-- Index for fast message retrieval by thread
CREATE INDEX idx_messages_thread_id ON messages(thread_id);
CREATE INDEX idx_messages_created_at ON messages(created_at);
```

### 3. Set up Portkey

1. Create account at [portkey.ai](https://portkey.ai)
2. Get your API key
3. Create a "Virtual Key" that maps to your LLM provider (e.g., OpenAI)

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 5. Run the server

```bash
python server.py
# or
uvicorn server:app --reload
```

## Usage

### With OpenAI Python Client

```python
from openai import OpenAI

# Point to your server with thread ID in the base URL
client = OpenAI(
    base_url="http://localhost:8000/v1/threads/my-thread-123",
    api_key="not-used-but-required"  # Server uses Portkey credentials
)

# Streaming
stream = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True
)

for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")

# Non-streaming
response = client.chat.completions.create(
    model="gpt-4", 
    messages=[{"role": "user", "content": "What did I just say?"}]
)
print(response.choices[0].message.content)
```

### With curl

```bash
# Create a thread
curl -X POST http://localhost:8000/v1/threads \
  -H "Content-Type: application/json" \
  -d '{"system_message": "You are a helpful assistant."}'

# Chat with streaming
curl -X POST http://localhost:8000/v1/threads/YOUR_THREAD_ID/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'

# Get thread history
curl http://localhost:8000/v1/threads/YOUR_THREAD_ID/messages
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/threads/{id}/chat/completions` | Chat completion (main endpoint) |
| GET | `/v1/threads/{id}/messages` | Get all messages in thread |
| POST | `/v1/threads/{id}/messages` | Add message without completion |
| POST | `/v1/threads` | Create new thread |
| DELETE | `/v1/threads/{id}/messages` | Clear thread messages |
| GET | `/v1/models` | List available models |
| GET | `/health` | Health check |

## Project Structure

```
├── server.py              # FastAPI server with OpenAI-compatible endpoints
├── src/
│   ├── llm/
│   │   ├── base.py        # Abstract LLMProvider class (documented)
│   │   └── portkey.py     # Portkey implementation
│   └── db/
│       └── supabase.py    # Thread/message storage
├── playground/            # Next.js test UI
│   └── src/app/page.tsx   # Chat interface
├── requirements.txt
├── .env.example
└── README.md
```

## Playground UI

A minimal monochrome Next.js UI is included for testing:

```bash
cd playground
cp .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 to test your API.

## Adding New LLM Providers

The `LLMProvider` base class makes it easy to add new providers:

```python
from src.llm.base import LLMProvider, Message, StreamChunk, CompletionResponse

class MyCustomProvider(LLMProvider):
    async def stream_completion(self, messages, **kwargs):
        # Your streaming implementation
        async for token in my_api.stream(messages):
            yield StreamChunk(delta=token)
    
    async def completion(self, messages, **kwargs):
        # Your non-streaming implementation
        result = await my_api.complete(messages)
        return CompletionResponse(content=result.text)
```

See `src/llm/base.py` for the full interface documentation.

## Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `PORTKEY_API_KEY` | Portkey API key | Required |
| `PORTKEY_VIRTUAL_KEY` | Virtual key for LLM provider | Required |
| `SUPABASE_URL` | Supabase project URL | Required |
| `SUPABASE_KEY` | Supabase API key | Required |
| `DEFAULT_MODEL` | Default model when not specified | `gpt-4` |
| `PORT` | Server port | `8000` |

## Why Threads?

**Traditional approach:**
- Client sends ALL messages every request
- Token costs scale with conversation length
- Client must manage conversation state

**Thread-based approach:**
- Client sends only NEW message(s)
- Server manages history efficiently
- Simpler client implementation
- Consistent conversation state across clients/sessions
