/**
 * The focus box's vocabulary — lib/interview/focus.ts
 *
 * WHAT PROBLEM THIS SOLVES. The "Anything specific?" box on the interview setup page is free
 * text, and free text is where a good idea goes to be ignored. A candidate types "revision of
 * my weak areas" and nothing happens, because there is nothing in that sentence for the
 * backend to match against; a candidate types "SQL joins" and a whole area of the plan tilts
 * towards them. From inside the textarea those two outcomes look identical, so the box read as
 * broken even in the cases where it worked.
 *
 * These are the terms that are KNOWN to land. Each one was checked against
 * `syllabus.match_focus` for the Cognizant Digital Nurture — Java FSE syllabus and each
 * resolves to a distinct area:
 *
 *     Core Java    -> Core Java              (area name)
 *     OOP          -> OOP & Class Design     (area name)
 *     React        -> React & Frontend       (area name)
 *     SQL          -> SQL & Data Modelling   (area name)
 *     Spring Boot  -> Spring Boot & REST     (area name)
 *     Coding       -> Coding Fundamentals    (area name)
 *
 * WHY "Spring Boot" AND NOT "REST". Because "REST" alone does not resolve where you would
 * expect. `match_focus` tries sub-topic containment before area names, and the React area has
 * a sub-topic "consuming a REST endpoint from a component" — so bare "REST" lands on the
 * FRONTEND area, not on Spring. That is defensible behaviour in the matcher and a trap in a
 * chip, so the chip says "Spring Boot", which resolves to "Spring Boot & REST" whole.
 *
 * WHY NO "Project" OR "HR" CHIP. They are not weighted areas of the syllabus — they are stages
 * that happen in every technical interview regardless, carried by `project_probes` and
 * `hr_themes`. A chip for them would offer a steer with nothing to steer, and the honest
 * version of that information is a sentence under the box saying they are covered either way.
 *
 * THIS LIST IS NOT A WHITELIST. The textarea stays free text and anything typed into it is
 * still sent. The chips are the discoverable path, not the only one.
 */

/** The six one-tap terms, in the order the real round reaches them. */
export const FOCUS_SUGGESTIONS = [
  'Core Java',
  'OOP',
  'React',
  'SQL',
  'Spring Boot',
  'Coding',
] as const;

/**
 * Does this focus text already name `term`?
 *
 * Case-insensitive substring, deliberately loose. The question being answered is only "should
 * the chip still offer to add this?", and the cost of the two possible mistakes is wildly
 * asymmetric: a false positive hides a chip whose term is already in the text (no loss — the
 * candidate has said the thing), while a false negative appends a duplicate into a sentence the
 * candidate wrote (visible mess in their own words).
 *
 * So "spring boot and rest" counts as naming "Spring Boot", and a candidate who typed "Java" is
 * still offered "Core Java" — mildly redundant if they take it, which is the cheaper error.
 */
export function focusMentions(text: string, term: string): boolean {
  return text.toLowerCase().includes(term.toLowerCase());
}

/**
 * `term` appended to the focus text, comma-separated.
 *
 * Comma-separated rather than newline- or space-separated because it has to read like a
 * sentence a person wrote — this text is shown back to them in the box and eventually reaches
 * the panel prompt as prose. "Core Java, SQL, Spring Boot" is a request; "Core Java SQL Spring
 * Boot" is a keyword soup that also risks being matched as one long term.
 *
 * Returns the input UNCHANGED when the term is already mentioned, so a double tap or a
 * re-render cannot duplicate it. The trailing-separator strip handles the candidate who was
 * mid-sentence — "I want SQL, " plus a chip must not become "I want SQL, , React".
 */
export function addFocusTerm(text: string, term: string): string {
  if (focusMentions(text, term)) return text;
  const base = text.trim().replace(/[,;\s]+$/, '');
  return base ? `${base}, ${term}` : term;
}
