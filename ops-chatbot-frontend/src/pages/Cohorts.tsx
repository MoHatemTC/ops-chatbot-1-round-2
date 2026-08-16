import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

interface Material {
    id?: number;
    title?: string;
    source?: string;
    type?: string;
}

interface Cohort {
    cohort_id: string;
    name: string;
    description?: string;
    project?: string;
    start_date?: string;
    end_date?: string;
    enabled?: boolean;
    materials?: Material[];
}

interface CohortForm {
    cohort_id: string;
    name: string;
    description: string;
    project: string;
    start_date: string;
    end_date: string;
}

const MATERIAL_TYPES = {
    FAQ: "faq",
    Onboarding: "onboarding",
    Schedule: "schedule",
    "Program Doc": "program_doc",
} as const;

const ALLOWED_EXTENSIONS = [
    ".txt",
    ".md",
    ".markdown",
    ".json",
];

const MAX_FILE_SIZE = 25 * 1024 * 1024;

const EMPTY_FORM: CohortForm = {
    cohort_id: "",
    name: "",
    description: "",
    project: "",
    start_date: "",
    end_date: "",
};

function formatDate(value?: string) {
    if (!value) return "?";

    try {
        return new Date(value).toLocaleDateString();
    } catch {
        return value;
    }
}

function toInputDate(value?: string) {
    if (!value) return "";

    return value.substring(0, 10);
}

function addDays(dateString: string, days: number) {
    const date = new Date(`${dateString}T00:00:00`);
    date.setDate(date.getDate() + days);

    return date.toISOString().substring(0, 10);
}

function todayString() {
    return new Date().toISOString().substring(0, 10);
}

