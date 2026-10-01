import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BASE_URL, ApiError, apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";
import { useAuth } from "../../lib/auth";

/** The signed-in person's own employee file, as /hr/me/profile answers it (unmasked: it is theirs). */
export interface MyProfile {
  id: string;
  employee_no: string;
  first_name: string;
  last_name: string;
  full_name: string;
  hire_date: string;
  job_title: string | null;
  department_name: string | null;
  position_title: string | null;
  grade_code: string | null;
  status: string;
  gender: string | null;
  birth_date: string | null;
  birth_place: string | null;
  nationality: string | null;
  national_id: string | null;
  inps_no: string | null;
  amo_no: string | null;
  marital_status: string | null;
  address: string | null;
  emergency_contact: string | null;
  badge_no: string | null;
  site: string | null;
  user_email: string | null;
}

/** NO_EMPLOYEE_FILE is a normal answer, not a failure: plenty of accounts (admin, service) have none. */
export function useMyProfile() {
  const { session } = useAuth();
  return useQuery({
    queryKey: ["profile", "me", session?.userId],
    queryFn: async () => {
      try {
        return await apiFetch<MyProfile>("/hr/me/profile", { token: session!.token });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: !!session,
  });
}

/** The avatar's bytes: an <img> cannot send the bearer token itself, so we fetch the blob
 * and the caller makes (and revokes) its own object URL -- the same shape as scan's PageImage. */
async function fetchAvatarBlob(token: string): Promise<Blob | null> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/core/users/me/avatar`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (response.status === 404) return null; // no photo set is a normal state
  if (!response.ok) throw await apiErrorFromResponse(response);
  return await response.blob();
}

export const MY_AVATAR_KEY = ["profile", "my-avatar"] as const;

export function useMyAvatar() {
  const { session } = useAuth();
  return useQuery({
    queryKey: [...MY_AVATAR_KEY, session?.userId],
    queryFn: () => fetchAvatarBlob(session!.token),
    enabled: !!session,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
  });
}

export function useSetMyAvatar() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dataBase64: string) =>
      apiFetch<{ content_type: string; bytes: number }>("/core/users/me/avatar", {
        method: "PUT",
        token: session!.token,
        body: { data_base64: dataBase64 },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MY_AVATAR_KEY }),
  });
}

export function useRemoveMyAvatar() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/core/users/me/avatar", { method: "DELETE", token: session!.token }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MY_AVATAR_KEY }),
  });
}
