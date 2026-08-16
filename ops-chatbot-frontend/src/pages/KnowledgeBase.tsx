import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface Cohort {
    cohort_id: string;
    name: string;
}

interface Material {
    material_id: string;
    source_id?: string;
    updated_at?: string;
    content_hash?: string;
    cohort?: string;
    [key: string]: unknown;
}

interface IngestionStats {
    sources_seen?: number;
    sources_ingested?: number;
    sources_skipped?: number;
    chunks_written?: number;
}

export default function KnowledgeBase() {
    const [cohorts, setCohorts] = useState<Cohort[]>([]);
    const [selectedCohort, setSelectedCohort] = useState("");
    const [onboarding, setOnboarding] = useState(false);
    const [onboardError, setOnboardError] = useState("");
    const [onboardStats, setOnboardStats] = useState<IngestionStats | null>(null);

    const [materials, setMaterials] = useState<Material[]>([]);
    const [materialsLoading, setMaterialsLoading] = useState(true);
    const [materialsError, setMaterialsError] = useState("");
    const [cohortFilter, setCohortFilter] = useState("All cohorts");

    const [viewMaterialId, setViewMaterialId] = useState("");
    const [viewedContent, setViewedContent] = useState<{ source_id: string; updated_at?: string; content: string } | null>(null);
    const [viewLoading, setViewLoading] = useState(false);

    const [retireMaterialId, setRetireMaterialId] = useState("");
    const [retiring, setRetiring] = useState(false);

    useEffect(() => {
        api.get("/kb/cohorts").then((res) => setCohorts(res.data.cohorts));
        loadMaterials();
    }, []);

    function loadMaterials() {
        setMaterialsLoading(true);
        api
            .get("/kb/materials")
            .then((res) => {
                const raw = res.data.materials as Material[];
                // Mirror the Streamlit transform: rename source_id -> material_id,
                // derive cohort from "{cohort}::{source}"
                const transformed = raw.map((m) => {
                    const material_id = m.source_id ?? m.material_id;
                    const cohort = String(material_id).split("::")[0];
                    return { ...m, material_id, cohort };
                });
                setMaterials(transformed);
            })
            .catch((err) => setMaterialsError(err.response?.data?.detail ?? "Couldn't load the knowledge base"))
            .finally(() => setMaterialsLoading(false));
    }

    async function handleOnboard() {
        if (!selectedCohort) return;
        setOnboarding(true);
        setOnboardError("");
        setOnboardStats(null);
        try {
            const res = await api.post(`/kb/cohorts/${selectedCohort}/onboard`);
            setOnboardStats(res.data);
        } catch (err: any) {
            // Important: onboarding failure must not hide the materials table below.
            setOnboardError(err.response?.data?.detail ?? `Couldn't ingest '${selectedCohort}'`);
        } finally {
            setOnboarding(false);
        }
    }

    async function handleRetire() {
        if (!retireMaterialId) return;
        setRetiring(true);
        try {
            await api.post(`/kb/retire/${encodeURIComponent(retireMaterialId)}`);
            loadMaterials();
            setRetireMaterialId("");
        } catch (err: any) {
            setMaterialsError(err.response?.data?.detail ?? "Couldn't retire material");
        } finally {
            setRetiring(false);
        }
    }

    async function handleViewContent() {
        if (!viewMaterialId) return;
        setViewLoading(true);
        try {
            const res = await api.get(`/kb/materials/${encodeURIComponent(viewMaterialId)}`);
            setViewedContent(res.data);
        } catch (err: any) {
            setViewedContent(null);
        } finally {
            setViewLoading(false);
        }
    }

    const cohortOptions = [
        "All cohorts",
        ...Array.from(new Set(materials.map((m) => m.cohort).filter(Boolean))),
    ] as string[];

    const filteredMaterials =
        cohortFilter === "All cohorts" ? materials : materials.filter((m) => m.cohort === cohortFilter);

    const materialIds = filteredMaterials.map((m) => m.material_id);

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Knowledge Base</p>
            <h1 className="text-2xl font-bold mb-1">Knowledge Base</h1>
            <p className="text-muted-foreground mb-6">Manage the knowledge sources used by the AI assistant.</p>

            {/* Cohort loader */}
            <Card className="p-4 mb-6">
                <h2 className="font-semibold mb-1">Load a Cohort</h2>
                <p className="text-sm text-muted-foreground mb-3">
                    Pick a cohort and its approved materials are loaded into the knowledge base automatically.
                </p>

                {cohorts.length === 0 ? (
                    <p className="text-yellow-700 text-sm">No enabled cohorts are available.</p>
                ) : (
                    <>
                        <select
                            className="w-full border rounded-md px-3 py-2 text-sm mb-2"
                            value={selectedCohort}
                            onChange={(e) => setSelectedCohort(e.target.value)}
                        >
                            <option value="">Select a cohort</option>
                            {cohorts.map((c) => (
                                <option key={c.cohort_id} value={c.cohort_id}>
                                    {c.cohort_id}
                                </option>
                            ))}
                        </select>
                        <p className="text-xs text-muted-foreground mb-3">
                            Selecting a cohort does not re-ingest it automatically. Use the button below only when you
                            want to ingest or re-index that cohort's approved files.
                        </p>
                        <Button onClick={handleOnboard} disabled={!selectedCohort || onboarding} className="w-full">
                            {onboarding ? "Loading..." : "Load / Re-index Selected Cohort"}
                        </Button>

                        {onboardError && <p className="text-red-600 text-sm mt-3">{onboardError}</p>}
                        {onboardStats && (
                            <div className="mt-3 text-sm bg-blue-50 border border-blue-200 rounded-md p-3">
                                <p>Sources Seen: <strong>{onboardStats.sources_seen ?? 0}</strong></p>
                                <p>Sources Ingested: <strong>{onboardStats.sources_ingested ?? 0}</strong></p>
                                <p>Sources Skipped: <strong>{onboardStats.sources_skipped ?? 0}</strong></p>
                                <p>Chunks Written: <strong>{onboardStats.chunks_written ?? 0}</strong></p>
                            </div>
                        )}
                    </>
                )}
            </Card>

            {/* Materials table */}
            <h2 className="font-semibold mb-2">Knowledge Base Materials</h2>

            {materialsLoading ? (
                <p>Loading materials...</p>
            ) : materialsError ? (
                <p className="text-red-600">{materialsError}</p>
            ) : materials.length === 0 ? (
                <p className="text-muted-foreground mb-6">
                    No materials have been ingested yet. Load one of the configured cohorts above.
                </p>
            ) : (
                <>
                    <select
                        className="border rounded-md px-3 py-2 text-sm mb-3"
                        value={cohortFilter}
                        onChange={(e) => setCohortFilter(e.target.value)}
                    >
                        {cohortOptions.map((c) => (
                            <option key={c} value={c}>{c}</option>
                        ))}
                    </select>

                    <div className="overflow-x-auto mb-6 border rounded-md">
                        <table className="w-full text-sm">
                            <thead className="bg-muted">
                                <tr>
                                    <th className="text-left p-2">material_id</th>
                                    <th className="text-left p-2">cohort</th>
                                    <th className="text-left p-2">updated_at</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredMaterials.map((m) => (
                                    <tr key={m.material_id} className="border-t">
                                        <td className="p-2">{m.material_id}</td>
                                        <td className="p-2">{m.cohort}</td>
                                        <td className="p-2">{m.updated_at}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {materialIds.length > 0 && (
                        <>
                            {/* View content */}
                            <h2 className="font-semibold mb-2">View Material Content</h2>
                            <div className="flex gap-2 mb-2">
                                <select
                                    className="flex-1 border rounded-md px-3 py-2 text-sm"
                                    value={viewMaterialId}
                                    onChange={(e) => setViewMaterialId(e.target.value)}
                                >
                                    <option value="">Select a material</option>
                                    {materialIds.map((id) => (
                                        <option key={id} value={id}>{id}</option>
                                    ))}
                                </select>
                                <Button variant="outline" onClick={handleViewContent} disabled={!viewMaterialId || viewLoading}>
                                    {viewLoading ? "Loading..." : "View Content"}
                                </Button>
                            </div>
                            {viewedContent && (
                                <div className="mb-6 border rounded-md p-3">
                                    <p className="text-sm">
                                        <strong>Source:</strong> <code>{viewedContent.source_id}</code>
                                    </p>
                                    {viewedContent.updated_at && (
                                        <p className="text-xs text-muted-foreground mb-2">Last updated: {viewedContent.updated_at}</p>
                                    )}
                                    <textarea
                                        className="w-full h-64 border rounded-md p-2 text-sm bg-muted"
                                        readOnly
                                        value={viewedContent.content ?? "(no content field returned)"}
                                    />
                                </div>
                            )}

                            {/* Retire */}
                            <h2 className="font-semibold mb-2">Retire Material</h2>
                            <p className="text-sm text-muted-foreground mb-2">
                                Retired materials will no longer be used when answering learners.
                            </p>
                            <div className="flex gap-2">
                                <select
                                    className="flex-1 border rounded-md px-3 py-2 text-sm"
                                    value={retireMaterialId}
                                    onChange={(e) => setRetireMaterialId(e.target.value)}
                                >
                                    <option value="">Select a material</option>
                                    {materialIds.map((id) => (
                                        <option key={id} value={id}>{id}</option>
                                    ))}
                                </select>
                                <Button
                                    variant="destructive"
                                    onClick={handleRetire}
                                    disabled={!retireMaterialId || retiring}
                                >
                                    {retiring ? "Retiring..." : "Retire"}
                                </Button>
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    );
}