import { apiFetch } from "../../lib/api";

export interface Contact {
  id: string;
  partner_id: string;
  first_name: string;
  last_name: string;
  job_title: string | null;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
}

export interface CreateContactInput {
  partner_id: string;
  first_name: string;
  last_name: string;
  job_title?: string;
  email?: string;
  phone?: string;
  is_primary: boolean;
}

export function listContacts(token: string, partnerId?: string) {
  const query = partnerId ? `?partner_id=${encodeURIComponent(partnerId)}` : "";
  return apiFetch<Contact[]>(`/crm/contacts${query}`, { token });
}

export function createContact(token: string, input: CreateContactInput) {
  return apiFetch<Contact>("/crm/contacts", { method: "POST", token, body: input });
}
