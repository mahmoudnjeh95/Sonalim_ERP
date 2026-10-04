import { useState } from "react";
import { NavLink } from "react-router-dom";
import { ChevronsUpDown, LogOut, Settings as SettingsIcon, UserCircle } from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { cn } from "../lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { UserAvatar } from "../features/profile/UserAvatar";
import { useMyProfile } from "../features/profile/api";

/**
 * The signed-in person, as one row at the foot of the sidebar.
 *
 * It replaces what used to be three stacked rows (Settings, the user line with its own
 * sign-out button, and the e-mail under a "Signed in" caption): the photo and the name
 * are the row, and everything you can do about the account lives in the popover.
 */
export function SidebarUserMenu({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { session, logout } = useAuth();
  const { t } = useI18n();
  const profile = useMyProfile();
  const [open, setOpen] = useState(false);

  // The employee file's name when HR keeps one for this account, the e-mail otherwise.
  const name = profile.data?.full_name ?? null;
  const shown = name ?? session?.email ?? session?.userId ?? "—";

  const close = () => {
    setOpen(false);
    onNavigate?.();
  };

  const itemClass =
    "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          title={collapsed ? shown : undefined}
          aria-label={t("nav.accountMenu")}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-md py-1.5 text-left transition-colors hover:bg-muted",
            collapsed ? "justify-center px-1.5" : "px-2",
          )}
        >
          <UserAvatar name={name} email={session?.email} className="h-7 w-7 text-xs" />
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">{shown}</span>
              <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent align="start" side="top" className="w-56 p-1.5">
        <div className="border-b border-border px-2 pb-2 pt-1">
          <p className="truncate text-sm font-medium">{shown}</p>
          {/* The e-mail stays visible here when the row shows a name instead. */}
          <p className="truncate text-[11px] text-muted-foreground">{session?.email ?? t("nav.signedIn")}</p>
        </div>

        <div className="pt-1.5">
          <NavLink to="/profile" onClick={close} className={itemClass}>
            <UserCircle className="h-4 w-4 shrink-0" />
            {t("nav.myProfile")}
          </NavLink>
          <NavLink to="/settings" onClick={close} className={itemClass}>
            <SettingsIcon className="h-4 w-4 shrink-0" />
            {t("nav.settings")}
          </NavLink>
          <button type="button" onClick={logout} className={cn(itemClass, "hover:text-destructive")}>
            <LogOut className="h-4 w-4 shrink-0" />
            {t("nav.signOut")}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
