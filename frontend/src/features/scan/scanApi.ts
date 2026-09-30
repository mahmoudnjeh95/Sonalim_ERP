import { apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";
import type { GridRow } from "../production/shift/ShiftGrid";
import type { Row, SectionKey, SectionPayload, SectionStatus, ShiftStatus } from "../production/shift/shiftApi";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type PageStatus = "queued" | "reading" | "read" | "unrecognized" | "failed";
export type FormType = "fabrication" | "conditionnement" | "bobines";
export type Verdict = "this_shift" | "other_shift" | "unknown";
export type SessionStatus = "open" | "applied" | "discarded";
export type Choice = "replace" | "keep";

export interface ReadHeader {
  date: string | null;
  team: string | null;
  hours_from: string | null;
  line: string | null;
}

export interface ScanPage {
  id: string;
  status: PageStatus;
  form_type: FormType | null;
  form_hint: FormType | null;
  rotation: number;
  width: number | null;
  height: number | null;
  attempts: number;
  error: string | null;
  created_at: string;
  read_at: string | null;
  attribution: { verdict: Verdict; reasons: string[]; read: ReadHeader } | null;
}

export interface ShiftSectionState {
  status: SectionStatus;
  revision: number;
  rows: number;
  fingerprint: string;
  payload: SectionPayload;
}

export interface ShiftState {
  id: string;
  status: ShiftStatus;
  team: string | null;
  conducteur: string | null;
  agent_fabrication: string | null;
  machiniste: string | null;
  aide_machiniste: string | null;
  default_lot_number: string | null;
  sections: Partial<Record<SectionKey, ShiftSectionState>>;
}

/** The review being edited: the working values, per-section choices, confirmed doubts, included pages. */
export interface ReviewValues {
  header: Record<string, string | null>;
  sections: Partial<Record<SectionKey, Record<string, GridRow[] | Row>>>;
}

export interface ReviewState {
  values?: ReviewValues;
  choices?: Partial<Record<SectionKey, Choice>>;
  confirmed?: string[];
  include_pages?: string[];
  touched?: SectionKey[];
}

export interface ScanSession {
  id: string;
  kind: "shift";
  work_center_id: string;
  report_date: string;
  shift: string;
  default_of_id: string | null;
  shift_report_id: string | null;
  status: SessionStatus;
  created_by: string;
  created_at: string;
  applied_at: string | null;
  page_count?: number;
}

export interface SessionDetail extends ScanSession {
  review_state: ReviewState;
  pages: ScanPage[];
  shift_report: ShiftState | null;
  window: { start: string; end: string } | null;
}

export interface FlagEntry {
  reason: string;
  detail: string | null;
}

export interface SourceEntry {
  page_id: string;
  box: [number, number, number, number] | null;
  text: string;
  confidence: number;
}

export interface SetAsideEntry {
  part: string;
  row: Row;
  reason: string;
}

export interface Proposal {
  header: Record<string, string | null>;
  sections: Partial<Record<SectionKey, SectionPayload>>;
  flags: Record<string, FlagEntry[]>;
  sources: Record<string, SourceEntry[]>;
  coded: Record<string, { kind: string; read_text: string; value: string | null }>;
  set_aside: Partial<Record<SectionKey, SetAsideEntry[]>>;
  pages: Record<string, { form_type: FormType | null; verdict: Verdict; reasons: string[]; importable: boolean; included: boolean }>;
}

export interface ProposalResponse {
  proposal: Proposal;
  shift: ShiftState | null;
  review_state: ReviewState;
}

export interface ApplyBody {
  header: Record<string, string | null>;
  sections: Partial<Record<SectionKey, Record<string, Row[] | Row>>>;
  fingerprints: Partial<Record<SectionKey, string | null>>;
}

export interface PageUpload {
  filename: string;
  content_type: string;
  width: number;
  height: number;
  data_base64: string;
}

export interface ShiftPage {
  id: string;
  session_id: string;
  form_type: FormType | null;
  rotation: number;
  width: number | null;
  height: number | null;
  created_at: string;
}

export interface Alias {
  id: string;
  kind: string;
  raw_text_normalized: string;
  raw_text_example: string;
  target_value: string;
  use_count: number;
  updated_at: string;
}

export type VocabularyOptions = Record<string, { value: string; label: string }[]>;

export const SCAN_QUERY_KEY = ["scan"] as const;
export const SCAN_SESSIONS_QUERY_KEY = ["scan", "sessions"] as const;
export const SCAN_ALIASES_QUERY_KEY = ["scan", "aliases"] as const;
export const scanSessionKey = (id: string) => ["scan", "session", id] as const;
export const scanProposalPrefix = (id: string) => ["scan", "proposal", id] as const;

const base = "/scan";

export function createSession(token: string, body: { work_center_id: string; report_date: string; shift: string; default_of_id: string | null }) {
  return apiFetch<ScanSession>(`${base}/sessions`, { method: "POST", body: { kind: "shift", ...body }, token });
}

export function listSessions(token: string) {
  return apiFetch<ScanSession[]>(`${base}/sessions`, { token });
}

export function getSession(token: string, id: string) {
  return apiFetch<SessionDetail>(`${base}/sessions/${id}`, { token });
}

export function uploadPages(token: string, id: string, files: PageUpload[]) {
  return apiFetch<ScanPage[]>(`${base}/sessions/${id}/pages`, { method: "POST", body: { files }, token });
}

export function deletePage(token: string, id: string, pageId: string) {
  return apiFetch<void>(`${base}/sessions/${id}/pages/${pageId}`, { method: "DELETE", token });
}

export function rereadPage(token: string, id: string, pageId: string, formHint: FormType | null) {
  return apiFetch<ScanPage>(`${base}/sessions/${id}/pages/${pageId}/reread`, { method: "POST", body: { form_hint: formHint }, token });
}

export function getProposal(token: string, id: string) {
  return apiFetch<ProposalResponse>(`${base}/sessions/${id}/proposal`, { token });
}

export function saveReview(token: string, id: string, reviewState: ReviewState) {
  return apiFetch<void>(`${base}/sessions/${id}/review`, { method: "PUT", body: { review_state: reviewState }, token });
}

export function applySession(token: string, id: string, body: ApplyBody) {
  return apiFetch<{ shift_report_id: string; sections_written: SectionKey[] }>(`${base}/sessions/${id}/apply`, { method: "POST", body, token });
}

export function discardSession(token: string, id: string) {
  return apiFetch<ScanSession>(`${base}/sessions/${id}/discard`, { method: "POST", token });
}

export function listShiftPages(token: string, shiftReportId: string) {
  return apiFetch<ShiftPage[]>(`${base}/shifts/${shiftReportId}/pages`, { token });
}

export function listAliases(token: string) {
  return apiFetch<Alias[]>(`${base}/aliases`, { token });
}

export function updateAlias(token: string, id: string, targetValue: string) {
  return apiFetch<Alias>(`${base}/aliases/${id}`, { method: "PATCH", body: { target_value: targetValue }, token });
}

export function deleteAlias(token: string, id: string) {
  return apiFetch<Alias>(`${base}/aliases/${id}`, { method: "DELETE", token });
}

export function getVocabulary(token: string, workCenterId?: string) {
  const query = workCenterId ? `?work_center_id=${encodeURIComponent(workCenterId)}` : "";
  return apiFetch<VocabularyOptions>(`${base}/vocabulary${query}`, { token });
}

/** A photo as an object URL: an <img> cannot send the session's bearer token itself. */
export async function fetchPageImage(token: string, pageId: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${base}/pages/${pageId}/image`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return URL.createObjectURL(await response.blob());
}
