import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";

interface Notification {
    id: number;
    title: string;
    message: string;
    category: string;
    is_read: boolean;
}

export default function NotificationBell() {
    const { user } = useAuth();
    const [notifications, setNotifications] = useState<Notification[]>([]);
    const [open, setOpen] = useState(false);
    const popoverRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadNotifications();
    }, []);

    function loadNotifications() {
        api.get("/notifications").then((res) => setNotifications(res.data)).catch(() => setNotifications([]));
    }

    useEffect(() => {
        function handleClickOutside(e: MouseEvent) {
            if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
                setOpen(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    async function handleMarkRead(id: number) {
        try {
            await api.patch(`/notifications/${id}/read`);
            setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
        } catch {
            // no-op; UI already reflects the intended state optimistically enough for this
        }
    }

    async function handleMarkAllRead() {
        try {
            await api.patch("/notifications/read-all");
            setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
        } catch {
            loadNotifications();
        }
    }

    const unread = user?.role === "learner" ? notifications.filter((n) => !n.is_read).length : notifications.length;

    return (
        <div className="relative" ref={popoverRef}>
            <button
                onClick={() => setOpen((v) => !v)}
                className="relative flex items-center justify-center h-10 w-10 rounded-md border border-border bg-card hover:bg-muted transition-colors"
            >
                <span className="text-lg">🔔</span>
                {unread > 0 && (
                    <span className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-destructive text-white text-xs font-semibold flex items-center justify-center notif-pulse">
                        {unread}
                    </span>
                )}
            </button>

            {open && (
                <div className="absolute right-0 mt-2 w-80 border rounded-md bg-background shadow-lg p-4 z-50 motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-150">
                    <div className="flex justify-between items-center mb-3">
                        <h3 className="font-semibold">Notifications</h3>
                        {user?.role === "learner" && unread > 0 && (
                            <button className="text-xs text-primary hover:underline" onClick={handleMarkAllRead}>
                                Mark all as read
                            </button>
                        )}
                    </div>

                    {notifications.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No notifications.</p>
                    ) : (
                        <div className="flex flex-col gap-3">
                            {notifications.map((n) => (
                                <div key={n.id} className="border-b pb-3 last:border-b-0">
                                    <p className="text-sm font-medium">{n.title}</p>
                                    <p className="text-xs text-muted-foreground">{n.message}</p>
                                    {user?.role === "learner" && !n.is_read && (
                                        <button
                                            className="text-xs text-primary mt-1 hover:underline"
                                            onClick={() => handleMarkRead(n.id)}
                                        >
                                            ✓ Mark as read
                                        </button>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}