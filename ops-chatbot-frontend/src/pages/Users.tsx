import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const ROLE_OPTIONS = ["LEARNER", "ADMIN", "PROGRAM_LEAD"];
const UNASSIGNED_COHORT_ID = "unassigned";
const UNASSIGNED_LABEL = "Unassigned";

interface User {
    id: number;
    email: string;
    username: string;
    first_name: string;
    last_name: string;
    role: string;
    cohort_id: string | null;
    is_ops: boolean;
}

interface Cohort {
    cohort_id: string;
    name: string;
}

function displayName(u: User) {
    const full = `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim();
    return full || u.username || "Unknown User";
}

function generatePassword(length = 12) {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*";
    let pw = "";
    for (let i = 0; i < length; i++) pw += alphabet[Math.floor(Math.random() * alphabet.length)];
    return pw;
}

export default function Users() {
    const [users, setUsers] = useState<User[]>([]);
    const [cohorts, setCohorts] = useState<Cohort[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    const [showAddForm, setShowAddForm] = useState(false);
    const [addError, setAddError] = useState("");
    const [adding, setAdding] = useState(false);
    const [newUser, setNewUser] = useState({
        first_name: "", last_name: "", email: "", username: "", password: "", role: "LEARNER",
    });

    const [search, setSearch] = useState("");
    const [roleFilter, setRoleFilter] = useState("All roles");
    const [cohortFilter, setCohortFilter] = useState("All cohorts");

    // Per-row editable state: userId -> { role, cohort }
    const [rowEdits, setRowEdits] = useState<Record<number, { role: string; cohort: string }>>({});
    const [updatingId, setUpdatingId] = useState<number | null>(null);

    // Reset-password panel state
    const [resetOpenId, setResetOpenId] = useState<number | null>(null);
    const [generatedPw, setGeneratedPw] = useState("");
    const [resetting, setResetting] = useState(false);

    useEffect(() => {
        loadAll();
    }, []);

    function loadAll() {
        setLoading(true);
        Promise.all([api.get("/users/"), api.get("/kb/cohorts")])
            .then(([usersRes, cohortsRes]) => {
                setUsers(usersRes.data);
                setCohorts(cohortsRes.data.cohorts);
            })
            .catch((err) => setError(err.response?.data?.detail ?? "Couldn't load users"))
            .finally(() => setLoading(false));
    }

    const cohortNameMap: Record<string, string> = {};
    cohorts.forEach((c) => (cohortNameMap[c.cohort_id] = c.name));
    const cohortIdMap: Record<string, string> = {};
    cohorts.forEach((c) => (cohortIdMap[c.name] = c.cohort_id));
    const COHORT_OPTIONS = [UNASSIGNED_LABEL, ...cohorts.map((c) => c.name)];

    function cohortLabel(cohortId: string | null) {
        return (cohortId && cohortNameMap[cohortId]) || UNASSIGNED_LABEL;
    }

    function getEdit(user: User) {
        return rowEdits[user.id] ?? { role: user.role.toUpperCase(), cohort: cohortLabel(user.cohort_id) };
    }

    function setEdit(userId: number, patch: Partial<{ role: string; cohort: string }>) {
        setRowEdits((prev) => ({ ...prev, [userId]: { ...getEditFor(userId), ...patch } }));
    }

    function getEditFor(userId: number) {
        const u = users.find((x) => x.id === userId)!;
        return rowEdits[userId] ?? { role: u.role.toUpperCase(), cohort: cohortLabel(u.cohort_id) };
    }

    async function handleAddUser(e: React.FormEvent) {
        e.preventDefault();
        setAddError("");

        const { first_name, last_name, email, username, password, role } = newUser;
        if (![first_name, last_name, email, username, password].every(Boolean)) {
            setAddError("Please fill in all fields.");
            return;
        }
        if (password.length < 8) {
            setAddError("Password must be at least 8 characters long.");
            return;
        }

        setAdding(true);
        try {
            await api.post("/users/", {
                email, username, first_name, last_name, password,
                role: role.toLowerCase(),
            });
            setNewUser({ first_name: "", last_name: "", email: "", username: "", password: "", role: "LEARNER" });
            setShowAddForm(false);
            loadAll();
        } catch (err: any) {
            setAddError(err.response?.data?.detail ?? "Couldn't create user");
        } finally {
            setAdding(false);
        }
    }

    async function handleUpdateUser(user: User) {
        const edit = getEdit(user);
        setUpdatingId(user.id);
        try {
            await api.patch(`/users/${user.id}/role`, {
                role: edit.role.toLowerCase(),
                cohort: edit.cohort === UNASSIGNED_LABEL ? UNASSIGNED_COHORT_ID : cohortIdMap[edit.cohort],
            });
            loadAll();
        } catch (err: any) {
            setError(err.response?.data?.detail ?? "Couldn't update user");
        } finally {
            setUpdatingId(null);
        }
    }

    async function handleConfirmReset(userId: number) {
        setResetting(true);
        try {
            await api.patch(`/users/${userId}/password`, { password: generatedPw });
            setResetOpenId(null);
            setGeneratedPw("");
        } catch (err: any) {
            setError(err.response?.data?.detail ?? "Couldn't reset password");
        } finally {
            setResetting(false);
        }
    }

    if (loading) return <div className="p-8">Loading users...</div>;
    if (error) return <div className="p-8 text-red-600">{error}</div>;

    const filtered = users.filter((u) => {
        const name = displayName(u);
        const role = u.role.toUpperCase();
        const cohortName = cohortLabel(u.cohort_id);

        if (search.trim()) {
            const haystack = `${name} ${u.username} ${u.email}`.toLowerCase();
            if (!haystack.includes(search.trim().toLowerCase())) return false;
        }
        if (roleFilter !== "All roles" && role !== roleFilter) return false;
        if (cohortFilter !== "All cohorts" && cohortName !== cohortFilter) return false;
        return true;
    });

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Program Lead</p>
            <h1 className="text-2xl font-bold mb-1">👥 User Management</h1>
            <p className="text-muted-foreground mb-6">View learners and staff.</p>

            {/* Add user */}
            <Card className="p-4 mb-6">
                <button
                    className="font-semibold w-full text-left"
                    onClick={() => setShowAddForm((v) => !v)}
                >
                    ➕ Add a new user {showAddForm ? "▲" : "▼"}
                </button>

                {showAddForm && (
                    <form onSubmit={handleAddUser} className="grid grid-cols-2 gap-3 mt-4">
                        <Input placeholder="First name" value={newUser.first_name} onChange={(e) => setNewUser({ ...newUser, first_name: e.target.value })} />
                        <Input placeholder="Last name" value={newUser.last_name} onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })} />
                        <Input placeholder="Email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
                        <Input placeholder="Username" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
                        <Input type="password" placeholder="Password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
                        <select
                            className="border rounded-md px-3 py-2 text-sm"
                            value={newUser.role}
                            onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
                        >
                            {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                        </select>

                        {addError && <p className="col-span-2 text-red-600 text-sm">{addError}</p>}

                        <Button type="submit" disabled={adding} className="col-span-2">
                            {adding ? "Creating..." : "Create user"}
                        </Button>
                    </form>
                )}
            </Card>

            {/* Filters */}
            <div className="grid grid-cols-3 gap-3 mb-2">
                <Input placeholder="Search by name, or email..." value={search} onChange={(e) => setSearch(e.target.value)} />
                <select className="border rounded-md px-3 py-2 text-sm" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                    {["All roles", ...ROLE_OPTIONS].map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <select className="border rounded-md px-3 py-2 text-sm" value={cohortFilter} onChange={(e) => setCohortFilter(e.target.value)}>
                    {["All cohorts", ...COHORT_OPTIONS].map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
            </div>

            <p className="text-sm text-muted-foreground mb-4">{filtered.length} of {users.length} users</p>

            {filtered.length === 0 ? (
                <p className="text-muted-foreground">No users match your search/filters.</p>
            ) : (
                <div className="flex flex-col gap-3">
                    {filtered.map((user) => {
                        const role = user.role.toLowerCase();
                        const isStaff = role === "admin" || role === "program_lead";
                        const edit = getEdit(user);
                        const unchanged = edit.role.toLowerCase() === role && edit.cohort === cohortLabel(user.cohort_id);

                        return (
                            <Card key={user.id} className="p-4">
                                <div className="grid grid-cols-[2.8fr_1.8fr_1.8fr_1fr] gap-4 items-start">
                                    <div>
                                        <p className="font-semibold">{displayName(user)}</p>
                                        <p className="text-xs text-muted-foreground">{user.email ?? "No email"}</p>
                                        <Badge className="mt-1">{user.role}</Badge>
                                        {!isStaff && <Badge variant="outline" className="ml-1 mt-1">{cohortLabel(user.cohort_id)}</Badge>}
                                    </div>

                                    <select
                                        className="border rounded-md px-2 py-1.5 text-sm"
                                        value={edit.role}
                                        disabled={isStaff}
                                        onChange={(e) => setEdit(user.id, { role: e.target.value })}
                                    >
                                        {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                                    </select>

                                    {isStaff ? (
                                        <div>
                                            <p className="text-sm font-medium">Cohort</p>
                                            <p className="text-sm text-muted-foreground">—</p>
                                        </div>
                                    ) : (
                                        <select
                                            className="border rounded-md px-2 py-1.5 text-sm"
                                            value={edit.cohort}
                                            onChange={(e) => setEdit(user.id, { cohort: e.target.value })}
                                        >
                                            {COHORT_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                                        </select>
                                    )}

                                    <div className="flex flex-col gap-2">
                                        <Button
                                            size="sm"
                                            disabled={isStaff || unchanged || updatingId === user.id}
                                            onClick={() => handleUpdateUser(user)}
                                        >
                                            {updatingId === user.id ? "..." : "Update"}
                                        </Button>
                                        <Button size="sm" variant="outline" onClick={() => setResetOpenId(resetOpenId === user.id ? null : user.id)}>
                                            Reset Password
                                        </Button>
                                    </div>
                                </div>

                                {resetOpenId === user.id && (
                                    <div className="border-t mt-4 pt-4">
                                        <p className="text-sm text-muted-foreground mb-2">
                                            Reset password for <strong>{displayName(user)}</strong>
                                        </p>
                                        <div className="flex gap-2 items-center">
                                            <Button size="sm" variant="outline" onClick={() => setGeneratedPw(generatePassword())}>
                                                Generate password
                                            </Button>
                                            {generatedPw && (
                                                <>
                                                    <code className="bg-muted px-2 py-1 rounded text-sm">{generatedPw}</code>
                                                    <Button size="sm" onClick={() => handleConfirmReset(user.id)} disabled={resetting}>
                                                        {resetting ? "..." : "Confirm & set"}
                                                    </Button>
                                                </>
                                            )}
                                            <Button size="sm" variant="ghost" onClick={() => { setResetOpenId(null); setGeneratedPw(""); }}>
                                                Cancel
                                            </Button>
                                        </div>
                                        {generatedPw && (
                                            <p className="text-xs text-muted-foreground mt-2">
                                                Click "Confirm & set" to apply it. Make sure to copy it first — it won't be shown again.
                                            </p>
                                        )}
                                    </div>
                                )}
                            </Card>
                        );
                    })}
                </div>
            )}
        </div>
    );
}