/**
 * The shape of `GET /api/v1/legal/disclosure`.
 *
 * Mirrors `backend/app/services/legal/disclosure.py`, which is the source of truth. Nothing
 * here restates the CONTENT — no vendor names, no countries, no retention periods — because
 * the entire point of that module is that those are derived from the running configuration.
 * A duplicate list on this side would drift in the same way the hardcoded one it replaced did.
 */
export interface Processor {
  name: string;
  country: string;
  receives: string;
  purpose: string;
}

export interface Disclosure {
  notice_version: string;
  /** True while the wording has not been through a lawyer. The UI must surface this. */
  draft: boolean;
  processors: Processor[];
  leaves_india: boolean;
  grievance: {
    role: string;
    name: string;
    email: string;
    response_days: number;
    /** False when no contact has been appointed. Rendered as a gap, never papered over. */
    configured: boolean;
  };
  retention: { what: string; how_long: string }[];
  rights: string[];
}
