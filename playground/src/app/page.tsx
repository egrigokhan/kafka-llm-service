"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card } from "@/components/ui/card";

interface Message {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  tool_calls?: Array<{
    id: string;
    type: string;
    function: { name: string; arguments: string };
  }>;
  tool_call_id?: string;
  name?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ChatPlayground() {
  const [mode, setMode] = useState<"agent" | "thread" | "stateless">("agent");
  const [threadId, setThreadId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [model, setModel] = useState("gpt-4o");
  const scrollEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const streamContentRef = useRef<string>("");

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const createThread = async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      setThreadId(data.thread_id);
      setMessages([]);
    } catch (error) {
      console.error("Failed to create thread:", error);
    }
  };

  const loadThread = async (id: string, isRefresh = false) => {
    if (!id) return;
    try {
      const res = await fetch(`${API_BASE}/v1/threads/${id}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages || []);
        if (!isRefresh) {
          setThreadId(id);
        }
      }
    } catch (error) {
      console.error("Failed to load thread:", error);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    
    const newUserMsg: Message = { role: "user", content: userMessage };
    const updatedMessages = [...messages, newUserMsg];
    setMessages(updatedMessages);
    setIsLoading(true);

    let currentThreadId = threadId;
    
    try {
      let endpoint: string;
      let body: Record<string, unknown>;

      if (mode === "agent") {
        // Agent mode: send all messages to agent endpoint
        endpoint = `${API_BASE}/v1/agent/run`;
        body = {
          model,
          messages: updatedMessages.map((m) => {
            const msg: Record<string, unknown> = { role: m.role };
            if (m.content !== null) msg.content = m.content;
            if (m.tool_calls) msg.tool_calls = m.tool_calls;
            if (m.tool_call_id) msg.tool_call_id = m.tool_call_id;
            if (m.name) msg.name = m.name;
            return msg;
          }),
        };
      } else if (mode === "stateless") {
        // Stateless mode: send all messages to standard endpoint
        endpoint = `${API_BASE}/v1/chat/completions`;
        body = {
          model,
          messages: updatedMessages.map((m) => {
            const msg: Record<string, unknown> = { role: m.role };
            if (m.content !== null) msg.content = m.content;
            if (m.tool_calls) msg.tool_calls = m.tool_calls;
            if (m.tool_call_id) msg.tool_call_id = m.tool_call_id;
            if (m.name) msg.name = m.name;
            return msg;
          }),
          stream: true,
        };
      } else {
        // Thread mode: auto-create thread if needed, send only new message via agent/run
        if (!currentThreadId) {
          const res = await fetch(`${API_BASE}/v1/threads`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          });
          const data = await res.json();
          currentThreadId = data.thread_id;
          setThreadId(currentThreadId);
        }
        endpoint = `${API_BASE}/v1/threads/${currentThreadId}/agent/run`;
        body = {
          model,
          messages: [newUserMsg].map((m) => {
            const msg: Record<string, unknown> = { role: m.role };
            if (m.content !== null) msg.content = m.content;
            return msg;
          }),
        };
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      // Reset stream content ref and add empty assistant message for streaming
      streamContentRef.current = "";
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("No reader available");
      }

      let buffer = "";
      // Track accumulated tool calls by index for agent mode
      const accumulatedToolCalls: Record<number, { id: string; name: string; arguments: string }> = {};
      // Track current completion ID to detect new LLM responses
      let currentCompletionId: string | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") continue;

            try {
              const parsed = JSON.parse(data);
              
              // Handle agent_done event
              if (parsed.type === "agent_done") {
                // Remove empty streaming assistant message if present
                setMessages((prev) => {
                  const last = prev[prev.length - 1];
                  if (last?.role === "assistant" && !last.content && !last.tool_calls) {
                    return prev.slice(0, -1);
                  }
                  return prev;
                });
                continue;
              }
              
              // Handle streaming tool_result events
              if (parsed.type === "tool_result") {
                const { tool_call_id, tool_name, delta } = parsed;
                
                setMessages((prev) => {
                  // Find existing tool message
                  const toolMsgIndex = prev.findIndex(
                    (m) => m.role === "tool" && m.tool_call_id === tool_call_id
                  );
                  
                  if (toolMsgIndex >= 0) {
                    // Update existing tool message content
                    return prev.map((msg, i) =>
                      i === toolMsgIndex
                        ? { ...msg, content: (msg.content || "") + delta }
                        : msg
                    );
                  } else {
                    // Create new tool message - remove empty assistant, add tool msg
                    const withoutEmptyAssistant = prev.filter((m, i) => 
                      !(i === prev.length - 1 && m.role === "assistant" && !m.content && !m.tool_calls)
                    );
                    
                    return [
                      ...withoutEmptyAssistant,
                      {
                        role: "tool" as const,
                        content: delta,
                        tool_call_id,
                        name: tool_name
                      },
                      { role: "assistant" as const, content: "" }
                    ];
                  }
                });
                continue;
              }
              
              // Handle custom tool_messages event (complete tool messages)
              if (parsed.type === "tool_messages" && parsed.messages) {
                setMessages((prev) => {
                  const filtered = prev.filter((m, i) => 
                    !(i === prev.length - 1 && m.role === "assistant" && !m.content)
                  );
                  return [
                    ...filtered.filter(m => !(m.role === "tool" || (m.role === "assistant" && m.tool_calls))),
                    ...parsed.messages,
                    { role: "assistant", content: "" }
                  ];
                });
                continue;
              }
              
              // Handle OpenAI streaming chunks (content and tool_calls)
              const choice = parsed.choices?.[0];
              if (choice?.delta) {
                const delta = choice.delta;
                const chunkId = parsed.id;
                
                // Detect new completion (new LLM response in the loop)
                if (chunkId && chunkId !== currentCompletionId) {
                  // New completion started - if last assistant has content, start fresh
                  if (currentCompletionId !== null) {
                    // Reset accumulated state for new completion
                    streamContentRef.current = "";
                    Object.keys(accumulatedToolCalls).forEach(k => delete accumulatedToolCalls[Number(k)]);
                    
                    // Finalize the previous assistant and add new empty one
                    setMessages((prev) => {
                      const last = prev[prev.length - 1];
                      // Only add new assistant if last one has content or tool_calls
                      if (last?.role === "assistant" && (last.content || last.tool_calls)) {
                        return [...prev, { role: "assistant" as const, content: "" }];
                      }
                      return prev;
                    });
                  }
                  currentCompletionId = chunkId;
                }
                
                // Handle tool call deltas (streaming tool calls)
                if (delta.tool_calls) {
                  for (const tc of delta.tool_calls) {
                    const idx = tc.index ?? 0;
                    if (!accumulatedToolCalls[idx]) {
                      accumulatedToolCalls[idx] = { id: "", name: "", arguments: "" };
                    }
                    if (tc.id) accumulatedToolCalls[idx].id = tc.id;
                    if (tc.function?.name) accumulatedToolCalls[idx].name = tc.function.name;
                    if (tc.function?.arguments) accumulatedToolCalls[idx].arguments += tc.function.arguments;
                  }
                }
                
                // Handle content delta
                if (delta.content) {
                  streamContentRef.current += delta.content;
                  const newContent = streamContentRef.current;
                  setMessages((prev) => {
                    const lastIndex = prev.length - 1;
                    if (lastIndex >= 0 && prev[lastIndex].role === "assistant") {
                      return prev.map((msg, i) =>
                        i === lastIndex ? { ...msg, content: newContent } : msg
                      );
                    }
                    return prev;
                  });
                }
                
                // When finish_reason is tool_calls, update the current assistant message with tool_calls
                if (choice.finish_reason === "tool_calls") {
                  const toolCallsList = Object.values(accumulatedToolCalls).map((tc) => ({
                    id: tc.id,
                    type: "function" as const,
                    function: { name: tc.name, arguments: tc.arguments }
                  }));
                  
                  // Update the last assistant with tool_calls (keep existing content if any)
                  setMessages((prev) => {
                    const lastIndex = prev.length - 1;
                    if (lastIndex >= 0 && prev[lastIndex].role === "assistant") {
                      const current = prev[lastIndex];
                      return prev.map((msg, i) =>
                        i === lastIndex
                          ? { ...msg, content: current.content || null, tool_calls: toolCallsList }
                          : msg
                      );
                    }
                    return prev;
                  });
                  
                  // Reset for next iteration  
                  streamContentRef.current = "";
                  Object.keys(accumulatedToolCalls).forEach(k => delete accumulatedToolCalls[Number(k)]);
                }
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
      // In thread mode, reload messages from DB to get tool calls/results
      if (mode === "thread" && currentThreadId) {
        await loadThread(currentThreadId, true);
      }
    } catch (error) {
      console.error("Failed to send message:", error);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${error}` },
      ]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = () => {
    setMessages([]);
    setThreadId("");
  };

  const cycleMode = () => {
    setMode((prev) => {
      if (prev === "agent") return "thread";
      if (prev === "thread") return "stateless";
      return "agent";
    });
    setMessages([]);
    setThreadId("");
  };

  return (
    <div className="flex flex-col h-screen max-w-3xl mx-auto p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-border">
        <div className="space-y-1">
          <h1 className="text-lg font-medium tracking-tight">playground</h1>
          <p className="text-xs text-muted-foreground font-mono">
            {mode === "agent"
              ? "agent mode — loops until idle"
              : mode === "thread"
              ? threadId
                ? `thread: ${threadId.slice(0, 8)}...`
                : "no thread"
              : "stateless mode"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="model"
            className="w-32 h-8 text-xs font-mono bg-secondary border-0"
          />
          <Button
            variant={mode === "agent" ? "default" : mode === "thread" ? "secondary" : "outline"}
            size="sm"
            onClick={cycleMode}
            className="h-8 text-xs font-mono"
          >
            {mode}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={clearChat}
            className="h-8 text-xs text-muted-foreground"
          >
            clear
          </Button>
        </div>
      </div>

      {/* Thread controls - only show in thread mode */}
      {mode === "thread" && (
        <div className="flex gap-2 mb-4">
          <Input
            value={threadId}
            onChange={(e) => setThreadId(e.target.value)}
            placeholder="enter thread id or create new"
            className="flex-1 h-9 text-sm font-mono bg-card border-border"
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadThread(threadId)}
            disabled={!threadId}
            className="h-9"
          >
            load
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={createThread}
            className="h-9"
          >
            new
          </Button>
        </div>
      )}

      {/* Messages */}
      <Card className="flex-1 mb-4 bg-card border-border overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-4">
            {messages.length === 0 ? (
              <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
                {mode === "agent"
                  ? "agent — runs until idle is called"
                  : mode === "stateless"
                  ? "stateless — all messages sent each request"
                  : "start a conversation"}
              </div>
            ) : (
              <div className="space-y-4">
                {messages
                  .filter((msg) => !(msg.role === "tool" && msg.name === "idle"))
                  .map((msg, i) => (
                  <div key={i} className="space-y-1">
                    <div className="text-xs text-muted-foreground font-mono">
                      {msg.role}
                      {msg.name && <span className="ml-1 text-blue-400">({msg.name})</span>}
                    </div>
                    <div
                      className={`text-sm whitespace-pre-wrap ${
                        msg.role === "user"
                          ? "text-foreground"
                          : msg.role === "tool"
                          ? "text-green-400/80 bg-green-950/20 p-2 rounded font-mono text-xs"
                          : "text-muted-foreground"
                      }`}
                    >
                      {/* Show content if present */}
                      {msg.content && <div>{msg.content}</div>}
                      
                      {/* Show tool calls if present (hide idle calls) */}
                      {msg.tool_calls && msg.tool_calls.filter(tc => tc.function.name !== "idle").length > 0 && (
                        <div className="text-yellow-400/80 bg-yellow-950/20 p-2 rounded font-mono text-xs mt-2">
                          {msg.tool_calls
                            .filter(tc => tc.function.name !== "idle")
                            .map((tc, j) => (
                              <div key={j}>
                                🔧 {tc.function.name}({tc.function.arguments})
                              </div>
                            ))}
                        </div>
                      )}
                      
                      {/* Show thinking only if no content and no tool_calls */}
                      {!msg.content && (!msg.tool_calls || msg.tool_calls.length === 0) && (
                        <span className="opacity-50">thinking...</span>
                      )}
                    </div>
                  </div>
                ))}
                <div ref={scrollEndRef} />
              </div>
            )}
          </div>
        </ScrollArea>
      </Card>

      {/* Input */}
      <div className="flex gap-2">
        <Input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="message"
          disabled={isLoading}
          className="flex-1 h-10 bg-card border-border"
        />
        <Button
          onClick={sendMessage}
          disabled={isLoading || !input.trim()}
          className="h-10 px-6"
        >
          {isLoading ? "..." : "send"}
        </Button>
      </div>

      {/* Footer */}
      <div className="mt-4 text-center text-xs text-muted-foreground font-mono">
        {mode === "agent"
          ? `${API_BASE}/v1/agent/run`
          : mode === "thread"
          ? `${API_BASE}/v1/threads/<id>/agent/run`
          : `${API_BASE}/v1/chat/completions`}
      </div>
    </div>
  );
}
