import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { useAuth } from "@/context/AuthContext";

export default function Guide() {
    const { user } = useAuth();
    const [content, setContent] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (user?.role !== "admin") return;

        fetch("/admin-guide.md")
            .then((res) => {
                if (!res.ok) throw new Error("Admin guide not found.");
                return res.text();
            })
            .then(setContent)
            .catch((err) => setError(err.message))
            .finally(() => setLoading(false));
    }, [user]);

    if (user?.role !== "admin") {
        return <div className="p-8 text-red-600">You are not authorized to view this page.</div>;
    }

    if (loading) return <div className="p-8">Loading...</div>;
    if (error) return <div className="p-8 text-red-600">{error}</div>;

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Documentation</p>
            <h1 className="text-2xl font-bold mb-6">📘 Administrator Guide</h1>
            <p className="text-muted-foreground mb-6">System administration and operational documentation.</p>
            <article className="prose max-w-none">
                <ReactMarkdown>{content}</ReactMarkdown>
            </article>
        </div>
    );
}