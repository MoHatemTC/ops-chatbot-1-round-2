import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";

interface Reminder {
    type: string;
    due_at: string;
    title: string;
    description?: string;
}

type DueFilter = "All" | "Overdue" | "Today" | "Tomorrow" | "This Week" | "Future";

function daysFromToday(n: number): Date {
    const d = new Date();
    d.setUTCHours(0, 0, 0, 0);
    d.setUTCDate(d.getUTCDate() + n);
    return d;
}

function dateOnly(iso: string): Date {
    const d = new Date(iso);
    d.setUTCHours(0, 0, 0, 0);
    return d;
}

export default function Reminders() {
    const [reminders, setReminders] = useState<Reminder[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [typeFilter, setTypeFilter] = useState("All");
    const [dueFilter, setDueFilter] = useState<DueFilter>("All");

    useEffect(() => {
        api
            .get("/reminders")
            .then((res) => {
                const all: Reminder[] = res.data;
                setReminders(all.filter((r) => String(r.type).toUpperCase() !== "FEEDBACK_FOLLOW_UP"));
            })
            .catch((err) => setError(err.response?.data?.detail ?? "Couldn't load reminders"))
            .finally(() => setLoading(false));
    }, []);

    if (loading) return <div className="p-8">Loading reminders...</div>;
    if (error) return <div className="p-8 text-red-600">{error}</div>;
    if (reminders.length === 0) return <div className="p-8 text-muted-foreground">No reminders.</div>;

    const reminderTypes = Array.from(new Set(reminders.map((r) => r.type))).sort();

    const today = daysFromToday(0);
    const tomorrow = daysFromToday(1);
    const weekOut = daysFromToday(7);

    const filtered = reminders.filter((r) => {
        if (typeFilter !== "All" && r.type !== typeFilter) return false;

        const due = dateOnly(r.due_at);

        switch (dueFilter) {
            case "All":
                return true;
            case "Overdue":
                return due < today;
            case "Today":
                return due.getTime() === today.getTime();
            case "Tomorrow":
                return due.getTime() === tomorrow.getTime();
            case "This Week":
                return due >= today && due <= weekOut;
            case "Future":
                return due > weekOut;
        }
    });

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">⏰ Reminders</h1>
            <p className="text-muted-foreground mb-6">Your reminders.</p>

            <div className="grid grid-cols-2 gap-4 mb-6">
                <select
                    className="border rounded-md px-3 py-2 text-sm"
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                >
                    <option value="All">All</option>
                    {reminderTypes.map((t) => (
                        <option key={t} value={t}>{t}</option>
                    ))}
                </select>

                <select
                    className="border rounded-md px-3 py-2 text-sm"
                    value={dueFilter}
                    onChange={(e) => setDueFilter(e.target.value as DueFilter)}
                >
                    {["All", "Overdue", "Today", "Tomorrow", "This Week", "Future"].map((f) => (
                        <option key={f} value={f}>{f}</option>
                    ))}
                </select>
            </div>

            {filtered.length === 0 ? (
                <p className="text-muted-foreground">No reminders match the selected filters.</p>
            ) : (
                <div className="flex flex-col gap-4">
                    {filtered.map((reminder, i) => (
                        <Card key={i} className="p-4">
                            <h2 className="font-semibold text-lg mb-2">{reminder.title}</h2>
                            <div className="grid grid-cols-2 gap-2 text-sm mb-2">
                                <p><strong>Type:</strong> {reminder.type}</p>
                                <p><strong>Due:</strong> {reminder.due_at}</p>
                            </div>
                            {reminder.description && <p className="text-sm">{reminder.description}</p>}
                        </Card>
                    ))}
                </div>
            )}
        </div>
    );
}