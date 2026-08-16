import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface Ticket {
  ticket_id: string;
  learner_name: string;
  user_id: string | null;
  reason: string;
  status: string;
  problem: string;
  context: string;
  suggested_next_step: string;
  summary: string;
  user_goal: string;
  created_at: string;
}

function statusColor(status: string) {
  switch (status.toLowerCase()) {
    case "open":
      return "bg-yellow-100 text-yellow-800";
    case "resolved":
      return "bg-green-100 text-green-800";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export default function Escalations() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  useEffect(() => {
    loadTickets();
  }, []);

  function loadTickets() {
    setLoading(true);
    api
      .get("/tickets")
      .then((res) => setTickets(res.data.tickets))
      .catch((err) => setError(err.response?.data?.detail ?? "Couldn't load tickets"))
      .finally(() => setLoading(false));
  }

  async function handleResolve(ticketId: string) {
    setResolving(true);
    try {
      await api.patch(`/tickets/${ticketId}/resolve`);
      loadTickets();
    } catch (err: any) {
      setError(err.response?.data?.detail ?? "Couldn't resolve ticket");
    } finally {
      setResolving(false);
    }
  }

  if (loading) return <div className="p-8">Loading tickets...</div>;
  if (error) return <div className="p-8 text-red-600">{error}</div>;
  if (tickets.length === 0) {
    return <div className="p-8 text-green-700">No escalation tickets right now 🎉</div>;
  }

  const selected = tickets.find((t) => t.ticket_id === selectedId) ?? null;

  return (
    <div className="p-8">
      <p className="text-sm text-muted-foreground">Support</p>
      <h1 className="text-2xl font-bold mb-1">🎫 Escalation Tickets</h1>
      <p className="text-muted-foreground mb-6">Conversations the assistant flagged for human follow-up.</p>

      <h2 className="font-semibold mb-2">Tickets</h2>
      <p className="text-sm text-muted-foreground mb-2">Click a row to view its details.</p>

      <div className="overflow-x-auto border rounded-md mb-6">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr>
              <th className="text-left p-2">Ticket ID</th>
              <th className="text-left p-2">Learner</th>
              <th className="text-left p-2">Reason</th>
              <th className="text-left p-2">Status</th>
              <th className="text-left p-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {tickets.map((t) => (
              <tr
                key={t.ticket_id}
                onClick={() => setSelectedId(t.ticket_id)}
                className={`border-t cursor-pointer hover:bg-muted/50 ${selectedId === t.ticket_id ? "bg-muted" : ""
                  }`}
              >
                <td className="p-2">{t.ticket_id}</td>
                <td className="p-2">{t.learner_name}</td>
                <td className="p-2">{t.reason}</td>
                <td className="p-2">
                  <Badge className={statusColor(t.status)}>{t.status}</Badge>
                </td>
                <td className="p-2">{new Date(t.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!selected ? (
        <p className="text-muted-foreground">Select a ticket from the table above.</p>
      ) : (
        <Card className="p-6">
          <div className="flex justify-between items-start mb-4">
            <h2 className="text-lg font-semibold">Ticket {selected.ticket_id}</h2>
            <Badge className={statusColor(selected.status)}>{selected.status}</Badge>
          </div>

          <h3 className="font-semibold text-sm mb-1">Learner</h3>
          <p className="mb-4 text-sm">
            <strong>{selected.learner_name}</strong>
            {selected.user_id ? <> · User ID: <code>{selected.user_id}</code></> : " · User ID unavailable"}
          </p>

          <h3 className="font-semibold text-sm mb-1">Problem</h3>
          <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-sm mb-4">{selected.problem}</div>

          <h3 className="font-semibold text-sm mb-1">Context</h3>
          <p className="text-sm mb-4">{selected.context}</p>

          <h3 className="font-semibold text-sm mb-1">Suggested Next Step</h3>
          <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm mb-4">
            {selected.suggested_next_step}
          </div>

          <h3 className="font-semibold text-sm mb-1">Summary</h3>
          <p className="text-sm mb-4">{selected.summary}</p>

          <h3 className="font-semibold text-sm mb-1">User Goal</h3>
          <p className="text-sm mb-4">{selected.user_goal}</p>

          <div className="border-t pt-4">
            {selected.status.toLowerCase() === "open" ? (
              <Button onClick={() => handleResolve(selected.ticket_id)} disabled={resolving} className="w-full">
                {resolving ? "Resolving..." : "✅ Resolve Ticket"}
              </Button>
            ) : (
              <p className="text-green-700 text-sm">This ticket has already been resolved.</p>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}