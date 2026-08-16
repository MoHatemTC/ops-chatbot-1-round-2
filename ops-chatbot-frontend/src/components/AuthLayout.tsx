import { Outlet, useLocation } from "react-router-dom";
import AppSidebar from "./AppSidebar";
import NotificationBell from "./NotificationBell";

export default function AppLayout() {
    const location = useLocation();

    return (
        <div className="flex h-screen overflow-hidden">
            <div className="sticky top-0 h-screen shrink-0">
                <AppSidebar />
            </div>
            <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
                <div className="flex justify-end p-4 border-b shrink-0">
                    <NotificationBell />
                </div>
                <main className="flex-1">
                    <div
                        key={location.pathname}
                        className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-300"
                    >
                        <Outlet />
                    </div>
                </main>
            </div>
        </div>
    );
}