export default function Cohorts() {
    const { user } = useAuth();

    const [cohorts, setCohorts] = useState<Cohort[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    const [search, setSearch] = useState("");
    const [projectFilter, setProjectFilter] = useState("All");

    // ------------------------------------------------------------
    // CREATE / EDIT
    // ------------------------------------------------------------

    const [showCohortDialog, setShowCohortDialog] = useState(false);
    const [editingCohort, setEditingCohort] =
        useState<Cohort | null>(null);

    const [cohortForm, setCohortForm] =
        useState<CohortForm>(EMPTY_FORM);

    const [savingCohort, setSavingCohort] = useState(false);

    // ------------------------------------------------------------
    // DELETE
    // ------------------------------------------------------------

    const [deleteTarget, setDeleteTarget] =
        useState<Cohort | null>(null);

    const [deleting, setDeleting] = useState(false);

    // ------------------------------------------------------------
    // UPLOAD
    // ------------------------------------------------------------

    const [uploadTarget, setUploadTarget] =
        useState<Cohort | null>(null);

    const [showUploadDialog, setShowUploadDialog] =
        useState(false);

    const [materialTitle, setMaterialTitle] = useState("");

    const [materialType, setMaterialType] =
        useState<string>("faq");

    const [selectedFile, setSelectedFile] =
        useState<File | null>(null);

    const [uploading, setUploading] = useState(false);

    // ============================================================
    // LOAD COHORTS
    // ============================================================

    async function loadCohorts() {
        try {
            setLoading(true);
            setError("");

            const response = await api.get("/kb/cohorts", {
                params: {
                    include_disabled: true,
                },
            });

            const data = response.data;

            if (Array.isArray(data)) {
                setCohorts(data);
            } else if (Array.isArray(data?.cohorts)) {
                setCohorts(data.cohorts);
            } else {
                setCohorts([]);
            }
        } catch (err: any) {
            console.error(
                "Failed to load cohorts:",
                err
            );

            setError(
                err.response?.data?.detail ??
                "Couldn't load cohorts."
            );
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        loadCohorts();
    }, []);

    // ============================================================
    // EXPIRE OLD COHORTS
    // Same behavior as Streamlit
    // ============================================================

    async function syncExpiredCohorts(
        currentCohorts: Cohort[]
    ) {
        const today = todayString();

        const expired = currentCohorts.filter((cohort) => {
            if (!cohort.enabled) {
                return false;
            }

            if (!cohort.end_date) {
                return false;
            }

            return toInputDate(cohort.end_date) < today;
        });

        if (expired.length === 0) {
            return;
        }

        for (const cohort of expired) {
            try {
                await api.patch(
                    `/kb/cohorts/${cohort.cohort_id}`,
                    {
                        enabled: false,
                    }
                );
            } catch (err) {
                console.error(
                    `Failed to disable expired cohort ${cohort.cohort_id}`,
                    err
                );
            }
        }

        setCohorts((previous) =>
            previous.map((cohort) =>
                expired.some(
                    (item) =>
                        item.cohort_id ===
                        cohort.cohort_id
                )
                    ? {
                        ...cohort,
                        enabled: false,
                    }
                    : cohort
            )
        );
    }

    useEffect(() => {
        if (!loading && cohorts.length > 0) {
            syncExpiredCohorts(cohorts);
        }
    }, [loading]);

    // ============================================================
    // PROJECT FILTER
    // ============================================================

    const projects = useMemo(() => {
        const projectSet = new Set<string>();

        cohorts.forEach((cohort) => {
            if (cohort.project) {
                projectSet.add(cohort.project);
            }
        });

        return [
            "All",
            ...Array.from(projectSet).sort(),
        ];
    }, [cohorts]);

    // ============================================================
    // FILTERED COHORTS
    // ============================================================

    const filteredCohorts = useMemo(() => {
        const searchValue =
            search.trim().toLowerCase();

        return cohorts.filter((cohort) => {
            const matchesSearch =
                !searchValue ||
                cohort.name
                    .toLowerCase()
                    .includes(searchValue);

            const matchesProject =
                projectFilter === "All" ||
                cohort.project === projectFilter;

            return (
                matchesSearch &&
                matchesProject
            );
        });
    }, [
        cohorts,
        search,
        projectFilter,
    ]);

    // ============================================================
    // OPEN CREATE
    // ============================================================

    function openCreateDialog() {
        setError("");
        setEditingCohort(null);

        const today = todayString();

        setCohortForm({
            cohort_id: "",
            name: "",
            description: "",
            project: "",
            start_date: today,
            end_date: addDays(today, 3),
        });

        setShowCohortDialog(true);
    }

    // ============================================================
    // OPEN EDIT
    // ============================================================

    function openEditDialog(cohort: Cohort) {
        setError("");
        setEditingCohort(cohort);

        const start =
            toInputDate(cohort.start_date) ||
            todayString();

        const end =
            toInputDate(cohort.end_date) ||
            addDays(start, 3);

        setCohortForm({
            cohort_id: cohort.cohort_id,
            name: cohort.name ?? "",
            description:
                cohort.description ?? "",
            project: cohort.project ?? "",
            start_date: start,
            end_date: end,
        });

        setShowCohortDialog(true);
    }

    // ============================================================
    // FORM VALIDATION
    // ============================================================

    function validateCohortForm() {
        const errors: string[] = [];

        if (!cohortForm.cohort_id.trim()) {
            errors.push(
                "Cohort ID is required."
            );
        }

        if (!cohortForm.name.trim()) {
            errors.push(
                "Cohort Name is required."
            );
        }

        if (!cohortForm.start_date) {
            errors.push(
                "Start Date is required."
            );
        }

        if (!cohortForm.end_date) {
            errors.push(
                "End Date is required."
            );
        }

        if (
            cohortForm.start_date &&
            cohortForm.end_date
        ) {
            const start = new Date(
                `${cohortForm.start_date}T00:00:00`
            );

            const end = new Date(
                `${cohortForm.end_date}T00:00:00`
            );

            const today = new Date(
                `${todayString()}T00:00:00`
            );

            if (end < start) {
                errors.push(
                    "End Date cannot be before Start Date."
                );
            }

            const difference =
                Math.floor(
                    (end.getTime() -
                        start.getTime()) /
                    (1000 * 60 * 60 * 24)
                );

            if (difference < 3) {
                errors.push(
                    "Cohort period must be at least 3 days."
                );
            }

            if (!editingCohort && end < today) {
                errors.push(
                    "End Date cannot be before the cohort creation date."
                );
            }
        }

        return errors;
    }

    // ============================================================
    // CREATE / UPDATE
    // ============================================================

    async function handleSaveCohort(
        event: React.FormEvent
    ) {
        event.preventDefault();

        const validationErrors =
            validateCohortForm();

        if (validationErrors.length > 0) {
            setError(
                validationErrors.join(" ")
            );
            return;
        }

        try {
            setSavingCohort(true);
            setError("");

            const today = todayString();

            const enabled =
                cohortForm.end_date >= today;

            const payload = {
                cohort_id:
                    cohortForm.cohort_id.trim(),
                name:
                    cohortForm.name.trim(),
                description:
                    cohortForm.description.trim() ||
                    null,
                project:
                    cohortForm.project.trim() ||
                    null,
                start_date:
                    cohortForm.start_date,
                end_date:
                    cohortForm.end_date,
                enabled,
            };

            if (editingCohort) {
                await api.patch(
                    `/kb/cohorts/${editingCohort.cohort_id}`,
                    {
                        name: payload.name,
                        description:
                            payload.description,
                        project:
                            payload.project,
                        start_date:
                            payload.start_date,
                        end_date:
                            payload.end_date,
                        enabled:
                            payload.enabled,
                    }
                );
            } else {
                await api.post(
                    "/kb/cohorts",
                    payload
                );
            }

            setShowCohortDialog(false);
            setEditingCohort(null);
            setCohortForm(EMPTY_FORM);

            await loadCohorts();
        } catch (err: any) {
            console.error(
                "Failed to save cohort:",
                err
            );

            setError(
                err.response?.data?.detail ??
                "Couldn't save cohort."
            );
        } finally {
            setSavingCohort(false);
        }
    }

    // ============================================================
    // DELETE
    // ============================================================

    function openDeleteDialog(
        cohort: Cohort
    ) {
        setDeleteTarget(cohort);
        setError("");
    }

    async function handleDelete() {
        if (!deleteTarget) {
            return;
        }

        try {
            setDeleting(true);
            setError("");

            await api.delete(
                `/kb/cohorts/${deleteTarget.cohort_id}`
            );

            setCohorts((previous) =>
                previous.filter(
                    (cohort) =>
                        cohort.cohort_id !==
                        deleteTarget.cohort_id
                )
            );

            setDeleteTarget(null);
        } catch (err: any) {
            console.error(
                "Failed to delete cohort:",
                err
            );

            setError(
                err.response?.data?.detail ??
                "Couldn't delete cohort."
            );
        } finally {
            setDeleting(false);
        }
    }

    // ============================================================
    // OPEN UPLOAD
    // ============================================================

    function openUploadDialog(
        cohort: Cohort
    ) {
        setUploadTarget(cohort);
        setMaterialTitle("");
        setMaterialType("faq");
        setSelectedFile(null);
        setError("");
        setShowUploadDialog(true);
    }

    // ============================================================
    // FILE VALIDATION
    // ============================================================

    function validateFile(file: File) {
        const errors: string[] = [];

        const extension =
            "." +
            file.name
                .split(".")
                .pop()
                ?.toLowerCase();

        if (
            !ALLOWED_EXTENSIONS.includes(
                extension
            )
        ) {
            errors.push(
                `Unsupported file type '${extension}'. Only .txt, .md, .markdown and .json files are allowed.`
            );
        }

        if (file.size > MAX_FILE_SIZE) {
            errors.push(
                "File exceeds the 25 MB upload limit."
            );
        }

        return errors;
    }

    function handleFileChange(
        event: React.ChangeEvent<HTMLInputElement>
    ) {
        const file =
            event.target.files?.[0] ?? null;

        setError("");

        if (!file) {
            setSelectedFile(null);
            return;
        }

        const errors =
            validateFile(file);

        if (errors.length > 0) {
            setError(
                errors.join(" ")
            );
            setSelectedFile(null);

            event.target.value = "";
            return;
        }

        setSelectedFile(file);
    }

    // ============================================================
    // UPLOAD MATERIAL
    // ============================================================

    async function handleUpload(
        event: React.FormEvent
    ) {
        event.preventDefault();

        if (!uploadTarget) {
            setError(
                "No cohort selected."
            );
            return;
        }

        const errors: string[] = [];

        if (!materialTitle.trim()) {
            errors.push(
                "Material Title is required."
            );
        }

        if (!selectedFile) {
            errors.push(
                "Please choose a file to upload."
            );
        }

        if (selectedFile) {
            errors.push(
                ...validateFile(
                    selectedFile
                )
            );
        }

        if (errors.length > 0) {
            setError(
                errors.join(" ")
            );
            return;
        }

        try {
            setUploading(true);
            setError("");

            const formData =
                new FormData();

            formData.append(
                "title",
                materialTitle.trim()
            );

            formData.append(
                "material_type",
                materialType
            );

            formData.append(
                "file",
                selectedFile!
            );

            await api.post(
                `/kb/cohorts/${uploadTarget.cohort_id}/materials`,
                formData,
                {
                    headers: {
                        "Content-Type":
                            "multipart/form-data",
                    },
                }
            );

            setShowUploadDialog(false);
            setUploadTarget(null);
            setSelectedFile(null);
            setMaterialTitle("");

            await loadCohorts();
        } catch (err: any) {
            console.error(
                "Failed to upload material:",
                err
            );

            setError(
                err.response?.data?.detail ??
                "Couldn't upload material."
            );
        } finally {
            setUploading(false);
        }
    }

    // ============================================================
    // LOADING
    // ============================================================

    if (loading) {
        return (
            <div className="p-8">
                <p className="text-muted-foreground">
                    Loading cohorts...
                </p>
            </div>
        );
    }

    // ============================================================
    // PAGE
    // ============================================================

    return (
        <div className="p-8">
            {/* HEADER */}

            <div className="flex items-start justify-between gap-4 mb-6">
                <div>
                    <p className="text-sm text-muted-foreground">
                        Program Lead
                    </p>

                    <h1 className="text-2xl font-bold mb-1">
                        Cohorts
                    </h1>

                    <p className="text-muted-foreground">
                        Manage learner cohorts and
                        their materials.
                    </p>
                </div>

                <Button
                    onClick={
                        openCreateDialog
                    }
                >
                    ➕ Create
                </Button>
            </div>

            {/* ERROR */}

            {error && (
                <div className="mb-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex justify-between gap-4">
                    <span>{error}</span>

                    <button
                        type="button"
                        className="font-medium hover:underline"
                        onClick={() =>
                            setError("")
                        }
                    >
                        Dismiss
                    </button>
                </div>
            )}

            {/* SEARCH + FILTER */}

            <div className="flex flex-col md:flex-row gap-4 mb-6">
                <div className="flex-1">
                    <Input
                        placeholder="Search by name..."
                        value={search}
                        onChange={(event) =>
                            setSearch(
                                event.target.value
                            )
                        }
                    />
                </div>

                <select
                    className="border rounded-md px-3 py-2 text-sm bg-background"
                    value={
                        projectFilter
                    }
                    onChange={(event) =>
                        setProjectFilter(
                            event.target.value
                        )
                    }
                >
                    {projects.map(
                        (project) => (
                            <option
                                key={project}
                                value={project}
                            >
                                {project}
                            </option>
                        )
                    )}
                </select>

                <Button
                    variant="outline"
                    onClick={
                        loadCohorts
                    }
                >
                    ↻ Refresh
                </Button>
            </div>

            {/* EMPTY STATE */}

            {filteredCohorts.length ===
                0 ? (
                <Card className="p-8 text-center">
                    <p className="text-muted-foreground mb-4">
                        No cohorts found.
                    </p>

                    {cohorts.length ===
                        0 && (
                            <Button
                                onClick={
                                    openCreateDialog
                                }
                            >
                                ➕ Create Cohort
                            </Button>
                        )}
                </Card>
            ) : (
                <div className="flex flex-col gap-4">
                    {filteredCohorts.map(
                        (cohort) => {
                            const isEnabled =
                                Boolean(
                                    cohort.enabled
                                );

                            return (
                                <Card
                                    key={
                                        cohort.cohort_id
                                    }
                                    className="p-5"
                                >
                                    {/* TITLE + STATUS */}

                                    <div className="flex justify-between items-start gap-4">
                                        <div>
                                            <h2 className="text-lg font-semibold">
                                                {
                                                    cohort.name
                                                }
                                            </h2>

                                            <p className="text-xs text-muted-foreground">
                                                ID:{" "}
                                                {
                                                    cohort.cohort_id
                                                }
                                            </p>
                                        </div>

                                        {isEnabled ? (
                                            <Badge className="bg-green-100 text-green-800">
                                                ✅ Enabled
                                            </Badge>
                                        ) : (
                                            <Badge className="bg-yellow-100 text-yellow-800">
                                                ⏸️ Disabled
                                            </Badge>
                                        )}
                                    </div>

                                    {/* DESCRIPTION */}

                                    {cohort.description && (
                                        <p className="mt-3">
                                            {
                                                cohort.description
                                            }
                                        </p>
                                    )}

                                    {/* METADATA */}

                                    <div className="mt-3 text-sm text-muted-foreground">
                                        {cohort.project && (
                                            <span>
                                                <strong>
                                                    Project:
                                                </strong>{" "}
                                                {
                                                    cohort.project
                                                }
                                                {" · "}
                                            </span>
                                        )}

                                        {(cohort.start_date ||
                                            cohort.end_date) && (
                                                <span>
                                                    <strong>
                                                        Dates:
                                                    </strong>{" "}
                                                    {formatDate(
                                                        cohort.start_date
                                                    )}{" "}
                                                    →{" "}
                                                    {formatDate(
                                                        cohort.end_date
                                                    )}
                                                    {" · "}
                                                </span>
                                            )}

                                        <span>
                                            <strong>
                                                Materials:
                                            </strong>{" "}
                                            {
                                                cohort
                                                    .materials
                                                    ?.length ??
                                                0
                                            }
                                        </span>
                                    </div>

                                    {/* MATERIALS */}

                                    {cohort.materials &&
                                        cohort.materials
                                            .length >
                                        0 && (
                                            <div className="mt-4 border-t pt-4">
                                                <p className="text-sm font-medium mb-2">
                                                    Materials
                                                </p>

                                                <div className="flex flex-col gap-2">
                                                    {cohort.materials.map(
                                                        (
                                                            material,
                                                            index
                                                        ) => (
                                                            <div
                                                                key={
                                                                    material.id ??
                                                                    index
                                                                }
                                                                className="flex items-center justify-between text-sm"
                                                            >
                                                                <span className="text-muted-foreground">
                                                                    📄{" "}
                                                                    {material.title ??
                                                                        material.source ??
                                                                        `Material ${index +
                                                                        1
                                                                        }`}
                                                                </span>

                                                                {material.type && (
                                                                    <Badge variant="outline">
                                                                        {
                                                                            material.type
                                                                        }
                                                                    </Badge>
                                                                )}
                                                            </div>
                                                        )
                                                    )}
                                                </div>
                                            </div>
                                        )}

                                    {/* ACTIONS */}

                                    <div className="flex gap-2 mt-4 pt-4 border-t">
                                        {isEnabled && (
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() =>
                                                    openUploadDialog(
                                                        cohort
                                                    )
                                                }
                                            >
                                                📤 Upload Materials
                                            </Button>
                                        )}

                                        <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={() =>
                                                openEditDialog(
                                                    cohort
                                                )
                                            }
                                        >
                                            ✏️ Edit
                                        </Button>

                                        <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={() =>
                                                openDeleteDialog(
                                                    cohort
                                                )
                                            }
                                        >
                                            🗑️ Delete
                                        </Button>
                                    </div>
                                </Card>
                            );
                        }
                    )}
                </div>
            )}

            {/* ====================================================
                CREATE / EDIT DIALOG
            ==================================================== */}

            {showCohortDialog && (
                <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
                    <div className="w-full max-w-2xl rounded-xl bg-background border shadow-xl">
                        <div className="p-6 border-b">
                            <h2 className="text-xl font-semibold">
                                {editingCohort
                                    ? "Edit Cohort"
                                    : "Create Cohort"}
                            </h2>

                            <p className="text-sm text-muted-foreground mt-1">
                                {editingCohort
                                    ? `Edit · ${editingCohort.name}`
                                    : "New Cohort"}
                            </p>
                        </div>

                        <form
                            onSubmit={
                                handleSaveCohort
                            }
                            className="p-6 flex flex-col gap-4"
                        >
                            {/* COHORT ID */}

                            <div>
                                <label className="text-sm font-medium block mb-1">
                                    Cohort ID*
                                </label>

                                <Input
                                    value={
                                        cohortForm.cohort_id
                                    }
                                    disabled={
                                        Boolean(
                                            editingCohort
                                        )
                                    }
                                    onChange={(
                                        event
                                    ) =>
                                        setCohortForm(
                                            (
                                                previous
                                            ) => ({
                                                ...previous,
                                                cohort_id:
                                                    event
                                                        .target
                                                        .value,
                                            })
                                        )
                                    }
                                    placeholder="e.g. cohort-2026-01"
                                />
                            </div>

                            {/* NAME */}

                            <div>
                                <label className="text-sm font-medium block mb-1">
                                    Cohort Name*
                                </label>

                                <Input
                                    value={
                                        cohortForm.name
                                    }
                                    onChange={(
                                        event
                                    ) =>
                                        setCohortForm(
                                            (
                                                previous
                                            ) => ({
                                                ...previous,
                                                name: event
                                                    .target
                                                    .value,
                                            })
                                        )
                                    }
                                    placeholder="Cohort name"
                                />
                            </div>

                            {/* DESCRIPTION */}

                            <div>
                                <label className="text-sm font-medium block mb-1">
                                    Description
                                </label>

                                <textarea
                                    className="w-full min-h-28 rounded-md border bg-background px-3 py-2 text-sm"
                                    value={
                                        cohortForm.description
                                    }
                                    onChange={(
                                        event
                                    ) =>
                                        setCohortForm(
                                            (
                                                previous
                                            ) => ({
                                                ...previous,
                                                description:
                                                    event
                                                        .target
                                                        .value,
                                            })
                                        )
                                    }
                                    placeholder="Describe this cohort..."
                                />
                            </div>

                            {/* PROJECT */}

                            <div>
                                <label className="text-sm font-medium block mb-1">
                                    Project Name
                                </label>

                                <Input
                                    value={
                                        cohortForm.project
                                    }
                                    onChange={(
                                        event
                                    ) =>
                                        setCohortForm(
                                            (
                                                previous
                                            ) => ({
                                                ...previous,
                                                project:
                                                    event
                                                        .target
                                                        .value,
                                            })
                                        )
                                    }
                                    placeholder="Project name"
                                />
                            </div>

                            {/* DATES */}

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="text-sm font-medium block mb-1">
                                        Start Date
                                    </label>

                                    <Input
                                        type="date"
                                        value={
                                            cohortForm.start_date
                                        }
                                        onChange={(
                                            event
                                        ) =>
                                            setCohortForm(
                                                (
                                                    previous
                                                ) => ({
                                                    ...previous,
                                                    start_date:
                                                        event
                                                            .target
                                                            .value,
                                                })
                                            )
                                        }
                                    />
                                </div>

                                <div>
                                    <label className="text-sm font-medium block mb-1">
                                        End Date
                                    </label>

                                    <Input
                                        type="date"
                                        value={
                                            cohortForm.end_date
                                        }
                                        min={
                                            cohortForm.start_date
                                                ? addDays(
                                                    cohortForm.start_date,
                                                    3
                                                )
                                                : undefined
                                        }
                                        onChange={(
                                            event
                                        ) =>
                                            setCohortForm(
                                                (
                                                    previous
                                                ) => ({
                                                    ...previous,
                                                    end_date:
                                                        event
                                                            .target
                                                            .value,
                                                })
                                            )
                                        }
                                    />

                                    <p className="text-xs text-muted-foreground mt-1">
                                        Cohort period must
                                        be at least 3 days.
                                    </p>
                                </div>
                            </div>

                            {/* DATE VALIDATION */}

                            {cohortForm.start_date &&
                                cohortForm.end_date &&
                                new Date(
                                    cohortForm.end_date
                                ) <
                                new Date(
                                    cohortForm.start_date
                                ) && (
                                    <p className="text-sm text-red-600">
                                        End Date cannot
                                        be before Start
                                        Date.
                                    </p>
                                )}

                            {cohortForm.start_date &&
                                cohortForm.end_date &&
                                (new Date(
                                    cohortForm.end_date
                                ).getTime() -
                                    new Date(
                                        cohortForm.start_date
                                    ).getTime()) /
                                (1000 *
                                    60 *
                                    60 *
                                    24) <
                                3 && (
                                    <p className="text-sm text-red-600">
                                        Cohort period must
                                        be at least 3 days.
                                    </p>
                                )}

                            {/* BUTTONS */}

                            <div className="flex justify-end gap-3 pt-4 border-t">
                                <Button
                                    type="button"
                                    variant="outline"
                                    disabled={
                                        savingCohort
                                    }
                                    onClick={() =>
                                        setShowCohortDialog(
                                            false
                                        )
                                    }
                                >
                                    Cancel
                                </Button>

                                <Button
                                    type="submit"
                                    disabled={
                                        savingCohort
                                    }
                                >
                                    {savingCohort
                                        ? "Saving..."
                                        : editingCohort
                                            ? "Save Changes"
                                            : "Create"}
                                </Button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* ====================================================
                UPLOAD MATERIAL DIALOG
            ==================================================== */}

            {showUploadDialog &&
                uploadTarget && (
                    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
                        <div className="w-full max-w-2xl rounded-xl bg-background border shadow-xl">
                            <div className="p-6 border-b">
                                <h2 className="text-xl font-semibold">
                                    Upload Materials
                                </h2>

                                <p className="text-sm text-muted-foreground mt-1">
                                    Upload material ·{" "}
                                    {
                                        uploadTarget.name
                                    }
                                </p>
                            </div>

                            <form
                                onSubmit={
                                    handleUpload
                                }
                                className="p-6 flex flex-col gap-5"
                            >
                                {/* TITLE */}

                                <div>
                                    <label className="text-sm font-medium block mb-1">
                                        Material Title*
                                    </label>

                                    <Input
                                        value={
                                            materialTitle
                                        }
                                        onChange={(
                                            event
                                        ) =>
                                            setMaterialTitle(
                                                event
                                                    .target
                                                    .value
                                            )
                                        }
                                        placeholder="Material title"
                                    />
                                </div>

                                {/* TYPE */}

                                <div>
                                    <label className="text-sm font-medium block mb-1">
                                        Material Type*
                                    </label>

                                    <select
                                        className="w-full border rounded-md px-3 py-2 text-sm bg-background"
                                        value={
                                            materialType
                                        }
                                        onChange={(
                                            event
                                        ) =>
                                            setMaterialType(
                                                event
                                                    .target
                                                    .value
                                            )
                                        }
                                    >
                                        {Object.entries(
                                            MATERIAL_TYPES
                                        ).map(
                                            ([
                                                label,
                                                value,
                                            ]) => (
                                                <option
                                                    key={
                                                        value
                                                    }
                                                    value={
                                                        value
                                                    }
                                                >
                                                    {
                                                        label
                                                    }
                                                </option>
                                            )
                                        )}
                                    </select>
                                </div>

                                {/* FILE */}

                                <div>
                                    <label className="text-sm font-medium block mb-1">
                                        Choose File*
                                    </label>

                                    <Input
                                        type="file"
                                        accept=".txt,.md,.markdown,.json"
                                        onChange={
                                            handleFileChange
                                        }
                                    />

                                    <p className="text-xs text-muted-foreground mt-2">
                                        Accepted: .txt,
                                        .md, .markdown,
                                        .json
                                    </p>

                                    <p className="text-xs text-muted-foreground">
                                        Maximum file size:
                                        25 MB
                                    </p>
                                </div>

                                {/* SELECTED FILE */}

                                {selectedFile && (
                                    <div className="rounded-md bg-muted p-4">
                                        <p className="text-sm font-medium">
                                            📄 Selected
                                            File
                                        </p>

                                        <p className="text-sm text-muted-foreground mt-1">
                                            {
                                                selectedFile.name
                                            }
                                        </p>

                                        <p className="text-xs text-muted-foreground mt-1">
                                            {(
                                                selectedFile.size /
                                                (1024 *
                                                    1024)
                                            ).toFixed(
                                                2
                                            )}{" "}
                                            MB
                                        </p>
                                    </div>
                                )}

                                {/* INFO */}

                                <div className="rounded-md bg-muted p-4 text-sm text-muted-foreground">
                                    <p className="font-medium mb-2">
                                        Accepted File
                                        Types
                                    </p>

                                    <ul className="space-y-1">
                                        <li>
                                            📄 .txt
                                        </li>
                                        <li>
                                            📝 .md
                                        </li>
                                        <li>
                                            📝 .markdown
                                        </li>
                                        <li>
                                            📋 .json
                                        </li>
                                    </ul>

                                    <p className="mt-2">
                                        <strong>
                                            Maximum upload
                                            size:
                                        </strong>{" "}
                                        25 MB
                                    </p>
                                </div>

                                {/* BUTTONS */}

                                <div className="flex justify-end gap-3 pt-4 border-t">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        disabled={
                                            uploading
                                        }
                                        onClick={() =>
                                            setShowUploadDialog(
                                                false
                                            )
                                        }
                                    >
                                        Cancel
                                    </Button>

                                    <Button
                                        type="submit"
                                        disabled={
                                            uploading ||
                                            !selectedFile ||
                                            !materialTitle.trim()
                                        }
                                    >
                                        {uploading
                                            ? "Uploading..."
                                            : "Upload"}
                                    </Button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}

            {/* ====================================================
                DELETE DIALOG
            ==================================================== */}

            {deleteTarget && (
                <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
                    <div className="w-full max-w-md rounded-xl bg-background border shadow-xl">
                        <div className="p-6">
                            <h2 className="text-xl font-semibold">
                                Delete Cohort
                            </h2>

                            <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                                Are you sure you want to
                                delete{" "}
                                <strong>
                                    {
                                        deleteTarget.name
                                    }
                                </strong>
                                ?
                                <br />
                                <br />
                                This will permanently
                                delete the cohort and its
                                uploaded materials.
                            </div>
                        </div>

                        <div className="p-6 border-t flex justify-end gap-3">
                            <Button
                                variant="outline"
                                disabled={
                                    deleting
                                }
                                onClick={() =>
                                    setDeleteTarget(
                                        null
                                    )
                                }
                            >
                                Cancel
                            </Button>

                            <Button
                                variant="destructive"
                                disabled={
                                    deleting
                                }
                                onClick={
                                    handleDelete
                                }
                            >
                                {deleting
                                    ? "Deleting..."
                                    : "Delete"}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}