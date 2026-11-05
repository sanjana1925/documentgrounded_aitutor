import { NavLink } from "react-router-dom";
import { LayoutDashboard, Bot, Brain, BarChart3, Sparkles, X } from "lucide-react";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/tutor", label: "AI Tutor", icon: Bot },
  { to: "/quiz", label: "Adaptive Quiz", icon: Brain },
  { to: "/evaluation", label: "Evaluation", icon: BarChart3 },
];

export default function Sidebar({ open, onClose }) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 bg-ink/40 z-40 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        className={`fixed lg:sticky top-0 left-0 h-screen w-72 shrink-0 bg-bg border-r-2 border-ink z-50
          flex flex-col gap-6 px-5 py-6 transition-transform duration-300
          ${open ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="w-11 h-11 rounded-md bg-violet border-2 border-ink shadow-std grid place-items-center">
              <Sparkles size={22} strokeWidth={2.5} className="text-white" />
            </span>
            <span className="font-heading font-extrabold text-lg leading-tight">AI Tutor Guide</span>
          </div>
          <button className="lg:hidden p-1.5 rounded-sm border-2 border-ink" onClick={onClose} aria-label="Close navigation">
            <X size={18} strokeWidth={2.5} />
          </button>
        </div>

        <nav className="flex flex-col gap-2" aria-label="Primary">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-md border-2 font-body font-semibold tactile min-h-[48px]
                ${
                  isActive
                    ? "bg-violet text-white border-ink shadow-sm"
                    : "bg-transparent text-fg border-transparent hover:bg-amber/25 hover:border-ink"
                }`
              }
            >
              <Icon size={20} strokeWidth={2.5} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
    </>
  );
}
