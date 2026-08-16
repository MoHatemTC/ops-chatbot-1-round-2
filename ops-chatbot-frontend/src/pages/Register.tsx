import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import AuthLayout from "@/components/AuthLayout";

interface Cohort {
    cohort_id: string;
    name: string;
}

export default function Register() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [firstName, setFirstName] = useState("");
    const [lastName, setLastName] = useState("");
    const [cohortId, setCohortId] = useState("");
    const [cohorts, setCohorts] = useState<Cohort[]>([]);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    useEffect(() => {
        api.get("/cohorts").then((res) => setCohorts(res.data));
    }, []);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError("");
        setLoading(true);
        try {
            await api.post("/auth/register", {
                email,
                password,
                first_name: firstName,
                last_name: lastName,
                cohort_id: cohortId || "unassigned",
            });
            navigate("/login");
        } catch (err: any) {
            setError(err.response?.data?.detail ?? "Registration failed");
        } finally {
            setLoading(false);
        }
    }

    return (
        <AuthLayout title="Create your account" subtitle="Join your program's support portal.">
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-3">
                    <div>
                        <label className="text-sm font-medium mb-1.5 block">First name</label>
                        <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} />
                    </div>
                    <div>
                        <label className="text-sm font-medium mb-1.5 block">Last name</label>
                        <Input value={lastName} onChange={(e) => setLastName(e.target.value)} />
                    </div>
                </div>

                <div>
                    <label className="text-sm font-medium mb-1.5 block">Email</label>
                    <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
                </div>

                <div>
                    <label className="text-sm font-medium mb-1.5 block">Password</label>
                    <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
                </div>

                <div>
                    <label className="text-sm font-medium mb-1.5 block">Cohort</label>
                    <select
                        className="w-full border rounded-md px-3 py-2 text-sm bg-background"
                        value={cohortId}
                        onChange={(e) => setCohortId(e.target.value)}
                    >
                        <option value="">Select a cohort</option>
                        {cohorts.map((c) => (
                            <option key={c.cohort_id} value={c.cohort_id}>{c.name}</option>
                        ))}
                    </select>
                </div>

                {error && <p className="text-sm text-destructive">{error}</p>}

                <Button type="submit" disabled={loading} className="w-full mt-2">
                    {loading ? "Creating account..." : "Register"}
                </Button>

                <p className="text-sm text-muted-foreground text-center mt-2">
                    Already have an account? <Link to="/login" className="text-primary hover:underline">Log in</Link>
                </p>
            </form>
        </AuthLayout>
    );
}