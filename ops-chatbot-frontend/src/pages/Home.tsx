import { useAuth } from "@/context/AuthContext";
import { Link } from "react-router-dom";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
    LayoutDashboard,
    MessageSquare,
    Ticket,
    BookOpen,
    Bell,
    BarChart3,
    Settings as SettingsIcon,
    FileText,
    Users,
    FolderOpen,
    type LucideIcon,
} from "lucide-react";

interface NavItem {
    title: string;
    description: string;
    path: string;
    roles: string[];
    icon: LucideIcon;
}

const navItems: NavItem[] = [
    { title: "Dashboard", description: "Overview of key metrics", path: "/app/dashboard", roles: ["program_lead", "admin"], icon: LayoutDashboard },
    { title: "Chat Viewer", description: "Talk to the assistant", path: "/app/chat", roles: ["learner"], icon: MessageSquare },
    { title: "Escalations", description: "Conversations the assistant flagged for human follow-up.", path: "/app/escalations", roles: ["admin"], icon: Ticket },
    { title: "Knowledge Base", description: "Manage the knowledge sources used by the AI assistant.", path: "/app/knowlegebase", roles: ["program_lead"], icon: BookOpen },
    { title: "Reminders", description: "Your reminders.", path: "/app/reminders", roles: ["learner"], icon: Bell },
    { title: "Analytics", description: "Aggregate support metrics across all learners and programs.", path: "/app/analytics", roles: ["admin"], icon: BarChart3 },
    { title: "Settings", description: "Manage your account.", path: "/app/settings", roles: ["program_lead", "admin", "learner"], icon: SettingsIcon },
    { title: "Guide", description: "System administration and operational documentation.", path: "/app/guide", roles: ["admin"], icon: FileText },
    { title: "Users", description: "View learners and staff.", path: "/app/users", roles: ["program_lead"], icon: Users },
    { title: "Cohorts", description: "Manage learner cohorts and their materials.", path: "/app/cohorts", roles: ["program_lead"], icon: FolderOpen },
];

export default function Home() {
    const { user } = useAuth();
    const visibleItems = navItems.filter((item) => item.roles.includes(user?.role ?? ""));

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">Welcome, {user?.username}</h1>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {visibleItems.map((item) => (
                    <Link key={item.path} to={item.path}>
                        <Card className="hover:shadow-md hover:-translate-y-0.5 transition-all cursor-pointer">
                            <CardHeader>
                                <item.icon className="h-5 w-5 mb-2 text-muted-foreground" />
                                <CardTitle>{item.title}</CardTitle>
                                <CardDescription>{item.description}</CardDescription>
                            </CardHeader>
                        </Card>
                    </Link>
                ))}
            </div>
        </div>
    );
}