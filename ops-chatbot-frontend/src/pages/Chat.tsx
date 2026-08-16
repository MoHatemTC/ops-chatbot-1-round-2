import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface ChatSession {
    session_id: string;
    name?: string;
    token: { access_token: string };
}

interface ChatMessage {
    role: string;
    content: string;
}

const NUDGE_PHRASES = ["noticed things might be", "checking in", "just checking in"];

function looksLikeNudge(message: ChatMessage) {
    if (message.role !== "assistant") return false;
    const lower = message.content.toLowerCase();
    return NUDGE_PHRASES.some((phrase) => lower.includes(phrase));
}

function hideCitations(content: string) {
    if (!content) return "";
    let text = content.split(/\n\s*Sources:\s*\n/i)[0];
    text = text.replace(/\s*\[S\d+\]/g, "");
    return text.trim();
}

export default function Chat() {
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [sessionsError, setSessionsError] = useState("");
    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [activeSessionToken, setActiveSessionToken] = useState<string | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [messagesLoading, setMessagesLoading] = useState(false);
    const [input, setInput] = useState("");
    const [sending, setSending] = useState(false);
    const [composerError, setComposerError] = useState("");
    const [creatingSession, setCreatingSession] = useState(false);
    const transcriptRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadSessions();
    }, []);

    useEffect(() => {
        transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight });
    }, [messages]);

    async function loadSessions() {
        try {
            const res = await api.get("/auth/sessions");
            const list: ChatSession[] = res.data;
            setSessions(list);
            if (list.length > 0) {
                selectSession(list[0]);
            }
        } catch (err: any) {
            setSessionsError(err.response?.data?.detail ?? "Failed to load sessions.");
        }
    }

    async function selectSession(session: ChatSession) {
        setActiveSessionId(session.session_id);
        setActiveSessionToken(session.token.access_token);
        setComposerError("");
        setMessagesLoading(true);
        try {
            const res = await api.get("/chatbot/messages", {
                headers: { Authorization: `Bearer ${session.token.access_token}` },
            });
            setMessages(res.data.messages ?? []);
        } catch (err: any) {
            setMessages([]);
            setComposerError(err.response?.data?.detail ?? "Failed to load messages.");
        } finally {
            setMessagesLoading(false);
        }
    }

    async function handleNewChat() {
        setCreatingSession(true);
        setComposerError("");
        try {
            const res = await api.post("/auth/session");
            const session: ChatSession = res.data;
            setSessions((prev) => [session, ...prev]);
            setMessages([]);
            await selectSession(session);
        } catch (err: any) {
            setComposerError(err.response?.data?.detail ?? "Failed to start a new chat.");
        } finally {
            setCreatingSession(false);
        }
    }

    async function handleSend() {
        const text = input.trim();
        if (!text || !activeSessionToken) return;

        setSending(true);
        setComposerError("");

        // Optimistic user bubble + a placeholder "Thinking…" reply, replaced once
        // the real response comes back.
        setMessages((prev) => [...prev, { role: "user", content: text }, { role: "assistant", content: "Thinking…" }]);
        setInput("");

        try {
            const res = await api.post(
                "/chatbot/chat",
                { messages: [{ role: "user", content: text }] },
                { headers: { Authorization: `Bearer ${activeSessionToken}` } }
            );
            // Server returns the full canonical message list for the session.
            setMessages(res.data.messages ?? []);
        } catch (err: any) {
            // Drop the optimistic placeholder on failure.
            setMessages((prev) => prev.slice(0, -1));
            setComposerError(err.response?.data?.detail ?? "Failed to send message.");
        } finally {
            setSending(false);
        }
    }

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    }

    const activeSession = sessions.find((s) => s.session_id === activeSessionId);

    return (
        <div className="p-8 h-screen flex flex-col">
            <h1 className="text-2xl font-bold mb-1">💬 Chat Viewer</h1>
            <p className="text-muted-foreground mb-4 text-sm">
                Chat history for your account, including any at-risk nudges.
            </p>

            <div className="grid grid-cols-[280px_1fr] gap-4 flex-1 min-h-0">
                {/* Session list */}
                <div className="border rounded-md p-3 overflow-y-auto">
                    <div className="flex justify-between items-center mb-3">
                        <h2 className="text-sm font-semibold text-muted-foreground">Sessions</h2>
                        <Button size="sm" variant="outline" onClick={handleNewChat} disabled={creatingSession}>
                            + New chat
                        </Button>
                    </div>

                    {sessionsError && <p className="text-red-600 text-sm">{sessionsError}</p>}

                    {sessions.length === 0 && !sessionsError ? (
                        <p className="text-muted-foreground text-sm">No chat sessions yet.</p>
                    ) : (
                        <div className="flex flex-col gap-1">
                            {sessions.map((s) => (
                                <button
                                    key={s.session_id}
                                    onClick={() => selectSession(s)}
                                    className={`text-left text-sm rounded-md px-2 py-2 ${s.session_id === activeSessionId ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                                        }`}
                                >
                                    {s.name?.trim() || "Untitled session"}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Transcript */}
                <div className="border rounded-md flex flex-col min-h-0">
                    <div className="border-b px-4 py-3">
                        <h2 className="text-sm font-semibold">
                            {activeSession ? (activeSession.name?.trim() || "Untitled session") : "No session selected"}
                        </h2>
                    </div>

                    <div ref={transcriptRef} className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
                        {messagesLoading ? (
                            <p className="text-muted-foreground text-sm m-auto">Loading messages…</p>
                        ) : !activeSessionId ? (
                            <p className="text-muted-foreground text-sm m-auto">Pick a session on the left, or start a new chat.</p>
                        ) : messages.length === 0 ? (
                            <p className="text-muted-foreground text-sm m-auto">No messages in this session yet.</p>
                        ) : (
                            messages.map((m, i) => {
                                const isNudge = looksLikeNudge(m);
                                const isUser = m.role === "user";
                                return (
                                    <div key={i} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                                        <div className="max-w-[70%]">
                                            {isNudge && (
                                                <div className="text-xs font-bold bg-yellow-200 text-yellow-900 rounded-full px-2 py-0.5 inline-block mb-1">
                                                    ⚑ likely at-risk nudge
                                                </div>
                                            )}
                                            <div
                                                className={`rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap ${isUser
                                                        ? "bg-primary text-primary-foreground rounded-br-sm"
                                                        : isNudge
                                                            ? "bg-muted border-2 border-yellow-400 rounded-bl-sm"
                                                            : "bg-muted rounded-bl-sm"
                                                    }`}
                                            >
                                                {isUser ? m.content : hideCitations(m.content)}
                                            </div>
                                            <p className={`text-[10px] text-muted-foreground mt-1 ${isUser ? "text-right" : "text-left"}`}>
                                                {m.role}
                                            </p>
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    {composerError && <p className="text-red-600 text-xs px-4 pb-2">{composerError}</p>}

                    <div className="border-t p-3 flex gap-2 items-end">
                        <textarea
                            className="flex-1 border rounded-md px-3 py-2 text-sm resize-none"
                            rows={1}
                            placeholder="Type a message..."
                            value={input}
                            disabled={!activeSessionId || sending}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                        />
                        <Button onClick={handleSend} disabled={!activeSessionId || sending || !input.trim()}>
                            {sending ? "Sending..." : "Send"}
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
}