/**
 * Model selection. The careful judgment steps (reading numbers off a page,
 * deciding which reconciliation identities apply) want a strong model;
 * Opus 4.8 is the default. Swap EXTRACTION_MODEL to claude-fable-5 for the
 * hardest unknown formats, or claude-sonnet-4-6 to cut cost on high volume.
 *
 * Note: Fable 5 / Opus 4.8 use adaptive thinking only — no budget_tokens,
 * no temperature; depth is controlled with output_config.effort.
 */
export const EXTRACTION_MODEL = "claude-opus-4-8";
