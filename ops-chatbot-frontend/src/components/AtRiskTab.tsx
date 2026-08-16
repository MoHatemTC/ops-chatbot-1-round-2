import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";

interface Cohort {
    cohort_id: string;
    name: string;
}

interface AtRiskAggregate {
    run_date: string;
    total_learners: number;
    at_risk_count: number;
    at_risk_percent: number;
    missed_deadlines_count: number;
    inactive_count: number;
    low_progress_count: number;
    low_feedback_count: number;
}

const RISK_BANDS = { good: 10, warning: 25 };

function riskBand(pct: number) {
    if (pct < RISK_BANDS.good) return { label: "Low risk", color: "bg-green-100 text-green-800" };
    if (pct < RISK_BANDS.warning) return { label: "Elevated", color: "bg-yellow-100 text-yellow-800" };
    return { label: "High risk", color: "bg-red-100 text-red-800" };
}

export default function AtRiskTab() {
    const [cohorts, setCohorts] = useState<Cohort[]>([]);
    const [cohortId, setCohortId] = useState("");
    const [fromDate, setFromDate] = useState(() => {
        const d = new Date();
        d.setDate(d.getDate() - 13);
        return d.toISOString().slice(0, 10);
    });
    const [toDate, setToDate] = useState(() => new Date().toISOString().slice(0, 10));

    const [summary, setSummary] = useState<AtRiskAggregate | null>(null);
    const [summaryError, setSummaryError] = useState("");
    const [learnerIds, setLearnerIds] = useState<string[]>([]);
    const [learnersError, setLearnersError] = useState("");
    const [learnerSearch, setLearnerSearch] = useState("");
    const [trend, setTrend] = useState<AtRiskAggregate[]>([]);
    const [trendError, setTrendError] = useState("");

    useEffect(() => {
        api.get("/kb/cohorts", { params: { include_disabled: true } }).then((res) => {
            setCohorts(res.data.cohorts);
            if (res.data.cohorts.length > 0) {
                const demo = res.data.cohorts.find((c: Cohort) => c.cohort_id === "cohort_demo");
                setCohortId(demo ? demo.cohort_id : res.data.cohorts[0].cohort_id);
            }
        });
    }, []);

    useEffect(() => {
        if (!cohortId) return;
        if (fromDate > toDate) return;

        api
            .get("/atrisk/summary", { params: { cohort_id: cohortId, run_date: toDate } })
            .then((res) => { setSummary(res.data.aggregate); setSummaryError(""); })
            .catch((err) => setSummaryError(err.response?.data?.detail ?? "Couldn't load the at-risk summary"));

        api
            .get("/atrisk/learners", { params: { cohort_id: cohortId, run_date: toDate } })
            .then((res) => { setLearnerIds(res.data.learner_ids); setLearnersError(""); })
            .catch((err) => setLearnersError(err.response?.data?.detail ?? "Couldn't load learners"));

        api
            .get("/atrisk/trend", { params: { cohort_id: cohortId, start_date: fromDate, end_date: toDate } })
            .then((res) => { setTrend(res.data.trend); setTrendError(""); })
            .catch((err) => setTrendError(err.response?.data?.detail ?? "Couldn't load the trend"));
    }, [cohortId, fromDate, toDate]);

    if (fromDate > toDate) {
        return <p className="text-red-600">'From' date must be on or before 'To' date.</p>;
    }

    const band = summary ? riskBand(summary.at_risk_percent) : null;

    const reasonData = summary
        ? [
            { reason: "Missed deadlines", count: summary.missed_deadlines_count },
            { reason: "Inactivity", count: summary.inactive_count },
            { reason: "Low progress", count: summary.low_progress_count },
            { reason: "Low feedback", count: summary.low_feedback_count },
        ]
        : [];

    const filteredLearners = learnerSearch
        ? learnerIds.filter((id) => id.toLowerCase().includes(learnerSearch.toLowerCase()))
        : learnerIds;

    return (
        <div>
            <p className="text-sm text-muted-foreground mb-4">
                At-risk learners, why they're flagged, and how the count is trending.
            </p>

            <div className="grid grid-cols-3 gap-4 mb-6">
                <select className="border rounded-md px-3 py-2 text-sm" value={cohortId} onChange={(e) => setCohortId(e.target.value)}>
                    {cohorts.map((c) => (
                        <option key={c.cohort_id} value={c.cohort_id}>{c.name}</option>
                    ))}
                </select>
                <input type="date" className="border rounded-md px-3 py-2 text-sm" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
                <input type="date" className="border rounded-md px-3 py-2 text-sm" value={toDate} onChange={(e) => setToDate(e.target.value)} />
            </div>

            {summaryError && <p className="text-red-600 mb-4">{summaryError}</p>}

            {summary && (
                <div className="grid grid-cols-3 gap-4 mb-6">
                    <Card className="p-4">
                        <p className="text-sm text-muted-foreground">Total learners evaluated</p>
                        <p className="text-2xl font-bold">{summary.total_learners}</p>
                    </Card>
                    <Card className="p-4">
                        <p className="text-sm text-muted-foreground">At-risk learners</p>
                        <p className="text-2xl font-bold">{summary.at_risk_count}</p>
                        {band && <Badge className={band.color}>{band.label}</Badge>}
                    </Card>
                    <Card className="p-4">
                        <p className="text-sm text-muted-foreground">At-risk %</p>
                        <p className="text-2xl font-bold">{summary.at_risk_percent.toFixed(1)}%</p>
                        {band && <Badge className={band.color}>{band.label}</Badge>}
                    </Card>
                </div>
            )}

            <div className="grid grid-cols-2 gap-4 mb-6">
                <Card className="p-4">
                    <h3 className="font-semibold mb-3">Risk reasons breakdown</h3>
                    {!summary || summary.total_learners === 0 ? (
                        <p className="text-muted-foreground text-sm">No at-risk data for this date yet.</p>
                    ) : (
                        <div className="h-64">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={reasonData} layout="vertical" margin={{ left: 20 }}>
                                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                                    <XAxis type="number" />
                                    <YAxis type="category" dataKey="reason" width={110} />
                                    <Tooltip />
                                    <Bar dataKey="count" fill="#2A78D6" radius={[0, 4, 4, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    )}
                </Card>

                <Card className="p-4">
                    <h3 className="font-semibold mb-3">At-risk learners</h3>
                    {learnersError && <p className="text-red-600 text-sm">{learnersError}</p>}
                    {learnerIds.length === 0 && !learnersError ? (
                        <p className="text-muted-foreground text-sm">No at-risk learners for this date.</p>
                    ) : (
                        <>
                            <Input
                                placeholder="Filter learner ID"
                                value={learnerSearch}
                                onChange={(e) => setLearnerSearch(e.target.value)}
                                className="mb-2"
                            />
                            <p className="text-xs text-muted-foreground mb-2">
                                {filteredLearners.length} of {learnerIds.length} learners
                            </p>
                            <div className="h-52 overflow-y-auto border rounded-md">
                                <table className="w-full text-sm">
                                    <tbody>
                                        {filteredLearners.map((id) => (
                                            <tr key={id} className="border-t">
                                                <td className="p-2">{id}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    )}
                </Card>
            </div>

            <Card className="p-4">
                <h3 className="font-semibold mb-3">At-risk count over time</h3>
                {trendError && <p className="text-red-600 text-sm">{trendError}</p>}
                {trend.length === 0 && !trendError ? (
                    <p className="text-muted-foreground text-sm">No trend data for this window yet.</p>
                ) : (
                    <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={trend}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="run_date" tickFormatter={(d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" })} />
                                <YAxis />
                                <Tooltip />
                                <Line type="monotone" dataKey="at_risk_count" stroke="#2A78D6" strokeWidth={2} dot={{ r: 4 }} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                )}
            </Card>
        </div>
    );
}