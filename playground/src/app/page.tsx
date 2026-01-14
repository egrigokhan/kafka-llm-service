"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/components/auth-provider";
import { AuthForm } from "@/components/auth-form";
import { Sidebar } from "@/components/sidebar";

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
  const { user, loading: authLoading } = useAuth();
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
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
    if (selectedThreadId) {
      inputRef.current?.focus();
    }
  }, [selectedThreadId]);

  // Load thread messages when thread is selected
  useEffect(() => {
    if (selectedThreadId) {
      loadThread(selectedThreadId);
    } else {
      setMessages([]);
    }
  }, [selectedThreadId]);

  const loadThread = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/v1/threads/${id}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages || []);
      }
    } catch (error) {
      console.error("Failed to load thread:", error);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || isLoading || !selectedThreadId) return;

    const userMessage = input.trim();
    setInput("");

    const newUserMsg: Message = { role: "user", content: userMessage };
    const updatedMessages = [...messages, newUserMsg];
    setMessages(updatedMessages);
    setIsLoading(true);

    try {
      const endpoint = `${API_BASE}/v1/threads/${selectedThreadId}/agent/run`;
      const body = {
        model,
        messages: [newUserMsg].map((m) => ({
          role: m.role,
          content: m.content,
        })),
      };

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
      const accumulatedToolCalls: Record<
        number,
        { id: string; name: string; arguments: string }
      > = {};
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
                setMessages((prev) => {
                  const last = prev[prev.length - 1];
                  // Only remove empty assistant messages that have no content AND no tool_calls
                  // Don't remove if tool_calls exist (even if they're just "idle")
                  if (
                    last?.role === "assistant" &&
                    !last.content &&
                    (!last.tool_calls || last.tool_calls.length === 0)
                  ) {
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
                  const toolMsgIndex = prev.findIndex(
                    (m) => m.role === "tool" && m.tool_call_id === tool_call_id
                  );

                  if (toolMsgIndex >= 0) {
                    return prev.map((msg, i) =>
                      i === toolMsgIndex
                        ? { ...msg, content: (msg.content || "") + delta }
                        : msg
                    );
                  } else {
                    const withoutEmptyAssistant = prev.filter(
                      (m, i) =>
                        !(
                          i === prev.length - 1 &&
                          m.role === "assistant" &&
                          !m.content &&
                          !m.tool_calls
                        )
                    );

                    return [
                      ...withoutEmptyAssistant,
                      {
                        role: "tool" as const,
                        content: delta,
                        tool_call_id,
                        name: tool_name,
                      },
                      { role: "assistant" as const, content: "" },
                    ];
                  }
                });
                continue;
              }

              // Handle custom tool_messages event
              if (parsed.type === "tool_messages" && parsed.messages) {
                setMessages((prev) => {
                  const filtered = prev.filter(
                    (m, i) =>
                      !(
                        i === prev.length - 1 &&
                        m.role === "assistant" &&
                        !m.content
                      )
                  );
                  return [
                    ...filtered.filter(
                      (m) =>
                        !(
                          m.role === "tool" ||
                          (m.role === "assistant" && m.tool_calls)
                        )
                    ),
                    ...parsed.messages,
                    { role: "assistant", content: "" },
                  ];
                });
                continue;
              }

              // Handle OpenAI streaming chunks
              const choice = parsed.choices?.[0];
              if (choice?.delta) {
                const delta = choice.delta;
                const chunkId = parsed.id;

                if (chunkId && chunkId !== currentCompletionId) {
                  if (currentCompletionId !== null) {
                    streamContentRef.current = "";
                    Object.keys(accumulatedToolCalls).forEach((k) =>
                      delete accumulatedToolCalls[Number(k)]
                    );

                    setMessages((prev) => {
                      const last = prev[prev.length - 1];
                      if (
                        last?.role === "assistant" &&
                        (last.content || last.tool_calls)
                      ) {
                        return [
                          ...prev,
                          { role: "assistant" as const, content: "" },
                        ];
                      }
                      return prev;
                    });
                  }
                  currentCompletionId = chunkId;
                }

                if (delta.tool_calls) {
                  for (const tc of delta.tool_calls) {
                    const idx = tc.index ?? 0;
                    if (!accumulatedToolCalls[idx]) {
                      accumulatedToolCalls[idx] = { id: "", name: "", arguments: "" };
                    }
                    if (tc.id) accumulatedToolCalls[idx].id = tc.id;
                    if (tc.function?.name)
                      accumulatedToolCalls[idx].name = tc.function.name;
                    if (tc.function?.arguments)
                      accumulatedToolCalls[idx].arguments += tc.function.arguments;
                  }
                  
                  // Update message in real-time as tool_calls stream in
                  const toolCallsList = Object.values(accumulatedToolCalls).map(
                    (tc) => ({
                      id: tc.id,
                      type: "function" as const,
                      function: { name: tc.name, arguments: tc.arguments },
                    })
                  );
                  
                  setMessages((prev) => {
                    const lastIndex = prev.length - 1;
                    if (lastIndex >= 0 && prev[lastIndex].role === "assistant") {
                      return prev.map((msg, i) =>
                        i === lastIndex
                          ? {
                              ...msg,
                              tool_calls: toolCallsList,
                            }
                          : msg
                      );
                    }
                    return prev;
                  });
                }

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

                if (choice.finish_reason === "tool_calls") {
                  const toolCallsList = Object.values(accumulatedToolCalls).map(
                    (tc) => ({
                      id: tc.id,
                      type: "function" as const,
                      function: { name: tc.name, arguments: tc.arguments },
                    })
                  );

                  setMessages((prev) => {
                    const lastIndex = prev.length - 1;
                    if (lastIndex >= 0 && prev[lastIndex].role === "assistant") {
                      const current = prev[lastIndex];
                      return prev.map((msg, i) =>
                        i === lastIndex
                          ? {
                              ...msg,
                              content: current.content || null,
                              tool_calls: toolCallsList,
                            }
                          : msg
                      );
                    }
                    return prev;
                  });

                  streamContentRef.current = "";
                  Object.keys(accumulatedToolCalls).forEach((k) =>
                    delete accumulatedToolCalls[Number(k)]
                  );
                }
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }

      // Reload messages from DB
      await loadThread(selectedThreadId);
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

  // Show loading while checking auth
  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <span className="text-muted-foreground">loading...</span>
      </div>
    );
  }

  // Show auth form if not logged in
  if (!user) {
    return <AuthForm />;
  }

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <Sidebar
        selectedThreadId={selectedThreadId}
        onSelectThread={setSelectedThreadId}
      />

      {/* Main chat area */}
      <div className="flex-1 flex flex-col p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 pb-4 border-b border-border">
          <div className="space-y-1">
            <h1 className="text-lg font-medium tracking-tight">playground</h1>
            <p className="text-xs text-muted-foreground font-mono">
              {selectedThreadId
                ? `thread: ${selectedThreadId.slice(0, 8)}...`
                : "select or create a thread"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="model"
              className="w-32 h-8 text-xs font-mono bg-secondary border-0"
            />
          </div>
        </div>

        {/* Messages */}
        <Card className="flex-1 mb-4 bg-card border-border overflow-hidden">
          <ScrollArea className="h-full">
            <div className="p-4">
              {!selectedThreadId ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
                  select a thread from the sidebar or create a new one
                </div>
              ) : messages.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">
                  start a conversation
                </div>
              ) : (
                <div className="space-y-4">
                  {messages
                    .filter((msg) => !(msg.role === "tool" && msg.name === "idle"))
                    .map((msg, i) => (
                      <div key={i} className="space-y-1">
                        <div className="text-xs text-muted-foreground font-mono">
                          {msg.role}
                          {msg.name && (
                            <span className="ml-1 text-blue-400">
                              ({msg.name})
                            </span>
                          )}
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
                          {msg.content && <div>{msg.content}</div>}

                          {msg.tool_calls &&
                            msg.tool_calls.filter(
                              (tc) => tc.function.name !== "idle"
                            ).length > 0 && (
                              <div className="text-yellow-400/80 bg-yellow-950/20 p-2 rounded font-mono text-xs mt-2">
                                {msg.tool_calls
                                  .filter((tc) => tc.function.name !== "idle")
                                  .map((tc, j) => (
                                    <div key={j}>
                                      🔧 {tc.function.name}({tc.function.arguments})
                                    </div>
                                  ))}
                              </div>
                            )}

                          {!msg.content &&
                            (!msg.tool_calls || msg.tool_calls.length === 0) && (
                              <span className="opacity-50">thinking...</span>
                            )}
                          
                          {/* Show idle tool call if it's the only one */}
                          {msg.tool_calls &&
                            msg.tool_calls.length > 0 &&
                            msg.tool_calls.every((tc) => tc.function.name === "idle") &&
                            !msg.content && (
                              <span className="opacity-50">ready</span>
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
            placeholder={selectedThreadId ? "message" : "select a thread first"}
            disabled={isLoading || !selectedThreadId}
            className="flex-1 h-10 bg-card border-border"
          />
          <Button
            onClick={sendMessage}
            disabled={isLoading || !input.trim() || !selectedThreadId}
            className="h-10 px-6"
          >
            {isLoading ? "..." : "send"}
          </Button>
        </div>

        {/* Footer */}
        <div className="mt-4 text-center text-xs text-muted-foreground font-mono">
          {selectedThreadId
            ? `${API_BASE}/v1/threads/${selectedThreadId}/agent/run`
            : API_BASE}
        </div>
      </div>
    </div>
  );
}
