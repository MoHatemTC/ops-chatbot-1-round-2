import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface SupportVolumeRow {
    date: string;
    count: number;
}

interface ResolutionRow {
    estimated_resolution_seconds: number;
}

interface DashboardMetrics {
    support_volume?: SupportVolumeRow[];
    resolution_time?: ResolutionRow[];
    escalation_rate?: number;
}

export default function Analytics() {
    const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        api
            .get("/dashboards/metrics")
            .then((res) => setMetrics(res.data))
            .catch((err) => setError(err.response?.data?.detail ?? "Couldn't load analytics"))
            .finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="p-8">Loading analytics...</div>;
    if (error) return <div className="p-8 text-red-600">{error}</div>;

    const supportVolumeRows = metrics?.support_volume ?? [];
    const resolutionRows = metrics?.resolution_time ?? [];

    const supportVolume = supportVolumeRows.reduce((sum, row) => sum + (row.count ?? 0), 0);
    const escalationRate = (metrics?.escalation_rate ?? 0) * 100;
    const resolutionTimes = resolutionRows.map((r) => r.estimated_resolution_seconds ?? 0);
    const avgResolution =
        resolutionTimes.length > 0
            ? resolutionTimes.reduce((a, b) => a + b, 0) / resolutionTimes.length
            : 0;

    // sort by date, same as the Streamlit version
    const sortedRows = [...supportVolumeRows].sort(
        (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    );

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Insights</p>
            <h1 className="text-2xl font-bold">Analytics</h1>
            <p className="text-muted-foreground mb-6">
                Aggregate support metrics across all learners and programs.
            </p>

            <div className="grid grid-cols-3 gap-4 mb-8">
                <Card>
                    <CardHeader>
                        <CardDescription>📨 Support Volume</CardDescription>
                        <CardTitle className="text-2xl">{supportVolume}</CardTitle>
                    </CardHeader>
                </Card>
                <Card>
                    <CardHeader>
                        <CardDescription>🚨 Escalation Rate</CardDescription>
                        <CardTitle className="text-2xl">{escalationRate.toFixed(1)}%</CardTitle>
                    </CardHeader>
                </Card>
                <Card>
                    <CardHeader>
                        <CardDescription>⏱ Avg Resolution</CardDescription>
                        <CardTitle className="text-2xl">{(avgResolution / 60).toFixed(1)} min</CardTitle>
                    </CardHeader>
                </Card>
            </div>

            {sortedRows.length > 0 ? (
                <Card>
                    <CardHeader>
                        <CardTitle>Support Sessions per Day</CardTitle>
                    </CardHeader>
                    <div className="grid grid-cols-3 gap-4 p-6 pt-0">
                        <div className="col-span-2 h-80">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={sortedRows}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F2F2EF" />
                                    <XAxis dataKey="date" tickFormatter={(d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" })} />
                                    <YAxis />
                                    <Tooltip />
                                    <Bar dataKey="count" fill="#2A78D6" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                        <div className="overflow-y-auto h-80 border-l pl-4">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-left text-muted-foreground">
                                        <th className="pb-2">Date</th>
                                        <th className="pb-2">Sessions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {sortedRows.map((row) => (
                                        <tr key={row.date}>
                                            <td className="py-1">
                                                {new Date(row.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                                            </td>
                                            <td className="py-1">{row.count}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </Card>
            ) : (
                <p className="text-muted-foreground">No support activity found.</p>
            )}
        </div>
    );
}