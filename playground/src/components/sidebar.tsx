"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAuth } from "./auth-provider";
import { createClient } from "@/lib/supabase";
import { ChevronDown, Plus, MessageSquare, LogOut } from "lucide-react";

interface KafkaProfile {
  id: string;
  name: string;
}

interface Thread {
  id: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

interface SidebarProps {
  selectedThreadId: string | null;
  onSelectThread: (threadId: string) => void;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function Sidebar({ selectedThreadId, onSelectThread }: SidebarProps) {
  const { user, signOut } = useAuth();
  const [kafkaProfiles, setKafkaProfiles] = useState<KafkaProfile[]>([]);
  const [selectedKafka, setSelectedKafka] = useState<KafkaProfile | null>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [showKafkaDropdown, setShowKafkaDropdown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creatingThread, setCreatingThread] = useState(false);

  const supabase = createClient();

  // Fetch kafka profiles for the user
  useEffect(() => {
    if (!user) return;

    const fetchKafkaProfiles = async () => {
      const { data, error } = await supabase
        .from("kafka_profiles")
        .select("id, name")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false });

      if (!error && data) {
        setKafkaProfiles(data);
        if (data.length > 0 && !selectedKafka) {
          setSelectedKafka(data[0]);
        }
      }
      setLoading(false);
    };

    fetchKafkaProfiles();
  }, [user]);

  // Fetch threads for selected kafka profile
  useEffect(() => {
    if (!selectedKafka) {
      setThreads([]);
      return;
    }

    const fetchThreads = async () => {
      const { data, error } = await supabase
        .from("threads")
        .select("id, created_at, metadata")
        .eq("kafka_profile_id", selectedKafka.id)
        .order("created_at", { ascending: false });

      if (!error && data) {
        setThreads(data);
      }
    };

    fetchThreads();
  }, [selectedKafka]);

  const handleSelectKafka = (profile: KafkaProfile) => {
    setSelectedKafka(profile);
    setShowKafkaDropdown(false);
  };

  const handleCreateThread = async () => {
    if (!user || !selectedKafka) return;
    
    setCreatingThread(true);
    try {
      const res = await fetch(`${API_BASE}/v1/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.id,
          kafka_profile_id: selectedKafka.id,
        }),
      });
      
      if (!res.ok) {
        throw new Error(`Failed to create thread: ${res.status}`);
      }
      
      const data = await res.json();
      if (data.thread_id) {
        // Add new thread to list and select it
        const newThread: Thread = {
          id: data.thread_id,
          created_at: data.created_at || new Date().toISOString(),
        };
        setThreads((prev) => [newThread, ...prev]);
        onSelectThread(data.thread_id);
      }
    } catch (error) {
      console.error("Failed to create thread:", error);
    } finally {
      setCreatingThread(false);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="w-64 h-full bg-card border-r border-border flex items-center justify-center">
        <span className="text-muted-foreground text-sm">loading...</span>
      </div>
    );
  }

  return (
    <div className="w-64 h-full bg-card border-r border-border flex flex-col">
      {/* User header */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground font-mono truncate max-w-[180px]">
            {user?.email}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={signOut}
          >
            <LogOut className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Kafka profile selector */}
      <div className="p-3 border-b border-border">
        <div className="relative">
          <Button
            variant="outline"
            className="w-full justify-between h-9 text-sm"
            onClick={() => setShowKafkaDropdown(!showKafkaDropdown)}
          >
            <span className="truncate">
              {selectedKafka?.name || "Select Kafka"}
            </span>
            <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>

          {showKafkaDropdown && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-lg z-10">
              {kafkaProfiles.length === 0 ? (
                <div className="p-2 text-sm text-muted-foreground text-center">
                  no kafka profiles
                </div>
              ) : (
                kafkaProfiles.map((profile) => (
                  <button
                    key={profile.id}
                    className="w-full px-3 py-2 text-sm text-left hover:bg-accent transition-colors"
                    onClick={() => handleSelectKafka(profile)}
                  >
                    {profile.name}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      {/* New thread button */}
      <div className="p-3">
        <Button
          variant="secondary"
          className="w-full h-9 text-sm"
          onClick={handleCreateThread}
          disabled={!selectedKafka || creatingThread}
        >
          <Plus className="h-4 w-4 mr-2" />
          {creatingThread ? "Creating..." : "New Thread"}
        </Button>
      </div>

      {/* Threads list */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {threads.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground py-8">
              no threads yet
            </div>
          ) : (
            threads.map((thread) => (
              <button
                key={thread.id}
                className={`w-full px-3 py-2 rounded-md text-left transition-colors ${
                  selectedThreadId === thread.id
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50"
                }`}
                onClick={() => onSelectThread(thread.id)}
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 shrink-0 opacity-50" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-mono truncate">
                      {thread.id.slice(0, 8)}...
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {formatDate(thread.created_at)}
                    </div>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </ScrollArea>

      {/* Selected kafka info */}
      {selectedKafka && (
        <div className="p-3 border-t border-border">
          <div className="text-xs text-muted-foreground font-mono">
            kafka: {selectedKafka.id.slice(0, 8)}...
          </div>
        </div>
      )}
    </div>
  );
}
