import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { MessageSquare, Bell, BookOpen } from "lucide-react";

const FEATURES = [
    { icon: MessageSquare, text: "Learners get instant answers from the program's own materials." },
    { icon: Bell, text: "At-risk nudges reach learners before they fall behind." },
    { icon: BookOpen, text: "Program leads keep cohort knowledge current in one place." },
];

export default function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
    return (
        <div className="min-h-screen grid lg:grid-cols-2">
            {/* Brand panel */}
            <div className="hidden lg:flex flex-col justify-between bg-primary text-primary-foreground p-12 relative overflow-hidden">
                <div
                    className="absolute inset-0 opacity-[0.07]"
                    style={{
                        backgroundImage: "radial-gradient(circle, white 1px, transparent 1px)",
                        backgroundSize: "24px 24px",
                    }}
                />
                <Link to="/" className="relative flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-white" />
                    <span className="font-bold text-lg tracking-tight">Ops Chatbot</span>
                </Link>

                <div className="relative">
                    <h2 className="text-3xl font-bold tracking-tight mb-8 max-w-sm">
                        Support that keeps learners on track.
                    </h2>
                    <div className="flex flex-col gap-5">
                        {FEATURES.map((f) => (
                            <div key={f.text} className="flex items-start gap-3">
                                <f.icon className="h-5 w-5 shrink-0 mt-0.5 opacity-80" />
                                <p className="text-sm opacity-90 max-w-xs">{f.text}</p>
                            </div>
                        ))}
                    </div>
                </div>

                <p className="relative text-xs opacity-60">Operations Support Portal</p>
            </div>

            {/* Form panel */}
            <div className="flex items-center justify-center p-8 bg-background">
                <div className="w-full max-w-sm motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-300">
                    <div className="lg:hidden flex items-center gap-2 mb-8">
                        <span className="h-2 w-2 rounded-full bg-primary" />
                        <span className="font-bold text-lg tracking-tight">Ops Chatbot</span>
                    </div>
                    <h1 className="text-2xl font-bold tracking-tight mb-1">{title}</h1>
                    <p className="text-muted-foreground text-sm mb-8">{subtitle}</p>
                    {children}
                </div>
            </div>
        </div>
    );
}