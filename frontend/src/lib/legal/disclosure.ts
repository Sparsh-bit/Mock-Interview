/**
 * The shape of `GET /api/v1/legal/disclosure`.
 *
 * Mirrors `backend/app/services/legal/disclosure.py`, which is the source of truth. Nothing
 * here restates the CONTENT — no vendor names, no countries, no retention periods — because
 * the entire point of that module is that those are derived from the running configuration.
 * A duplicate list on this side would drift in the same way the hardcoded one it replaced did.
 */
export interface Processor {
  category: string;
  country: string;
  receives: string;
  purpose: string;
}

export interface Disclosure {
  notice_version: string;
  /** True while the wording has not been through a lawyer. The UI must surface this. */
  draft: boolean;
  /**
   * Who is giving this notice. A DPDP §5 notice is issued BY a Data Fiduciary, and this
   * payload is that notice, so it has to name one. It previously described what is
   * collected, who processes it, how long it is kept and what rights attach, without ever
   * naming the party responsible for any of it.
   *
   * `product` is carried alongside `name` because a candidate arrives knowing the product
   * and not the company; the notice has to join the two for the identification to land.
   *
   * OPTIONAL BECAUSE OF DEPLOY SKEW, not because the notice is optional. The frontend and the
   * backend deploy independently - Cloudflare and Railway - so for the minutes between one
   * shipping and the other, a new frontend can be talking to a backend that predates this
   * field. Typed as required, `DisclosureBody` destructured it and read `.name`, which is a
   * TypeError, which is a 500 on a legal page. The backend always sends it; the renderer
   * guards for it.
   */
  fiduciary?: {
    name: string;
    product: string;
    role: string;
  };
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
