import { useAuth } from "../../lib/auth";

/**
 * Whether the signed-in user holds a given permission code, e.g.
 * `useHasPermission("maintenance.manage_teams")`. Thin wrapper around
 * `useAuth().hasPermission` so maintenance tabs/components don't each
 * destructure `hasPermission` off `useAuth()` themselves — several tabs
 * (teams, jobs, programs, parts) gate buttons/sections on more than one
 * permission and this keeps the call sites short.
 */
export function useHasPermission(code: string): boolean {
  const { hasPermission } = useAuth();
  return hasPermission(code);
}
