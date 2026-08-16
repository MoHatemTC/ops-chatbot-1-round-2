import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface Profile {
    username: string;
    email: string;
    role: string;
}

interface Teammate {
    id: number;
    username?: string;
    email?: string;
}

interface TeamInfo {
    cohort_id: string;
    teammates: Teammate[];
}

interface Preferences {
    opted_out: boolean;
    session_reminders: boolean;
    deadline_reminders: boolean;
    nudges: boolean;
}

export default function Settings() {
    const { user } = useAuth();
    const isLearner = user?.role === "learner";

    // Account
    const [profile, setProfile] = useState<Profile | null>(null);

    // Password
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [passwordMessage, setPasswordMessage] = useState<{ type: "error" | "success"; text: string } | null>(null);
    const [savingPassword, setSavingPassword] = useState(false);

    // Team
    const [teamInfo, setTeamInfo] = useState<TeamInfo | null>(null);

    // Preferences
    const [preferences, setPreferences] = useState<Preferences>({
        opted_out: false,
        session_reminders: true,
        deadline_reminders: true,
        nudges: true,
    });
    const [prefsMessage, setPrefsMessage] = useState<{ type: "error" | "success"; text: string } | null>(null);
    const [savingPrefs, setSavingPrefs] = useState(false);

    useEffect(() => {
        api.get("/users/me").then((res) => setProfile(res.data));

        if (isLearner) {
            api.get("/users/me/teammates").then((res) => setTeamInfo(res.data)).catch(() => setTeamInfo(null));
            api.get("/notifications/preferences").then((res) => setPreferences(res.data)).catch(() => { });
        }
    }, [isLearner]);

    async function handleSavePassword() {
        setPasswordMessage(null);

        if (!newPassword) {
            setPasswordMessage({ type: "error", text: "Please enter a new password." });
            return;
        }
        if (newPassword.length < 8) {
            setPasswordMessage({ type: "error", text: "Password must be at least 8 characters long." });
            return;
        }
        if (newPassword !== confirmPassword) {
            setPasswordMessage({ type: "error", text: "Passwords do not match." });
            return;
        }

        setSavingPassword(true);
        try {
            await api.patch("/users/me/password", { password: newPassword });
            setNewPassword("");
            setConfirmPassword("");
            setPasswordMessage({ type: "success", text: "Password updated successfully!" });
        } catch (err: any) {
            setPasswordMessage({ type: "error", text: err.response?.data?.detail ?? "Failed to update password" });
        } finally {
            setSavingPassword(false);
        }
    }

    async function handleSavePreferences() {
        setSavingPrefs(true);
        setPrefsMessage(null);
        try {
            const res = await api.put("/notifications/preferences", preferences);
            setPreferences(res.data);
            setPrefsMessage({ type: "success", text: "Notification preferences updated!" });
        } catch (err: any) {
            setPrefsMessage({ type: "error", text: err.response?.data?.detail ?? "Failed to update preferences" });
        } finally {
            setSavingPrefs(false);
        }
    }

    return (
        <div className="p-8">
            <p className="text-sm text-muted-foreground">Account</p>
            <h1 className="text-2xl font-bold mb-1">⚙️ Settings</h1>
            <p className="text-muted-foreground mb-6">Manage your account and notification preferences.</p>

            {/* Account */}
            <h2 className="font-semibold mb-2">👤 Account</h2>
            <div className="grid grid-cols-2 gap-4 mb-6">
                <Card className="p-4">
                    <p className="text-xs text-muted-foreground mb-1">Username</p>
                    <Input value={profile?.username ?? ""} disabled />
                    <p className="text-xs text-muted-foreground mt-3 mb-1">Email</p>
                    <Input value={profile?.email ?? ""} disabled />
                </Card>
                <Card className="p-4">
                    <p className="text-xs text-muted-foreground mb-1">Role</p>
                    <Input value={profile ? profile.role.charAt(0).toUpperCase() + profile.role.slice(1) : ""} disabled />
                </Card>
            </div>

            {/* Password */}
            <Card className="p-4 mb-6">
                <h2 className="font-semibold mb-1">🔒 Password</h2>
                <p className="text-sm text-muted-foreground mb-3">
                    Create or change your password. Your current password is never displayed.
                </p>

                <Input
                    type="password"
                    placeholder="Enter your new password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="mb-2"
                />
                <Input
                    type="password"
                    placeholder="Re-enter your new password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="mb-2"
                />
                <p className="text-xs text-muted-foreground mb-3">Password must be at least 8 characters long.</p>

                {passwordMessage && (
                    <p className={`text-sm mb-3 ${passwordMessage.type === "error" ? "text-red-600" : "text-green-600"}`}>
                        {passwordMessage.text}
                    </p>
                )}

                <Button onClick={handleSavePassword} disabled={savingPassword} className="w-full">
                    {savingPassword ? "Saving..." : "🔑 Save Password"}
                </Button>
            </Card>

            {/* Your Group — learner only */}
            {isLearner && (
                <Card className="p-4 mb-6">
                    <h2 className="font-semibold mb-2">👥 Your Group</h2>

                    {!teamInfo || teamInfo.cohort_id === "unassigned" ? (
                        <p className="text-sm text-muted-foreground">You haven't been assigned to a group yet.</p>
                    ) : (
                        <>
                            <p className="text-sm mb-2"><strong>Group:</strong> {teamInfo.cohort_id}</p>
                            {teamInfo.teammates.length === 0 ? (
                                <p className="text-xs text-muted-foreground">No other learners in your group yet.</p>
                            ) : (
                                <>
                                    <p className="text-xs text-muted-foreground mb-1">
                                        {teamInfo.teammates.length} teammate(s) in your group:
                                    </p>
                                    <ul className="text-sm">
                                        {teamInfo.teammates.map((mate) => (
                                            <li key={mate.id}>
                                                <strong>{mate.username ?? mate.email ?? "Unknown"}</strong> &nbsp;·&nbsp; {mate.email ?? ""}
                                            </li>
                                        ))}
                                    </ul>
                                </>
                            )}
                        </>
                    )}
                </Card>
            )}

            {/* Notification Preferences — learner only */}
            {isLearner && (
                <Card className="p-4">
                    <h2 className="font-semibold mb-3">⏰ Reminder Preferences</h2>

                    {prefsMessage && (
                        <p className={`text-sm mb-3 ${prefsMessage.type === "error" ? "text-red-600" : "text-green-600"}`}>
                            {prefsMessage.text}
                        </p>
                    )}

                    <label className="flex items-center gap-2 mb-2 text-sm">
                        <input
                            type="checkbox"
                            checked={preferences.opted_out}
                            onChange={(e) => setPreferences({ ...preferences, opted_out: e.target.checked })}
                        />
                        Opt out of all notifications
                    </label>

                    <label className="flex items-center gap-2 mb-2 text-sm">
                        <input
                            type="checkbox"
                            checked={preferences.session_reminders}
                            disabled={preferences.opted_out}
                            onChange={(e) => setPreferences({ ...preferences, session_reminders: e.target.checked })}
                        />
                        Session reminders
                    </label>

                    <label className="flex items-center gap-2 mb-2 text-sm">
                        <input
                            type="checkbox"
                            checked={preferences.deadline_reminders}
                            disabled={preferences.opted_out}
                            onChange={(e) => setPreferences({ ...preferences, deadline_reminders: e.target.checked })}
                        />
                        Deadline reminders
                    </label>

                    <label className="flex items-center gap-2 mb-4 text-sm">
                        <input
                            type="checkbox"
                            checked={preferences.nudges}
                            disabled={preferences.opted_out}
                            onChange={(e) => setPreferences({ ...preferences, nudges: e.target.checked })}
                        />
                        Learning nudges
                    </label>

                    <Button onClick={handleSavePreferences} disabled={savingPrefs} className="w-full">
                        {savingPrefs ? "Saving..." : "💾 Save Preferences"}
                    </Button>
                </Card>
            )}
        </div>
    );
}