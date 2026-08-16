import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface Cohort {
    cohort_id: string;
    name: string;
    description?: string;
    project?: string;
    start_date?: string;
    end_date?: string;
    enabled?: boolean;
    materials?: unknown[];
}

export default function Cohorts() {
    const [cohorts, setCohorts] = useState<Cohort[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [search, setSearch] = useState("");
    const [projectFilter, setProjectFilter] = useState("All");

    useEffect(() => {
        loadCohorts();
    }, []);

    function loadCohorts() {
        setLoading(true);
        api
            .get("/kb/cohorts", { params: { include_disabled: true } })
            .then((res) => setCohorts(res.data.cohorts))
            .catch((err) => setError(err.response?.data?.detail ?? "Couldn't load cohorts"))
            .finally(() => setLoading(false));
    }

    const projects = ["All", ...Array.from(new Set(cohorts.map((c) => c.project).filter(Boolean)))] as string[];

    const filtered = cohorts.filter((c) => {
        const matchesSearch = c.name.toLowerCase().includes(search.toLowerCase());
        const matchesProject = projectFilter === "All" || c.project === projectFilter;
        return matchesSearch && matchesProject;
    });

    if (loading) return <div className="p-8">Loading cohorts...</div>;
    if (error) return <div className="p-8 text-red-600">{error}</div>;

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Program Lead</p>
            <h1 className="text-2xl font-bold mb-1">Cohorts</h1>
            <p className="text-muted-foreground mb-6">Manage learner cohorts and their materials.</p>

            <div className="flex gap-4 mb-4 items-end">
                <div className="flex-1">
                    <Input
                        placeholder="Search by name..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                </div>
                <Button>➕ Create</Button>
            </div>

            <select
                className="mb-6 border rounded-md px-3 py-2 text-sm"
                value={projectFilter}
                onChange={(e) => setProjectFilter(e.target.value)}
            >
                {projects.map((p) => (
                    <option key={p} value={p}>
                        {p}
                    </option>
                ))}
            </select>

            {filtered.length === 0 ? (
                <p className="text-muted-foreground">No cohorts found.</p>
            ) : (
                <div className="flex flex-col gap-4">
                    {filtered.map((cohort) => (
                        <Card key={cohort.cohort_id} className="p-4">
                            <div className="flex justify-between items-start">
                                <h2 className="text-lg font-semibold">{cohort.name}</h2>
                                {cohort.enabled ? (
                                    <Badge className="bg-green-100 text-green-800">✅ Enabled</Badge>
                                ) : (
                                    <Badge className="bg-yellow-100 text-yellow-800">⏸️ Disabled</Badge>
                                )}
                            </div>
                            <p className="text-xs text-muted-foreground mb-2">ID: {cohort.cohort_id}</p>
                            {cohort.description && <p className="mb-2">{cohort.description}</p>}
                            <p className="text-sm text-muted-foreground">
                                {cohort.project && <>Project: {cohort.project} &nbsp;·&nbsp; </>}
                                {(cohort.start_date || cohort.end_date) && (
                                    <>Dates: {cohort.start_date ?? "?"} → {cohort.end_date ?? "?"} &nbsp;·&nbsp; </>
                                )}
                                Materials: {cohort.materials?.length ?? 0}
                            </p>
                            <div className="flex gap-2 mt-4 pt-4 border-t">
                                {cohort.enabled && <Button variant="outline" size="sm">📤 Upload Materials</Button>}
                                <Button variant="outline" size="sm">✏️ Edit</Button>
                                <Button variant="outline" size="sm">🗑️ Delete</Button>
                            </div>
                        </Card>
                    ))}
                </div>
            )}
        </div>
    );
}