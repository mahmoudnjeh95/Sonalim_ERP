import { useQueries } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { HR_KEYS, listPresenceMonths } from "../presenceApi";

/** The closed periods ("YYYY-MM-01") of the given years. */
export function useClosedMonths(years: number[]): Set<string> {
  const { session } = useAuth();
  const token = session!.token;
  const unique = [...new Set(years)];
  const results = useQueries({
    queries: unique.map((year) => ({
      queryKey: [...HR_KEYS.presence, "months", year],
      queryFn: () => listPresenceMonths(token, year),
    })),
  });
  return new Set(results.flatMap((result) => (result.data ?? []).filter((m) => m.status === "closed").map((m) => m.period)));
}
