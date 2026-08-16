import { Link, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import {
    LayoutDashboard, MessageSquare, Ticket, BookOpen, Bell,
    BarChart3, Settings as SettingsIcon, FileText, Users, FolderOpen,
    LogOut,
    type LucideIcon,
} from "lucide-react";

interface NavItem {
    title: string;
    path: string;
    roles: string[];
    icon: LucideIcon;
}

const navItems: NavItem[] = [
    { title: "Dashboard", path: "/app/dashboard", roles: ["program_lead", "admin"], icon: LayoutDashboard },
    { title: "Chat Viewer", path: "/app/chat", roles: ["learner"], icon: MessageSquare },
    { title: "Escalations", path: "/app/escalations", roles: ["admin"], icon: Ticket },
    { title: "Knowledge Base", path: "/app/kb", roles: ["program_lead"], icon: BookOpen },
    { title: "Reminders", path: "/app/reminders", roles: ["learner"], icon: Bell },
    { title: "Analytics", path: "/app/analytics", roles: ["admin"], icon: BarChart3 },
    { title: "Settings", path: "/app/settings", roles: ["program_lead", "admin", "learner"], icon: SettingsIcon },
    { title: "Guide", path: "/app/guide", roles: ["admin"], icon: FileText },
    { title: "Users", path: "/app/users", roles: ["program_lead"], icon: Users },
    { title: "Cohorts", path: "/app/cohorts", roles: ["program_lead"], icon: FolderOpen },
];

const ROLE_ACCENT: Record<string, { dot: string; border: string; bg: string; text: string; avatar: string }> = {
    learner: { dot: "bg-blue-600", border: "border-blue-600", bg: "bg-blue-50", text: "text-blue-700", avatar: "bg-blue-600" },
    program_lead: { dot: "bg-violet-600", border: "border-violet-600", bg: "bg-violet-50", text: "text-violet-700", avatar: "bg-violet-600" },
    admin: { dot: "bg-amber-600", border: "border-amber-600", bg: "bg-amber-50", text: "text-amber-700", avatar: "bg-amber-600" },
};

export default function AppSidebar() {
    const { user, logout } = useAuth();
    const location = useLocation();
    const visibleItems = navItems.filter((item) => item.roles.includes(user?.role ?? ""));
    const accent = ROLE_ACCENT[user?.role ?? ""] ?? ROLE_ACCENT.learner;
    const initial = user?.username?.charAt(0).toUpperCase() ?? "?";

    return (
        <aside className="w-60 shrink-0 border-r h-screen flex flex-col p-4 bg-sidebar">
            <div className="flex items-center gap-2 mb-6 px-1 shrink-0">
                <span className={cn("h-2 w-2 rounded-full", accent.dot)} />
                <span className="font-bold text-lg tracking-tight">Ops Chatbot</span>
            </div>

            {user && (
                <div className="flex items-center gap-3 mb-6 px-1 py-2 rounded-md bg-muted/50 shrink-0">
                    <div className={cn("h-9 w-9 rounded-full flex items-center justify-center text-white font-semibold text-sm shrink-0", accent.avatar)}>
                        {initial}
                    </div>
                    <div className="min-w-0">
                        <p className="text-sm font-semibold truncate">{user.username}</p>
                        <p className={cn("text-xs font-medium uppercase tracking-wide", accent.text)}>
                            {user.role.replace("_", " ")}
                        </p>
                    </div>
                </div>
            )}

            <nav className="flex flex-col gap-1 flex-1 overflow-y-auto min-h-0">
                {visibleItems.map((item) => {
                    const active = location.pathname === item.path;
                    return (
                        <Link
                            key={item.path}
                            to={item.path}
                            className={cn(
                                "group flex items-center gap-2 px-3 py-2 rounded-md text-sm border-l-4 -ml-1 pl-4 transition-colors",
                                active
                                    ? cn(accent.border, accent.bg, accent.text, "font-medium")
                                    : "border-transparent text-muted-foreground hover:bg-muted/50"
                            )}
                        >
                            <item.icon className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                            {item.title}
                        </Link>
                    );
                })}
            </nav>

            <button
                onClick={logout}
                className="shrink-0 flex items-center gap-2 mt-4 px-3 py-2.5 rounded-md text-sm font-medium border border-border bg-card text-foreground hover:bg-muted transition-colors"
            >
                <LogOut className="h-4 w-4" />
                Log out
            </button>
        </aside>
    );
}