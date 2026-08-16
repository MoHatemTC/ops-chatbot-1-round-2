import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import AtRiskTab from "@/components/AtRiskTab";

interface DashboardMetrics {
    support_volume?: { count: number }[];
    escalation_rate?: number;
    resolution_time?: unknown[];
}

interface Ticket {
    ticket_id: string;
    learner_name: string;
    reason: string;
    status: string;
}

export default function Dashboard() {
    const { user } = useAuth();
    const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
    const [demoMode, setDemoMode] = useState(false);
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [ticketsError, setTicketsError] = useState("");

    useEffect(() => {
        api
            .get("/dashboards/metrics")
            .then((res) => setMetrics(res.data))
            .catch(() => setDemoMode(true));

        api
            .get("/tickets")
            .then((res) => setTickets(res.data.tickets))
            .catch((err) => setTicketsError(err.response?.data?.detail ?? "Couldn't load tickets"));
    }, []);

    const totalSessions = metrics?.support_volume?.reduce((sum, r) => sum + (r.count ?? 0), 0) ?? 0;
    const escalationRate = ((metrics?.escalation_rate ?? 0) * 100).toFixed(0) + "%";
    const resolutionRecords = metrics?.resolution_time?.length ?? 0;

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Overview</p>
            <h1 className="text-2xl font-bold mb-1">📊 Dashboard</h1>
            <p className="text-muted-foreground mb-6">
                A daily snapshot of support volume, escalations, and at-risk learners.
            </p>

            {demoMode && (
                <p className="mb-4 text-sm bg-yellow-50 border border-yellow-200 rounded-md p-3">
                    ⚠️ Backend unavailable — showing demo data below.
                </p>
            )}

            <div className="grid grid-cols-4 gap-4 mb-8">
                <Card className="p-4">
                    <p className="text-sm text-muted-foreground">Sessions</p>
                    <p className="text-2xl font-bold">{demoMode ? 325 : totalSessions}</p>
                </Card>
                <Card className="p-4">
                    <p className="text-sm text-muted-foreground">Escalation Rate</p>
                    <p className="text-2xl font-bold">{demoMode ? "18%" : escalationRate}</p>
                </Card>
                <Card className="p-4">
                    <p className="text-sm text-muted-foreground">Resolution Records</p>
                    <p className="text-2xl font-bold">{demoMode ? 16 : resolutionRecords}</p>
                </Card>
                <Card className="p-4">
                    <p className="text-sm text-muted-foreground">Resolution Rate</p>
                    <p className="text-2xl font-bold">{demoMode ? "89%" : "N/A"}</p>
                </Card>
            </div>

            <Tabs defaultValue="tickets">
                <TabsList>
                    <TabsTrigger value="tickets">Tickets</TabsTrigger>
                    {(user?.role === "admin" || user?.role === "program_lead") && (
                        <TabsTrigger value="atrisk">At-Risk Nudges</TabsTrigger>
                    )}
                </TabsList>

                <TabsContent value="tickets">
                    <p className="text-sm text-muted-foreground mb-4">Latest escalations awaiting review</p>
                    {ticketsError ? (
                        <p className="text-red-600">{ticketsError}</p>
                    ) : tickets.length === 0 ? (
                        <p className="text-muted-foreground">No escalation tickets right now 🎉</p>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {tickets.slice(0, 5).map((t) => (
                                <div key={t.ticket_id} className="flex items-center gap-4 border-b py-2 text-sm">
                                    <code className="text-muted-foreground">#{t.ticket_id}</code>
                                    <span className="flex-1">{t.learner_name}</span>
                                    <Badge>{t.reason}</Badge>
                                    <Badge variant="outline">{t.status}</Badge>
                                </div>
                            ))}
                        </div>
                    )}
                </TabsContent>

                <TabsContent value="atrisk">
                    <AtRiskTab />
                </TabsContent>
            </Tabs>
        </div>
    );
}