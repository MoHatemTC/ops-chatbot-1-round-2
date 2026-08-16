import { Link } from "react-router-dom";
import { BarChart3, BookOpen, Users2 } from "lucide-react";

export default function Landing() {
    return (
        <div className="min-h-screen bg-background">
            {/* Top bar */}
            <div className="flex items-center justify-between px-8 py-6 max-w-6xl mx-auto">
                <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-primary" />
                    <span className="font-bold text-lg tracking-tight">Ops Chatbot</span>
                </div>
                <div className="flex gap-3">
                    <Link to="/login" className="text-sm font-medium px-4 py-2 hover:text-primary transition-colors">
                        Log in
                    </Link>
                    <Link
                        to="/register"
                        className="text-sm font-medium px-4 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
                    >
                        Register
                    </Link>
                </div>
            </div>

            {/* Hero: text + live chat mockup */}
            <div className="max-w-6xl mx-auto px-8 pt-12 pb-24 grid lg:grid-cols-2 gap-16 items-center">
                <div className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-left-4 motion-safe:duration-500">
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary mb-4">
                        Operations Support Portal
                    </p>
                    <h1 className="text-5xl font-bold tracking-tight mb-5 leading-[1.1]">
                        Support that catches learners before they fall behind.
                    </h1>
                    <p className="text-muted-foreground text-lg mb-8 max-w-md">
                        Every question gets answered from your program's own materials — and every
                        at-risk signal reaches Ops before it becomes a dropout.
                    </p>
                    <div className="flex gap-3">
                        <Link
                            to="/register"
                            className="px-6 py-3 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
                        >
                            Get started
                        </Link>
                        <Link
                            to="/login"
                            className="px-6 py-3 rounded-md border text-sm font-medium hover:bg-muted transition-colors"
                        >
                            Log in
                        </Link>
                    </div>
                </div>

                {/* Simulated chat panel — the product's actual signature moment */}
                <div className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-right-4 motion-safe:duration-500">
                    <div className="border rounded-xl bg-card shadow-lg overflow-hidden">
                        <div className="flex items-center gap-2 px-4 py-3 border-b bg-muted/40">
                            <span className="h-2 w-2 rounded-full bg-blue-600" />
                            <span className="text-xs font-medium text-muted-foreground">Chat Viewer — live session</span>
                        </div>
                        <div className="p-5 flex flex-col gap-3">
                            <div className="flex justify-end">
                                <div className="bg-primary text-primary-foreground rounded-2xl rounded-br-sm px-4 py-2 text-sm max-w-[75%]">
                                    When's the deadline for the capstone project?
                                </div>
                            </div>
                            <div className="flex justify-start">
                                <div className="bg-muted rounded-2xl rounded-bl-sm px-4 py-2 text-sm max-w-[75%]">
                                    The capstone is due Friday at 11:59 PM, per your cohort schedule.
                                </div>
                            </div>
                            <div
                                className="flex justify-start motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1"
                                style={{ animationDelay: "600ms", animationFillMode: "backwards" }}
                            >
                                <div className="max-w-[75%]">
                                    <div className="text-[10px] font-bold bg-amber-200 text-amber-900 rounded-full px-2 py-0.5 inline-block mb-1">
                                        ⚑ at-risk nudge
                                    </div>
                                    <div className="bg-muted border-2 border-amber-400 rounded-2xl rounded-bl-sm px-4 py-2 text-sm">
                                        Just checking in — I noticed you haven't logged in for a few days. Need a hand with anything?
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <p className="text-xs text-muted-foreground text-center mt-3">
                        What learners see — and what tells Ops someone needs a check-in.
                    </p>
                </div>
            </div>

            {/* Role breakdown — a real sequence: learner asks, Ops sees */}
            <div className="border-t bg-muted/20">
                <div className="max-w-6xl mx-auto px-8 py-20">
                    <h2 className="text-2xl font-bold tracking-tight mb-2">One conversation, three views</h2>
                    <p className="text-muted-foreground mb-12 max-w-lg">
                        The same chat session looks different depending on who's watching it.
                    </p>

                    <div className="grid md:grid-cols-3 gap-8">
                        <div className="flex flex-col gap-3">
                            <span className="text-xs font-semibold uppercase tracking-widest text-blue-700">01 — Learner</span>
                            <div className="h-9 w-9 rounded-lg bg-blue-50 flex items-center justify-center">
                                <BookOpen className="h-4 w-4 text-blue-700" />
                            </div>
                            <p className="text-sm text-muted-foreground">
                                Asks questions in plain language, gets answers sourced from their cohort's
                                approved materials — no digging through docs.
                            </p>
                        </div>
                        <div className="flex flex-col gap-3">
                            <span className="text-xs font-semibold uppercase tracking-widest text-violet-700">02 — Program lead</span>
                            <div className="h-9 w-9 rounded-lg bg-violet-50 flex items-center justify-center">
                                <Users2 className="h-4 w-4 text-violet-700" />
                            </div>
                            <p className="text-sm text-muted-foreground">
                                Manages cohorts and keeps the knowledge base current, so answers stay
                                accurate as the program evolves.
                            </p>
                        </div>
                        <div className="flex flex-col gap-3">
                            <span className="text-xs font-semibold uppercase tracking-widest text-amber-700">03 — Admin</span>
                            <div className="h-9 w-9 rounded-lg bg-amber-50 flex items-center justify-center">
                                <BarChart3 className="h-4 w-4 text-amber-700" />
                            </div>
                            <p className="text-sm text-muted-foreground">
                                Sees escalations that need a human, and at-risk trends across every
                                cohort before they become dropouts.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}